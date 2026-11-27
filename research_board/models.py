from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

APP_ID = "research-board"
APP_VERSION = "1.0.0"
STATE_SCHEMA_VERSION = "1.0"
MAX_ENTITIES = 60
MAX_LINKS = 120
MAX_STATE_VERSION = (2 ** 53) - 1

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Version = Annotated[int, Field(strict=True, ge=1, le=MAX_STATE_VERSION)]


def safe_url(url: HttpUrl) -> HttpUrl:
    if url.username is not None or url.password is not None or len(str(url)) > 2000:
        raise ValueError("Source URL must have no credentials and be at most 2000 characters")
    return url


SourceURL = Annotated[HttpUrl, AfterValidator(safe_url)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(Model):
    id: Identifier
    text: Text


class Source(Model):
    id: Identifier
    title: Title
    url: SourceURL


class Evidence(Model):
    id: Identifier
    source_id: Identifier
    excerpt: Text
    locator: Title | None = None


class Resolution(Model):
    status: Literal["open", "resolved"]
    note: Text | None = None

    @model_validator(mode="after")
    def validate_note(self) -> Self:
        if (self.status == "resolved") != (self.note is not None):
            raise ValueError("A resolution note is required for resolved contradictions only")
        return self


class Link(Model):
    id: Identifier
    from_type: Literal["evidence", "claim"] = "evidence"
    from_id: Identifier
    to_claim_id: Identifier
    relation: Literal["supports", "contradicts"]

    @model_validator(mode="after")
    def validate_direction(self) -> Self:
        if self.from_type == "claim":
            if self.relation != "contradicts":
                raise ValueError("Supporting links must start at evidence")
            if self.from_id == self.to_claim_id:
                raise ValueError("A claim cannot contradict itself")
        return self


class Contradiction(Model):
    link_id: Identifier
    resolution: Resolution


def unique_ids(items: list, kind: str) -> set[str]:
    ids = {item.id for item in items}
    if len(ids) != len(items):
        raise ValueError(f"Duplicate {kind} ID")
    return ids


class Board(Model):
    title: Title
    claims: list[Claim] = Field(default_factory=list, max_length=MAX_ENTITIES)
    sources: list[Source] = Field(default_factory=list, max_length=MAX_ENTITIES)
    evidence: list[Evidence] = Field(default_factory=list, max_length=MAX_ENTITIES)
    links: list[Link] = Field(default_factory=list, max_length=MAX_LINKS)
    resolutions: list[Contradiction] = Field(default_factory=list, max_length=MAX_LINKS)

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        claim_ids = unique_ids(self.claims, "claim")
        source_ids = unique_ids(self.sources, "source")
        evidence_ids = unique_ids(self.evidence, "evidence")
        unique_ids(self.links, "link")

        for evidence in self.evidence:
            if evidence.source_id not in source_ids:
                raise ValueError(f"Evidence {evidence.id} references an unknown source")

        directions = set()
        contradiction_ids = set()
        for link in self.links:
            from_ids = evidence_ids if link.from_type == "evidence" else claim_ids
            if link.from_id not in from_ids or link.to_claim_id not in claim_ids:
                raise ValueError(f"Link {link.id} references an unknown endpoint")
            direction = (link.from_type, link.from_id, link.to_claim_id)
            if direction in directions:
                raise ValueError(f"Duplicate directed link to claim {link.to_claim_id}")
            directions.add(direction)
            if link.relation == "contradicts":
                contradiction_ids.add(link.id)

        resolution_ids = {item.link_id for item in self.resolutions}
        if len(resolution_ids) != len(self.resolutions) or not resolution_ids <= contradiction_ids:
            raise ValueError("Each resolution must refer to a unique contradicting link")
        return self


class StateEnvelope(Model):
    session_id: str
    app_id: Literal["research-board"] = APP_ID
    app_version: str = APP_VERSION
    state_schema_version: Literal["1.0"] = STATE_SCHEMA_VERSION
    state_version: Version
    payload: Board
    updated_at: datetime


class FixtureInput(Model):
    kind: Literal["fixture"]
    fixture: Literal["urban-trees"]


class StructuredInput(Model):
    kind: Literal["structured"]
    board: Board


class Launch(Model):
    conversation_id: Identifier
    actor_id: Identifier = "local-user"
    input: Annotated[FixtureInput | StructuredInput, Field(discriminator="kind")]


class ClaimAction(Model):
    action: Literal["add_claim", "update_claim"]
    claim: Claim


class SourceAction(Model):
    action: Literal["add_source", "update_source"]
    source: Source


class EvidenceAction(Model):
    action: Literal["add_evidence", "update_evidence"]
    evidence: Evidence


class AddLink(Model):
    action: Literal["add_link"]
    link: Link


class RemoveLink(Model):
    action: Literal["remove_link"]
    link_id: Identifier


class SetResolution(Model):
    action: Literal["set_resolution"]
    link_id: Identifier
    resolution: Resolution


class DeleteClaim(Model):
    action: Literal["delete_claim"]
    claim_id: Identifier


class BulkDeleteLinks(Model):
    action: Literal["bulk_delete_links"]
    link_ids: list[Identifier] = Field(min_length=2, max_length=MAX_LINKS)

    @model_validator(mode="after")
    def unique_links(self) -> Self:
        if len(set(self.link_ids)) != len(self.link_ids):
            raise ValueError("Bulk deletion requires distinct link IDs")
        return self


class Export(Model):
    action: Literal["export"]


Operation = Annotated[
    ClaimAction | SourceAction | EvidenceAction | AddLink | RemoveLink | SetResolution |
    DeleteClaim | BulkDeleteLinks | Export,
    Field(discriminator="action"),
]


class ActionRequest(Model):
    expected_version: Version
    operation: Operation


class Decision(Model):
    decision: Literal["approve", "reject"]
