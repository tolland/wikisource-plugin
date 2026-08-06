"""The fetch path against a real wiki, over docker.

Replaces a set of vcrpy cassette tests. Cassettes recorded one library version
against one wiki and then quietly aged: pywikibot 11.6 fetches ``meta=userinfo``
while constructing a Site, which no recording from before it contained, so
replay failed on a request our code never made and the failures said nothing
about wtbot. Worse, the recordings could only be refreshed from a machine with
access to both wikis, which made "re-record" an answer nobody could act on.

The harness is a wiki, so it answers the questions cassettes were standing in
for -- and answers today's version of them. The cost is that these need docker,
hence ``@pytest.mark.slow`` and ``--runslow``.

Every assertion here goes through ``PywikibotClient``: the production fetch
path is pywikibot, so a test that reaches the wiki another way proves something
about ``requests`` instead of about wtbot.
"""

import pytest
from conftest import CANADIAN_PATENT_INDEX, CANADIAN_PATENT_SCAN, drain
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from wiki_harness import PwbHarness, WikiApi

from wtbot.main import create_app
from wtbot.model import FileBlob, IndexMeta, Page
from wtbot.wiki.wiki_types import PageNotFound

PAGE_1 = "Page:Canadian patent 29537.djvu/1"


@pytest.fixture
def wiki_client(seeded_upstream: WikiApi, upstream_pwb: PwbHarness):
    """The production client, pointed at the seeded harness wiki."""
    return upstream_pwb.client


@pytest.mark.slow
def test_get_index_page(wiki_client) -> None:
    """An Index: reports the ProofreadPage content model and its pagination.

    ``page_count`` comes from ``IndexPage.num_pages`` rather than from parsing
    <pagelist> or from file imageinfo, which is absent for many file types.
    """
    remote = wiki_client.get_page(CANADIAN_PATENT_INDEX)

    assert remote.content_model == "proofread-index"
    assert remote.namespace_canonical == "Index"
    assert remote.revid is not None
    assert remote.sha1 is not None
    assert remote.page_count is not None and remote.page_count > 0


@pytest.mark.slow
def test_get_page_1(wiki_client) -> None:
    remote = wiki_client.get_page(PAGE_1)

    assert remote.content_model == "proofread-page"
    assert remote.namespace_canonical == "Page"
    assert remote.revid is not None
    assert remote.text


@pytest.mark.slow
def test_get_file_info(wiki_client) -> None:
    info = wiki_client.get_file_info(CANADIAN_PATENT_SCAN)

    assert info.size > 0
    assert len(info.file_sha1) == 40
    assert info.mime


@pytest.mark.slow
def test_a_missing_page_raises_page_not_found(wiki_client) -> None:
    """The redlink case, which a partially transcribed index is full of."""
    with pytest.raises(PageNotFound):
        wiki_client.get_page("Page:Canadian patent 29537.djvu/9999")


@pytest.mark.slow
def test_list_index_subpages(wiki_client) -> None:
    titles = wiki_client.list_index_subpage_titles(CANADIAN_PATENT_INDEX)
    assert all(t.startswith(f"{CANADIAN_PATENT_INDEX}/") for t in titles)


@pytest.mark.slow
def test_fan_out_an_index_end_to_end(engine, tmp_path, wiki_client) -> None:
    """Enqueue, drain, and check what landed in SQLite.

    The whole worker, against a real wiki: index fetched, File: blob
    downloaded, Page: children fanned out and fetched.
    """
    app = create_app(
        engine=engine,
        client_factory=lambda site: wiki_client,
        blob_root=tmp_path / "blobs",
    )
    with TestClient(app) as http:
        enqueued = http.post(
            "/fetch/",
            json={
                "title": CANADIAN_PATENT_INDEX,
                "family": "mywikisource",
                "code": "en",
                "depth": 1,
            },
        )
        assert enqueued.status_code == 202
        report = drain(http)

    assert report["complete"], report

    with Session(engine) as session:
        pages = session.exec(select(Page)).all()
        index_row = next(p for p in pages if p.title == CANADIAN_PATENT_INDEX)
        meta = session.exec(
            select(IndexMeta).where(IndexMeta.page_pk == index_row.pk)
        ).one()
        assert meta.page_count is not None and meta.page_count > 0
        # The children the fan-out discovered mid-drain, not just the index.
        assert len(pages) > 1
        assert any(p.title.startswith(f"{CANADIAN_PATENT_INDEX}") for p in pages)

        blob = session.exec(
            select(FileBlob).where(FileBlob.page_pk == index_row.pk)
        ).first()
        assert blob is not None
        assert blob.size and blob.local_path
