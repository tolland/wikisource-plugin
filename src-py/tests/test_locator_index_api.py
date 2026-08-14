import pytest
from conftest import add_proofread_meta
from sqlmodel import Session, select

from wtbot.model import EditJournal, Page, Site
from wtbot.model.wiki.namespace import NsRole

"""Tests for GET /locator-index/{page-numbers,sections} — resolving a
back-of-book locator to the Page: that holds it. Mirrors test_page_nav.py's
seeding style (direct session inserts, no fetch/drain harness needed since
this endpoint only reads what's already cached)."""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Principles_of_mechanics.pdf"
INDEX_PATH = f"/{FAMILY}/{CODE}/{INDEX}"

_PAGELIST_BODY = "<pagelist from=155 to=170 155=121 170=- />"

_PARAGRAPH_273_BODY = (
    "<section begin=\"p-273\" />{{anchor|p-273}}273. '''Definition'''. "
    "The instantaneous rate of change of the velocity of a system is called "
    "its acceleration."
    '<section end="p-273" />'
)


def _page_path(title: str) -> str:
    return f"{INDEX_PATH}/Pages/{title}"


def _seed(engine) -> None:
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.flush()
        index = Page(
            site_pk=site.pk,
            title=INDEX,
            namespace_role=NsRole.index,
            content_model="proofread-index",
            text=_PAGELIST_BODY,
        )
        s.add(index)

        page_155 = Page(
            site_pk=site.pk,
            title="Page:Principles_of_mechanics.pdf/155",
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text="the explicit pagelist anchor page",
        )
        s.add(page_155)
        s.flush()
        add_proofread_meta(s, page_pk=page_155.pk, index_title=INDEX, page_number=155)

        page_163 = Page(
            site_pk=site.pk,
            title="Page:Principles_of_mechanics.pdf/163",
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text=_PARAGRAPH_273_BODY,
        )
        s.add(page_163)
        s.flush()
        add_proofread_meta(s, page_pk=page_163.pk, index_title=INDEX, page_number=163)

        page_164 = Page(
            site_pk=site.pk,
            title="Page:Principles_of_mechanics.pdf/164",
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text="no section markers on this one",
        )
        s.add(page_164)
        s.flush()
        add_proofread_meta(s, page_pk=page_164.pk, index_title=INDEX, page_number=164)
        s.commit()


@pytest.fixture
def seeded(engine):
    _seed(engine)


BARE_INDEX = "Index:NeglectedArgument.pdf"
BARE_INDEX_PATH = f"/{FAMILY}/{CODE}/{BARE_INDEX}"


def _seed_bare_pagelist(engine) -> None:
    # Index:NeglectedArgument.pdf's real Index page: a bare <pagelist />
    # with no attributes at all, which means straight 1:1 numbering.
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.flush()
        index = Page(
            site_pk=site.pk,
            title=BARE_INDEX,
            namespace_role=NsRole.index,
            content_model="proofread-index",
            text="<pagelist />",
        )
        s.add(index)
        for n in (1, 2, 50):
            page = Page(
                site_pk=site.pk,
                title=f"Page:NeglectedArgument.pdf/{n}",
                namespace_role=NsRole.page,
                content_model="proofread-page",
                text="",
            )
            s.add(page)
            s.flush()
            add_proofread_meta(
                s, page_pk=page.pk, index_title=BARE_INDEX, page_number=n
            )
        s.commit()


@pytest.fixture
def seeded_bare(engine):
    _seed_bare_pagelist(engine)


def test_page_number_exact_match_is_inferred(client, seeded):
    r = client.get(
        "/locator-index/page-numbers",
        params={"path": INDEX_PATH, "query": "129"},
    )
    assert r.status_code == 200
    matches = r.json()
    assert len(matches) == 1
    assert matches[0]["label"] == "129"
    assert matches[0]["confidence"] == "inferred"
    assert matches[0]["page"]["path"] == _page_path(
        "Page:Principles_of_mechanics.pdf/163"
    )
    assert matches[0]["page"]["scan_page"] == 163


