from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from research_board.app import create_app

BASE = "/api/research-board/sessions"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "research-board.db")) as test_client:
        yield test_client


def launch(client, board=None, conversation_id="conversation-1"):
    source = {"kind": "fixture", "fixture": "urban-trees"}
    if board is not None:
        source = {"kind": "structured", "board": board}
    return client.post(BASE, json={"conversation_id": conversation_id, "input": source})


def session_url(response):
    assert response.status_code == 201, response.text
    return f"{BASE}/{response.json()['state']['session_id']}"


def action(client, url, version, name, **fields):
    return client.post(f"{url}/actions", json={
        "expected_version": version,
        "operation": {"action": name, **fields},
    })


def decide(client, url, response, decision):
    assert response.status_code == 202, response.text
    confirmation_id = response.json()["confirmation"]["id"]
    return client.post(f"{url}/confirmations/{confirmation_id}", json={"decision": decision})


def claim_ids(result, field):
    return {claim["id"] for claim in result[field]}


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get("nodes", []))


def test_fixture_chat_board_chat_round_trip(client):
    launched = launch(client)
    url = session_url(launched)
    schema = launched.json()["ui_schema"]
    assert schema["schema_version"] == "1.0"
    assert {node["component_type"] for node in walk(schema["nodes"])} == {
        "card", "text", "source-link", "filter", "form",
    }

    updated = action(client, url, 1, "update_claim", claim={
        "id": "night-heat", "text": "Ночной эффект охлаждения требует дополнительной проверки.",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["state"]["state_version"] == 2

    filtered = client.get(url, params={"board_filter": "Без источников"}).json()["ui_schema"]
    assert len(filtered["nodes"][1]["nodes"]) == 1
    assert "расходы" in filtered["nodes"][1]["nodes"][0]["props"]["title"]

    returned = client.get(f"{url}/handoff").json()
    assert returned["conversation_id"] == "conversation-1"
    assert returned["app_id"] == "research-board"
    assert returned["state_version"] == 2
    assert returned["state"] == updated.json()["state"]
    result = returned["result"]
    assert claim_ids(result, "confirmed_claims") == {"summer-heat"}
    assert claim_ids(result, "unsourced_claims") == {"maintenance"}
    assert claim_ids(result, "unsupported_claims") == {"night-heat", "maintenance"}
    assert [link["id"] for link in result["unresolved_contradictions"]] == ["night-contradiction"]
    assert result["claims"][1]["text"] == "Ночной эффект охлаждения требует дополнительной проверки."
    original = client.get(f"{url}/handoff", params={"version": 1}).json()
    assert original["state"] == launched.json()["state"]


def test_structured_chat_board_chat_round_trip_after_restart(tmp_path):
    db = tmp_path / "research-board.db"
    board = {
        "title": "Учебное сравнение транспорта",
        "claims": [{"id": "travel-time", "text": "Трамвай быстрее автобуса на каждом рейсе."}],
        "sources": [{"id": "survey", "title": "Учебные замеры", "url": "https://example.org/transit"}],
        "evidence": [
            {"id": "median", "source_id": "survey", "excerpt": "Медиана: 20 против 25 минут."},
            {"id": "exception", "source_id": "survey", "excerpt": "Один трамвай опоздал на 12 минут."},
        ],
        "links": [
            {"id": "sample-support", "from_id": "median", "to_claim_id": "travel-time", "relation": "supports"},
            {"id": "exception-link", "from_id": "exception", "to_claim_id": "travel-time", "relation": "contradicts"},
        ],
    }
    with TestClient(create_app(db)) as client:
        url = session_url(launch(client, board, "conversation-2"))
        assert not client.get(f"{url}/handoff").json()["result"]["confirmed_claims"]
        changed = action(client, url, 1, "update_claim", claim={
            "id": "travel-time", "text": "Медианное время поездки на трамвае меньше в этой выборке.",
        })
        assert changed.status_code == 200, changed.text
        resolution = {"status": "resolved", "note": "Утверждение теперь касается медианы выборки."}
        resolved = action(client, url, 2, "set_resolution", link_id="exception-link", resolution=resolution)
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["state"]["state_version"] == 3

    with TestClient(create_app(db)) as client:
        saved = client.get(url).json()["state"]
        returned = client.get(f"{url}/handoff").json()
        assert returned["conversation_id"] == "conversation-2"
        assert returned["state_version"] == 3
        assert saved == returned["state"] == resolved.json()["state"]
        assert saved["payload"]["resolutions"] == [{"link_id": "exception-link", "resolution": resolution}]
        assert not returned["result"]["unresolved_contradictions"]
        assert claim_ids(returned["result"], "confirmed_claims") == {"travel-time"}
        assert returned["result"]["confirmed_claims"][0]["supporting_evidence_ids"] == ["median"]


def test_confirmation_audit_and_stale_or_replayed_decisions(client):
    url = session_url(launch(client))
    stale = action(client, url, 1, "delete_claim", claim_id="summer-heat")
    assert "summer-heat" in claim_ids(client.get(f"{url}/handoff").json()["result"], "claims")

    second = action(client, url, 1, "add_claim", claim={"id": "additional", "text": "New claim"})
    assert second.status_code == 200
    assert decide(client, url, stale, "approve").status_code == 409
    assert decide(client, url, stale, "approve").status_code == 409

    pending = action(client, url, 2, "bulk_delete_links", link_ids=["day-support", "night-contradiction"])
    denied = decide(client, url, pending, "reject")
    assert denied.json()["confirmation"]["status"] == "rejected"
    assert len(denied.json()["state"]["payload"]["links"]) == 2
    assert denied.json()["state"]["state_version"] == 2

    pending = action(client, url, 2, "bulk_delete_links", link_ids=["day-support", "night-contradiction"])
    approved = decide(client, url, pending, "approve")
    assert approved.json()["state"]["state_version"] == 3
    assert approved.json()["state"]["payload"]["links"] == []

    export = action(client, url, 3, "export")
    assert "export" not in export.json()["confirmation"]
    exported = decide(client, url, export, "approve").json()
    assert exported["confirmation"]["export"] == exported["state"]
    assert exported["state"]["state_version"] == 3
    assert decide(client, url, export, "approve").status_code == 409

    deletion = action(client, url, 3, "delete_claim", claim_id="summer-heat")
    removed = decide(client, url, deletion, "approve").json()
    assert removed["state"]["state_version"] == 4
    assert "summer-heat" not in {claim["id"] for claim in removed["state"]["payload"]["claims"]}
    audit = client.get(f"{url}/audit").json()["events"]
    assert [event["event"] for event in audit] == [
        "requested", "stale", "requested", "rejected", "requested", "approved", "executed",
        "requested", "approved", "executed", "requested", "approved", "executed",
    ]
    assert all(event["session_id"] == removed["state"]["session_id"] for event in audit)
    assert all(event["actor_id"] == "local-user" for event in audit)
    assert audit[-1]["expected_version"] == 3
    assert audit[-1]["state_version"] == 4


@pytest.mark.parametrize("board", [
    {"title": "Duplicate", "claims": [{"id": "a", "text": "One"}, {"id": "a", "text": "Two"}]},
    {"title": "Dangling", "evidence": [{"id": "e", "source_id": "missing", "excerpt": "A"}]},
    {"title": "Unsafe", "sources": [{"id": "s", "title": "URL", "url": "javascript:alert(1)"}]},
    {"title": "Unsafe", "sources": [{"id": "s", "title": "URL", "url": "https://user:pass@example.org"}]},
    {"title": "Injected", "claims": [{"id": "a", "text": "Text", "status": "proven"}]},
    {
        "title": "Dangling resolution",
        "resolutions": [{"link_id": "missing", "resolution": {"status": "resolved", "note": "Reviewed"}}],
    },
])
def test_invalid_board_input_is_rejected(client, board):
    assert launch(client, board).status_code == 422


def test_concurrent_edits_commit_only_one_expected_version(client):
    url = session_url(launch(client))
    with ThreadPoolExecutor(max_workers=2) as executor:
        writes = list(executor.map(
            lambda key: action(client, url, 1, "add_claim", claim={"id": key, "text": key}),
            ["first", "second"],
        ))
    assert sorted(response.status_code for response in writes) == [200, 409]
    current = client.get(url).json()["state"]
    assert current["state_version"] == 2
    assert len(current["payload"]["claims"]) == 4


def test_delete_claim_cascades_links_and_resolutions_only_after_confirmation(client):
    url = session_url(launch(client))
    resolved = action(client, url, 1, "set_resolution", link_id="night-contradiction",
                      resolution={"status": "resolved", "note": "Reviewed"})
    assert resolved.status_code == 200
    pending = action(client, url, 2, "delete_claim", claim_id="night-heat")
    assert len(pending.json()["state"]["payload"]["resolutions"]) == 1
    result = decide(client, url, pending, "approve")
    assert result.status_code == 200
    board = result.json()["state"]["payload"]
    assert [link["id"] for link in board["links"]] == ["day-support"]
    assert not board["resolutions"]
    assert len(board["evidence"]) == 2


def test_maximum_board_fits_renderer_limits(client):
    long_text = "📚" * 4000
    board = {
        "title": "Maximum board",
        "claims": [{"id": f"c{i}", "text": long_text} for i in range(60)],
        "sources": [{"id": f"s{i}", "title": "Source", "url": "https://example.org/"} for i in range(60)],
        "evidence": [
            {"id": f"e{i}", "source_id": "s0", "locator": "Section", "excerpt": long_text}
            for i in range(60)
        ],
        "links": [
            {"id": f"e{i}-c{j}", "from_id": f"e{i}", "to_claim_id": f"c{j}", "relation": "contradicts"}
            for i in range(60) for j in range(2)
        ],
        "resolutions": [
            {"link_id": f"e{i}-c{j}", "resolution": {"status": "resolved", "note": long_text}}
            for i in range(60) for j in range(2)
        ],
    }
    launched = launch(client, board)
    session_url(launched)
    schema = launched.json()["ui_schema"]

    def value_count(value, depth=0):
        assert depth <= 32
        if isinstance(value, dict):
            return 1 + sum(value_count(child, depth + 1) for child in value.values())
        if isinstance(value, list):
            assert len(value) <= 100
            return 1 + sum(value_count(child, depth + 1) for child in value)
        if isinstance(value, str):
            assert len(value.encode("utf-16-le")) // 2 <= 10000
        return 1

    assert value_count(schema) <= 10000
