"""The change feed: workers write it, REST and the websocket read it."""

import pytest
from conftest import register_site
from fastapi.testclient import TestClient

from wtbot.main import create_app
from wtbot.model import EventKind, FetchStatus
from wtbot.wiki.client import FakeWikiClient

LABEL = "test"


@pytest.fixture
def client(engine):
    app = create_app(
        engine=engine, client_factory=lambda site: FakeWikiClient(pages={})
    )
    with TestClient(app) as c:
        register_site(c, label=LABEL)
        yield c


def _kinds(client: TestClient) -> list[str]:
    return [e["kind"] for e in client.get("/events").json()["events"]]


def test_queue_drain_and_failure_are_all_on_the_feed(client):
    pk = client.post(
        "/fetch/", json={"title": "Index:Nope.djvu", "label": LABEL}
    ).json()["request"]["pk"]
    client.post("/fetch/drain")

    events = client.get("/events").json()["events"]
    assert [e["kind"] for e in events] == [
        EventKind.queued.value,
        EventKind.drain_started.value,
        EventKind.failed.value,
        EventKind.drain_finished.value,
    ]
    failed = events[2]
    assert failed["request_pk"] == pk
    assert failed["level"] == "error"
    assert "not found" in failed["message"]
    # Ordered by pk, so `after` is a usable cursor.
    after = events[1]["pk"]
    tail = client.get("/events", params={"after": after}).json()["events"]
    assert [e["kind"] for e in tail] == ["failed", "drain_finished"]


def test_retry_requeues_errored_requests_and_says_so(client):
    pk = client.post(
        "/fetch/", json={"title": "Index:Nope.djvu", "label": LABEL}
    ).json()["request"]["pk"]
    client.post("/fetch/drain")
    assert client.get(f"/fetch/{pk}").json()["status"] == FetchStatus.error.value

    assert client.post("/fetch/retry").json() == {"requeued": [pk]}
    row = client.get(f"/fetch/{pk}").json()
    assert row["status"] == FetchStatus.pending.value
    assert row["error_message"] is None
    assert _kinds(client)[-1] == EventKind.retried.value
    # Nothing is errored now, so nothing more to retry.
    assert client.post("/fetch/retry").json() == {"requeued": []}


def test_requests_listing_filters_by_status(client):
    client.post("/fetch/", json={"title": "Index:A.djvu", "label": LABEL})
    client.post("/fetch/drain")
    client.post("/fetch/", json={"title": "Index:B.djvu", "label": LABEL})

    assert [
        r["title"]
        for r in client.get("/fetch/requests", params={"status": "pending"}).json()
    ] == ["Index:B.djvu"]
    assert [
        r["title"]
        for r in client.get("/fetch/requests", params={"status": "error"}).json()
    ] == ["Index:A.djvu"]


def test_background_drain_works_the_queue_and_reports_on_the_feed(client):
    client.post("/fetch/", json={"title": "Index:Nope.djvu", "label": LABEL})

    assert client.post("/fetch/drain/background").json()["started"] is True
    client.app.state.background_drain.join(30)

    assert client.get("/fetch/queue").json()["pending"] == 0
    assert _kinds(client)[-2:] == ["failed", "drain_finished"]


def test_websocket_replays_then_tails_and_resumes_after_a_cursor(client):
    client.post("/fetch/", json={"title": "Index:Nope.djvu", "label": LABEL})

    with client.websocket_connect("/events/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "event" and first["event"]["kind"] == "queued"
        queue = ws.receive_json()
        assert queue["type"] == "queue" and queue["pending"] == 1
        last_seen = first["event"]["pk"]

        client.post("/fetch/drain")
        seen: list[str] = []
        while "drain_finished" not in seen:
            frame = ws.receive_json()
            if frame["type"] == "event":
                seen.append(frame["event"]["kind"])
        assert seen == ["drain_started", "failed", "drain_finished"]

    # A reconnect with the cursor gets exactly what was missed, not a replay.
    with client.websocket_connect(f"/events/ws?after={last_seen}") as ws:
        frame = ws.receive_json()
        assert frame["event"]["kind"] == "drain_started"
