from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from research_board.models import (
    AddLink,
    Board,
    BulkDeleteLinks,
    Claim,
    ClaimAction,
    DeleteClaim,
    EvidenceAction,
    Link,
    Operation,
    RemoveLink,
    Resolution,
    SetResolution,
    SourceAction,
    StateEnvelope,
)


class InvalidAction(ValueError):
    pass


def upsert(items: list, item, add: bool) -> None:
    for index, existing in enumerate(items):
        if existing["id"] == item.id:
            if add:
                raise InvalidAction(f"ID {item.id} is already in use")
            items[index] = item.model_dump(mode="json")
            return
    if not add:
        raise InvalidAction(f"Unknown ID {item.id}")
    items.append(item.model_dump(mode="json"))


def remove_links(payload: dict, ids: set[str]) -> None:
    if not ids <= {link["id"] for link in payload["links"]}:
        raise InvalidAction("Unknown link ID")
    payload["links"] = [link for link in payload["links"] if link["id"] not in ids]
    payload["resolutions"] = [
        resolution for resolution in payload["resolutions"] if resolution["link_id"] not in ids
    ]


def apply_operation(board: Board, operation: Operation) -> Board:
    payload = board.model_dump(mode="json")
    match operation:
        case ClaimAction(action=action, claim=claim):
            upsert(payload["claims"], claim, action == "add_claim")
        case SourceAction(action=action, source=source):
            upsert(payload["sources"], source, action == "add_source")
        case EvidenceAction(action=action, evidence=evidence):
            upsert(payload["evidence"], evidence, action == "add_evidence")
        case AddLink(link=link):
            upsert(payload["links"], link, add=True)
        case RemoveLink(link_id=link_id):
            remove_links(payload, {link_id})
        case SetResolution(link_id=link_id, resolution=resolution):
            payload["resolutions"] = [
                item for item in payload["resolutions"] if item["link_id"] != link_id
            ]
            payload["resolutions"].append({
                "link_id": link_id,
                "resolution": resolution.model_dump(),
            })
        case DeleteClaim(claim_id=claim_id):
            if not any(claim.id == claim_id for claim in board.claims):
                raise InvalidAction(f"Unknown claim {claim_id}")
            payload["claims"] = [claim for claim in payload["claims"] if claim["id"] != claim_id]
            remove_links(payload, {
                link.id for link in board.links
                if link.to_claim_id == claim_id or (link.from_type == "claim" and link.from_id == claim_id)
            })
        case BulkDeleteLinks(link_ids=link_ids):
            remove_links(payload, set(link_ids))
        case _:
            raise InvalidAction("Operation does not update the board")
    return Board.model_validate(payload)


@dataclass
class ClaimAssessment:
    claim: Claim
    evidence_links: list[Link]
    contradictions: list[Link]
    unresolved_ids: list[str]
    support_ids: list[str]

    @property
    def status(self) -> Literal["disputed", "supported", "unsupported"]:
        if self.unresolved_ids:
            return "disputed"
        if self.support_ids:
            return "supported"
        return "unsupported"


class BoardAssessment:
    def __init__(self, board: Board):
        self.resolutions = {item.link_id: item.resolution for item in board.resolutions}
        self.open_contradictions = [
            link for link in board.links
            if link.relation == "contradicts" and self.resolution(link).status == "open"
        ]
        open_ids = {link.id for link in self.open_contradictions}
        evidence_links = defaultdict(list)
        contradictions = defaultdict(list)
        for link in board.links:
            if link.from_type == "evidence":
                evidence_links[link.to_claim_id].append(link)
            if link.relation == "contradicts":
                contradictions[link.to_claim_id].append(link)
                if link.from_type == "claim":
                    contradictions[link.from_id].append(link)
        self.claims = [
            ClaimAssessment(
                claim,
                evidence_links[claim.id],
                contradictions[claim.id],
                [link.id for link in contradictions[claim.id] if link.id in open_ids],
                [link.from_id for link in evidence_links[claim.id] if link.relation == "supports"],
            )
            for claim in board.claims
        ]

    def resolution(self, link: Link) -> Resolution:
        return self.resolutions.get(link.id) or Resolution(status="open")


def handoff(state: StateEnvelope, conversation_id: str) -> dict:
    board = state.payload
    assessment = BoardAssessment(board)
    claims = [
        {
            **item.claim.model_dump(mode="json"),
            "status": item.status,
            "evidence_ids": [link.from_id for link in item.evidence_links],
            "supporting_evidence_ids": item.support_ids,
            "unresolved_contradiction_ids": item.unresolved_ids,
        }
        for item in assessment.claims
    ]
    return {
        "app_id": state.app_id,
        "session_id": state.session_id,
        "conversation_id": conversation_id,
        "state_version": state.state_version,
        "result": {
            "title": board.title,
            "claims": claims,
            "confirmed_claims": [claim for claim in claims if claim["status"] == "supported"],
            "evidence": [evidence.model_dump(mode="json") for evidence in board.evidence],
            "sources": [source.model_dump(mode="json") for source in board.sources],
            "links": [link.model_dump(mode="json") for link in board.links],
            "unresolved_contradictions": [
                {**link.model_dump(mode="json"), "status": "open"}
                for link in assessment.open_contradictions
            ],
            "unsourced_claims": [claim for claim in claims if not claim["evidence_ids"]],
            "unsupported_claims": [claim for claim in claims if not claim["supporting_evidence_ids"]],
        },
    }
