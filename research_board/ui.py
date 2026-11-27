from typing import Literal

from research_board.board import BoardAssessment, ClaimAssessment
from research_board.models import StateEnvelope

BoardFilter = Literal["Все", "Без подтверждения", "С противоречиями", "Без источников"]
FILTER_OPTIONS = ["Все", "Без подтверждения", "С противоречиями", "Без источников"]
STATUS_LABELS = {
    "supported": "Подкреплено доказательствами",
    "unsupported": "Без подтверждения",
    "disputed": "Есть неразрешённое противоречие",
}


def text(value: str) -> dict:
    return {"component_type": "text", "props": {"text": value}}


def card(title: str, nodes: list[dict]) -> dict:
    return {"component_type": "card", "props": {"title": title}, "nodes": nodes}


def form(label: str, action: str) -> dict:
    return {"component_type": "form", "props": {"label": label, "action": action}, "nodes": []}


def source_link(label: str, href: str) -> dict:
    return {"component_type": "source-link", "props": {"label": label, "href": href}}


def matches_filter(item: ClaimAssessment, board_filter: BoardFilter) -> bool:
    match board_filter:
        case "Без подтверждения":
            return not item.support_ids
        case "С противоречиями":
            return bool(item.unresolved_ids)
        case "Без источников":
            return not item.evidence_links
        case _:
            return True


def ui_schema(state: StateEnvelope, board_filter: BoardFilter) -> dict:
    board = state.payload
    assessment = BoardAssessment(board)
    sources = {source.id: source for source in board.sources}
    evidence = {item.id: item for item in board.evidence}
    claims = {claim.id: claim for claim in board.claims}
    claim_cards = []
    for item in assessment.claims:
        if not matches_filter(item, board_filter):
            continue
        nodes = [text(STATUS_LABELS[item.status])]
        if not item.evidence_links:
            nodes.append(text("Нет привязанных источников"))
        evidence_cards = []
        for link in item.evidence_links:
            fragment = evidence[link.from_id]
            source = sources[fragment.source_id]
            details = [source_link(source.title, str(source.url)), text(fragment.excerpt)]
            if fragment.locator:
                details.append(text(fragment.locator))
            if link.relation == "contradicts":
                resolution = assessment.resolution(link)
                if resolution.note:
                    details.append(text(f"Решение: {resolution.note}"))
            title = "Поддерживает" if link.relation == "supports" else "Противоречит"
            evidence_cards.append(card(title, details))
        if evidence_cards:
            nodes.append(card("Доказательства", evidence_cards))
        claim_conflicts = []
        for link in item.contradictions:
            if link.from_type != "claim":
                continue
            # Render a directed claim link on its target card only.
            if link.to_claim_id != item.claim.id:
                continue
            resolution = assessment.resolution(link)
            details = [text(claims[link.from_id].text)]
            if resolution.note:
                details.append(text(f"Решение: {resolution.note}"))
            claim_conflicts.append(card("Противоречащее утверждение", details))
        if claim_conflicts:
            nodes.append(card("Противоречия между утверждениями", claim_conflicts))
        claim_cards.append(card(item.claim.text, nodes))

    source_cards = []
    for source in board.sources:
        source_nodes = [source_link(source.title, str(source.url))]
        for fragment in board.evidence:
            if fragment.source_id == source.id:
                source_nodes.append(card(fragment.locator or "Фрагмент", [text(fragment.excerpt)]))
        source_cards.append(card(source.title, source_nodes))

    return {
        "schema_version": "1.0",
        "app_id": state.app_id,
        "nodes": [
            card(board.title, [
                text(f"Неразрешённые противоречия: {len(assessment.open_contradictions)}"),
                {"component_type": "filter", "props": {
                    "label": "Утверждения", "options": FILTER_OPTIONS, "action": "filter_claims",
                }},
                form("Добавить утверждение", "add_claim"),
                form("Добавить источник", "add_source"),
                form("Добавить доказательство", "add_evidence"),
                form("Добавить связь", "add_link"),
            ]),
            card("Утверждения", claim_cards or [text("Нет утверждений для выбранного фильтра")]),
            card("Источники", source_cards or [text("Нет источников")]),
            form("Вернуть итог в чат", "handoff"),
            form("Экспортировать доску", "export"),
        ],
    }
