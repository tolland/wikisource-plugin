from datetime import datetime, timezone

import httpx
import pytest
from sqlmodel import Session
from typer.testing import CliRunner

from wtbot.api.pages import query_pages
from wtbot.cli.run_cli import create_app
from wtbot.model import Content, Page, Revision, Site, Slot

runner = CliRunner()


def _content(pk: int, model: str = "wikitext") -> dict:
    return {
        "pk": pk,
        "content_sha1": f"sha-{pk}",
        "comparable_sha1": None,
        "content_model": model,
        "text": f"body {pk}",
        "size": 6,
        "remote_sha1": None,
        "remote_size": None,
    }


def _revision(pk: int, revid: int) -> dict:
    return {
        "pk": pk,
        "page_pk": 7,
        "revid": revid,
        "parent_revid": revid - 1,
        "timestamp": "2026-08-12T12:00:00Z",
        "contributor": "Editor",
        "comment": "change",
        "minor": False,
        "observed_at": "2026-08-12T12:01:00Z",
    }


def test_query_api_filters_pages_and_returns_joined_revision_records(
    session: Session,
) -> None:
    local = Site(family="localwiki", code="en", label="local")
    other = Site(family="otherwiki", code="en", label="other")
    session.add_all((local, other))
    session.commit()

    wanted = Page(
        site_pk=local.pk,
        title="Page:Book.djvu/1",
        pageid=101,
        revid=12,
        content_model="proofread-page",
    )
    same_title_elsewhere = Page(
        site_pk=other.pk,
        title=wanted.title,
        pageid=202,
        revid=24,
    )
    session.add_all((wanted, same_title_elsewhere))
    session.commit()

    old = Revision(page_pk=wanted.pk, revid=11)
    head = Revision(
        page_pk=wanted.pk,
        revid=12,
        parent_revid=11,
        timestamp=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    session.add_all((old, head))
    session.commit()
    main = Content(content_sha1="main", content_model="wikitext", text="main", size=4)
    data = Content(content_sha1="data", content_model="json", text="{}", size=2)
    session.add_all((main, data))
    session.commit()
    session.add_all(
        (
            Slot(revision_pk=old.pk, role="main", content_pk=main.pk),
            Slot(revision_pk=head.pk, role="main", content_pk=main.pk),
            Slot(revision_pk=head.pk, role="data", content_pk=data.pk),
        )
    )
    session.commit()

    results = query_pages(
        session=session,
        title=wanted.title,
        site_label="local",
        pageid=101,
        revid=12,
        pk=None,
        title_contains=None,
        namespace_role=None,
        content_model=None,
        limit=100,
    )

    assert len(results) == 1
    result = results[0]
    assert result.page.pk == wanted.pk
    assert result.site_label == "local"
    assert [item.revision.revid for item in result.revisions] == [12, 11]
    assert [slot.role for slot in result.revisions[0].slots] == [
        "data",
        "main",
    ]
    assert result.revisions[0].slots[0].content.text == "{}"


@pytest.fixture
def query_api(monkeypatch):
    calls: list[tuple[str, dict | None]] = []
    page = {
        "pk": 7,
        "site_pk": 1,
        "title": "Page:Book.djvu/1",
        "pageid": 101,
        "revid": 12,
        "content_model": "proofread-page",
    }
    body = [
        {
            "page": page,
            "site_label": "local",
            "revisions": [
                {
                    "revision": _revision(30, 12),
                    "slots": [
                        {"role": "main", "origin_revid": 12, "content": _content(40)}
                    ],
                },
                {
                    "revision": _revision(29, 11),
                    "slots": [
                        {
                            "role": "data",
                            "origin_revid": 11,
                            "content": _content(41, "json"),
                        },
                        {"role": "main", "origin_revid": 10, "content": _content(42)},
                    ],
                },
            ],
        }
    ]

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_cli_page_query_passes_filters_and_formats_single_and_multi_slots(
    query_api,
) -> None:
    result = runner.invoke(
        create_app(),
        [
            "page",
            "query",
            "--title",
            "Page:Book.djvu/1",
            "--label",
            "local",
            "--pageid",
            "101",
        ],
    )

    assert result.exit_code == 0, result.output
    url, params = query_api[0]
    assert url.endswith("/pages/query")
    assert params["title"] == "Page:Book.djvu/1"
    assert params["site_label"] == "local"
    assert params["pageid"] == 101

    lines = result.output.splitlines()
    assert lines[0].startswith("page #7 local:Page:Book.djvu/1")
    assert lines[1].startswith("  revision #30")
    assert " | slot=main " in lines[1]
    assert lines[2].startswith("  revision #29") and "slots=2" in lines[2]
    assert lines[3].startswith("    slot=data ")
    assert lines[4].startswith("    slot=main ")


def test_cli_page_query_reports_no_matches(monkeypatch) -> None:
    def fake_get(url, params=None, timeout=None):
        return httpx.Response(200, json=[], request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    result = runner.invoke(create_app(), ["page", "query", "--pk", "999"])

    assert result.exit_code == 0
    assert result.output == "no pages matched\n"