def test_page_number_lookup_works_from_a_page_path_too(client, seeded):
    # The Page: path resolves to the same Index, per GET /pages/nav's contract.
    r = client.get(
        "/locator-index/page-numbers",
        params={
            "path": _page_path("Page:Principles_of_mechanics.pdf/164"),
            "query": "129",
        },
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_explicit_min_confidence_excludes_inferred_matches(client, seeded):
    r = client.get(
        "/locator-index/page-numbers",
        params={"path": INDEX_PATH, "query": "129", "min_confidence": "explicit"},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_explicit_min_confidence_still_returns_explicit_matches(client, seeded):
    r = client.get(
        "/locator-index/page-numbers",
        params={"path": INDEX_PATH, "query": "121", "min_confidence": "explicit"},
    )
    assert r.status_code == 200
    matches = r.json()
    assert len(matches) == 1
    assert matches[0]["confidence"] == "explicit"
    assert matches[0]["page"]["scan_page"] == 155


def test_page_number_prefix_match(client, seeded):
    r = client.get(
        "/locator-index/page-numbers",
        params={"path": INDEX_PATH, "query": "12"},
    )
    assert r.status_code == 200
    labels = {m["label"] for m in r.json()}
    # 155=121 (explicit), 163 -> 129 (inferred), 164 -> 130 (inferred)
    assert "121" in labels
    assert "129" in labels


def test_bare_pagelist_defaults_pages_to_one_to_one(client, seeded_bare):
    r = client.get(
        "/locator-index/page-numbers",
        params={"path": BARE_INDEX_PATH, "query": "50"},
    )
    assert r.status_code == 200
    matches = r.json()
    assert len(matches) == 1
    assert matches[0]["label"] == "50"
    assert matches[0]["confidence"] == "inferred"
    assert matches[0]["page"]["scan_page"] == 50


def test_bare_pagelist_dump_shows_every_page_numbered(client, seeded_bare):
    r = client.get("/locator-index/dump", params={"path": BARE_INDEX_PATH})
    assert r.status_code == 200
    dump = r.json()
    assert dump["pagelist_assignments"] == []
    labels = {p["page"]["scan_page"]: p["label"] for p in dump["pages"]}
    assert labels == {1: "1", 2: "2", 50: "50"}


def test_section_lookup_finds_the_begin_occurrence(client, seeded):
    r = client.get(
        "/locator-index/sections",
        params={"path": INDEX_PATH, "query": "p-273"},
    )
    assert r.status_code == 200
    matches = r.json()
    roles = {m["role"] for m in matches}
    assert "begin" in roles
    assert "anchor_template" in roles
    assert "end" not in roles  # not in the default roles filter
    for m in matches:
        assert m["page"]["scan_page"] == 163


def test_section_lookup_can_include_end_role(client, seeded):
    r = client.get(
        "/locator-index/sections",
        params={
            "path": INDEX_PATH,
            "query": "p-273",
            "roles": "begin,end,anchor_template",
        },
    )
    assert r.status_code == 200
    roles = {m["role"] for m in r.json()}
    assert roles == {"begin", "end", "anchor_template"}


def test_section_lookup_no_match_is_empty(client, seeded):
    r = client.get(
        "/locator-index/sections",
        params={"path": INDEX_PATH, "query": "p-999"},
    )
    assert r.status_code == 200
    assert r.json() == []


def test_dump_returns_everything_unfiltered(client, seeded):
    r = client.get("/locator-index/dump", params={"path": INDEX_PATH})
    assert r.status_code == 200
    dump = r.json()
    assert dump["index_title"] == INDEX
    assert dump["index_path"] == INDEX_PATH

    # Raw pagelist entries: exactly the two explicit ones from _PAGELIST_BODY.
    raw = {a["scan_page"]: a for a in dump["pagelist_assignments"]}
    assert raw[155] == {
        "scan_page": 155,
        "kind": "numeral",
        "text": None,
        "style": "arabic",
        "value": 121,
    }
    assert raw[170]["kind"] == "blank"

    # Every seeded page, with computed labels -- not filtered by any query.
    labels = {p["page"]["scan_page"]: p for p in dump["pages"]}
    assert set(labels) == {155, 163, 164}
    assert labels[163]["label"] == "129"
    assert labels[163]["confidence"] == "inferred"
    assert labels[155]["confidence"] == "explicit"

    # Every section/anchor occurrence, all roles, unfiltered.
    section_roles = {(s["section_id"], s["role"]) for s in dump["sections"]}
    assert ("p-273", "begin") in section_roles
    assert ("p-273", "end") in section_roles
    assert ("p-273", "anchor_template") in section_roles


def test_dump_works_from_a_page_path_too(client, seeded):
    r = client.get(
        "/locator-index/dump",
        params={"path": _page_path("Page:Principles_of_mechanics.pdf/164")},
    )
    assert r.status_code == 200
    assert r.json()["index_title"] == INDEX


def test_dump_of_unknown_index_is_404(client, seeded):
    r = client.get(
        "/locator-index/dump",
        params={"path": f"/{FAMILY}/{CODE}/Index:Nope.pdf"},
    )
    assert r.status_code == 404


def test_unknown_index_is_404(client, seeded):
    r = client.get(
        "/locator-index/page-numbers",
        params={"path": f"/{FAMILY}/{CODE}/Index:Nope.pdf", "query": "1"},
    )
    assert r.status_code == 404


def test_unsaved_local_edit_is_visible_to_section_lookup(client, engine, seeded):
    # A completion feature should see a <section begin> the moment it's typed,
    # before any commit -- effective_body() is what makes that true.
    with Session(engine) as s:
        page = s.exec(
            select(Page).where(Page.title == "Page:Principles_of_mechanics.pdf/164")
        ).first()
        s.add(
            EditJournal(
                page_pk=page.pk,
                body='<section begin="p-999" />new paragraph<section end="p-999" />',
            )
        )
        s.commit()

    r = client.get(
        "/locator-index/sections",
        params={"path": INDEX_PATH, "query": "p-999"},
    )
    assert r.status_code == 200
    matches = r.json()
    assert len(matches) == 1
    assert matches[0]["page"]["scan_page"] == 164
