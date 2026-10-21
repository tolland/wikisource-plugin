import pymupdf
import pytest
from sqlmodel import Session, select
from typer.testing import CliRunner

from wtbot.cli.run_cli import create_app
from wtbot.model import EditJournal, Namespace, Site, Title
from wtbot.transclusion import ApplyTransclusionRequest, apply_transclusion
from wtbot.work_outline import (
    Generation,
    ScanRange,
    WorkMetadata,
    dump_proposal,
    extract_pdf,
    load_proposal,
    propose,
    render,
    validate_proposal,
)


def pdf(tmp_path, toc=None):
    path = tmp_path / "book.pdf"
    with pymupdf.open() as doc:
        for _ in range(20):
            doc.new_page()
        doc.set_toc(toc or [])
        doc.set_page_labels([{"startpage": 0, "style": "r", "firstpagenum": 1}])
        doc.save(path)
    return path


@pytest.fixture
def proposal(tmp_path):
    source = extract_pdf(
        pdf(
            tmp_path,
            [
                [1, "Contents", 2],
                [1, "Introduction to Part I: Foundations", 4],
                [2, "1. A chapter", 6],
                [3, "First section", 8],
                [3, "Second section", 10],
                [1, "Introduction to Part II: More", 12],
                [2, "6. Later chapter", 14],
                [1, "Notes", 18],
                [2, "Chapter 1", 18],
            ],
        )
    )
    return propose(
        source,
        generation=Generation(),
        metadata=WorkMetadata(title="Work", author="Author"),
    )


def test_hierarchy_numbering_and_container(proposal):
    pages = validate_proposal(proposal, root_page="Book:Work")
    assert [p.title for p in pages] == [
        "Book:Work/Frontmatter",
        "Book:Work/Contents",
        "Book:Work/Part_1",
        "Book:Work/Part_1/Chapter_1",
        "Book:Work/Part_1/Chapter_1/Section_1",
        "Book:Work/Part_1/Chapter_1/Section_2",
        "Book:Work/Part_2",
        "Book:Work/Part_2/Chapter_6",
        "Book:Work/Notes",
        "Book:Work/Notes/Chapter_1",
    ]
    assert proposal.pages[-1].scans is None
    assert pages[3].page.scans == ScanRange(first=6, last=7)
    assert pages[4].page.scans == ScanRange(first=8, last=9)
    assert proposal.source.labels[0].label == "i"


def test_depth_absorbs_scans_preserving_source(proposal):
    shallow = propose(
        proposal.source,
        generation=Generation(depth=2),
        metadata=proposal.metadata,
    )
    pages = validate_proposal(shallow, root_page="Book:Work")
    chapter = next(
        p for p in pages if p.title.endswith("Chapter_1") and "Part_1" in p.title
    )
    assert chapter.page.scans == ScanRange(first=6, last=11)
    assert chapter.page.pages == []
    assert shallow.source.pages[1].pages[0].pages[0].title == "First section"


def test_yaml_edits_change_paths_without_reextracting(proposal, tmp_path):
    path = tmp_path / "proposal.yaml"
    path.write_text(dump_proposal(proposal))
    edited = load_proposal(path)
    edited.pages[2].path = "Book 1"
    edited.source.file = "/does/not/exist/book.pdf"
    pages = render(edited, root_page="Book:Work")
    assert pages[3].title == "Book:Work/Book_1/Chapter_1"
    assert 'index="book.pdf" from="6" to="7"' in pages[3].body
    assert "[[Book:Work/Book_1/Chapter_1/Section_1|First section]]" in pages[3].body
    assert " | author = Author" in pages[3].body
    assert " | next = [[Book:Work/Book_1/Chapter_1|" in pages[2].body


@pytest.mark.parametrize("path", ["../bad", "Chapter/1", "", "A|B", "A#B"])
def test_invalid_paths_rejected(proposal, path):
    proposal.pages[0].path = path
    with pytest.raises(ValueError, match="Invalid relative"):
        render(proposal, root_page="Book:Work")


def test_duplicate_and_missing_coverage_rejected(proposal):
    proposal.pages[0].path = proposal.pages[1].path
    with pytest.raises(ValueError, match="Duplicate"):
        render(proposal, root_page="Book:Work")
    proposal.pages.pop(0)
    with pytest.raises(ValueError, match="coverage"):
        render(proposal, root_page="Book:Work")


def test_same_scan_siblings_are_not_merged(tmp_path):
    source = extract_pdf(pdf(tmp_path, [[1, "First", 1], [1, "Second", 1]]))
    result = propose(
        source,
        generation=Generation(),
        metadata=WorkMetadata(title="Work"),
    )
    assert len(result.source.pages) == len(result.pages) == 2
    assert not result.unresolved
    assert result.pages[0].scans == ScanRange(first=1, last=1)
    assert result.pages[1].scans == ScanRange(first=1, last=20)
    output = render(result, root_page="Book:Work")
    assert 'from="1" to="1"' in output[0].body
    assert 'from="1" to="20"' in output[1].body


def test_absent_outline_uses_all_scans(tmp_path):
    source = extract_pdf(pdf(tmp_path))
    result = propose(
        source,
        generation=Generation(),
        metadata=WorkMetadata(title="Work"),
    )
    assert validate_proposal(result)[0].page.scans == ScanRange(first=1, last=20)


def test_invalid_destination_rejected(tmp_path):
    with pytest.raises(ValueError, match="invalid destination"):
        extract_pdf(pdf(tmp_path, [[1, "Missing", -1]]))


def seed_site(session):
    site = Site(label="local", family="local", code="en")
    session.add(site)
    session.flush()
    session.add(
        Namespace(
            site_pk=site.pk,
            key=3000,
            canonical_name="Book",
            local_name="Book",
            subpages=True,
            case="first-letter",
        )
    )
    session.commit()
    return site


def test_apply_creates_journals_not_remote_pages_and_force_preserves_history(
    session, proposal
):
    seed_site(session)
    request = ApplyTransclusionRequest(
        label="local", proposal=proposal, root_page="Book:Work"
    )
    preview = apply_transclusion(session, request.model_copy(update={"dry_run": True}))
    assert len(preview.pages) == 10
    assert session.exec(select(EditJournal)).all() == []
    assert session.exec(select(Title)).all() == []
    result = apply_transclusion(session, request)
    assert len(result.pages) == 10
    titles = session.exec(select(Title)).all()
    assert all(t.dirty and t.namespace_key == 3000 for t in titles)
    assert "Book:Work" not in [t.title for t in titles]
    assert len(session.exec(select(EditJournal)).all()) == 10
    with pytest.raises(ValueError, match="already known locally"):
        apply_transclusion(session, request)
    assert len(session.exec(select(EditJournal)).all()) == 10
    apply_transclusion(session, request.model_copy(update={"force": True}))
    assert len(session.exec(select(EditJournal)).all()) == 20


def test_preflight_collision_writes_nothing(session, proposal):
    site = seed_site(session)
    session.add(
        Title(
            site_pk=site.pk,
            title="Book:Work/Part_2/Chapter_6",
            expected_content_model="wikitext",
        )
    )
    session.commit()
    with pytest.raises(ValueError, match="already known locally"):
        apply_transclusion(
            session,
            ApplyTransclusionRequest(
                label="local", proposal=proposal, root_page="Book:Work"
            ),
        )
    assert len(session.exec(select(Title)).all()) == 1
    assert session.exec(select(EditJournal)).all() == []


def test_apply_api_uses_normal_pending_commit_workflow(engine, client, proposal):
    with Session(engine) as session:
        seed_site(session)
    request = ApplyTransclusionRequest(
        label="local", proposal=proposal, root_page="Book:Work"
    )
    response = client.post(
        "/dev/transclusion", json=request.model_dump(mode="json", by_alias=True)
    )
    assert response.status_code == 200, response.text
    pending = client.get("/commits/pending").json()
    assert len(pending) == 10
    assert all(p["title"].startswith("Book:Work/") for p in pending)
    assert (
        client.post(
            "/dev/transclusion", json=request.model_dump(mode="json", by_alias=True)
        ).status_code
        == 400
    )


def test_cli_proposal_and_offline_preview(tmp_path):
    source = pdf(tmp_path, [[1, "Part I", 1], [2, "1. Heading", 3]])
    path = tmp_path / "structure.yaml"
    runner = CliRunner()
    app = create_app()
    result = runner.invoke(
        app,
        [
            "dev",
            "propose-transclusion",
            "--pdf-filepath",
            str(source),
            "--level-type",
            "1=Book",
            "--output",
            str(path),
        ],
    )
    assert result.exit_code == 0, result.output
    proposal = load_proposal(path)
    # Level mappings override source types while preserving their numbers.
    assert proposal.pages[0].path == "Book_1"
    result = runner.invoke(
        app,
        [
            "dev",
            "apply-transclusion",
            "--structure",
            str(path),
            "--root-page",
            "Book:Work",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Book:Work/Book_1/Chapter_1" in result.output
    assert "no local or remote edits" in result.output
    result = runner.invoke(
        app,
        [
            "dev",
            "propose-transclusion",
            "--pdf-filepath",
            str(source),
            "--output",
            str(path),
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_batch_failure_rolls_back_all_titles_and_journals(
    session, proposal, monkeypatch
):
    from wtbot.vfs.store import PageStore

    seed_site(session)
    append = PageStore.append_edit
    count = 0

    def fail_second(self, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("simulated save failure")
        return append(self, *args, **kwargs)

    monkeypatch.setattr(PageStore, "append_edit", fail_second)
    with pytest.raises(RuntimeError, match="simulated"):
        apply_transclusion(
            session,
            ApplyTransclusionRequest(
                label="local", proposal=proposal, root_page="Book:Work"
            ),
        )
    assert session.exec(select(Title)).all() == []
    assert session.exec(select(EditJournal)).all() == []


def test_title_cleanup_and_escaped_headers(proposal):
    from wtbot.work_outline import clean_title

    assert clean_title("Preface\x00\x00\n  text") == "Preface text"
    proposal.pages[0].title = "Title | {{bad}} [[link]]"
    body = render(proposal, root_page="Book:Work")[0].body
    assert "Title &#124; &#123;&#123;bad&#125;&#125; &#91;&#91;link&#93;&#93;" in body


def test_backwards_bookmarks_rejected(tmp_path):
    with pytest.raises(ValueError, match="backwards"):
        extract_pdf(pdf(tmp_path, [[1, "Later", 5], [1, "Earlier", 2]]))


def test_proposal_is_destination_independent(proposal):
    document = proposal.model_dump()
    assert "root_page" not in document
    assert "index_page" not in document
    first = render(
        proposal, root_page="Book:First Work", index_page="Index:First Scan.pdf"
    )
    second = render(
        proposal, root_page="Book:Second Work", index_page="Index:Second Scan.pdf"
    )
    assert first[3].title == "Book:First_Work/Part_1/Chapter_1"
    assert second[3].title == "Book:Second_Work/Part_1/Chapter_1"
    assert 'index="First_Scan.pdf"' in first[3].body
    assert 'index="Second_Scan.pdf"' in second[3].body
    assert (
        "[[Book:Second_Work/Part_1/Chapter_1/Section_1|First section]]"
        in second[3].body
    )
    assert proposal.model_dump() == document


def test_apply_infers_index_from_source_filename(proposal):
    proposal.source.file = "/unavailable/original/My Book.pdf"
    proposal.metadata.title = ""
    page = render(proposal, root_page="Book:My_Work")[0]
    assert 'index="My_Book.pdf"' in page.body
    assert " | title = My Work" in page.body


def test_spaces_and_underscores_collide(proposal):
    proposal.pages[0].path = "A page"
    proposal.pages[1].path = "A_page"
    with pytest.raises(ValueError, match="Duplicate"):
        render(proposal, root_page="Book:Work")


def test_force_keeps_existing_address_but_returns_canonical_path(session, proposal):
    site = seed_site(session)
    session.add(
        Title(
            site_pk=site.pk,
            title="Book:Work/Part 1/Chapter 1",
            expected_content_model="wikitext",
        )
    )
    session.commit()
    request = ApplyTransclusionRequest(
        label="local", proposal=proposal, root_page="Book:Work", force=True
    )
    result = apply_transclusion(session, request)
    destination = next(
        p for p in result.pages if p.title == "Book:Work/Part 1/Chapter 1"
    )
    assert destination.path.endswith("Book:Work/Part_1/Chapter_1")
    assert len(session.exec(select(Title)).all()) == 10


def test_source_filename_is_portable_in_extracted_yaml(tmp_path):
    source = extract_pdf(pdf(tmp_path))
    assert source.file == "book.pdf"
    result = propose(source, generation=Generation(), metadata=WorkMetadata())
    document = dump_proposal(result)
    assert "file: book.pdf" in document
    assert str(tmp_path) not in document
    assert source.fingerprint.startswith("sha256:")


@pytest.mark.parametrize("filename", ["/mnt/books/book.pdf", r"C:\Books\book.pdf"])
def test_loading_legacy_source_paths_removes_directories(proposal, filename):
    document = proposal.model_dump()
    document["source"]["file"] = filename
    loaded = type(proposal).model_validate(document)
    assert loaded.source.file == "book.pdf"
    assert filename not in dump_proposal(loaded)
    assert 'index="book.pdf"' in render(loaded, root_page="Book:Work")[0].body


@pytest.mark.parametrize("depth", [1, 2, 99])
def test_successive_sections_on_same_scan_generate_partial_first_scan(tmp_path, depth):
    source = extract_pdf(
        pdf(
            tmp_path,
            [
                [1, "Part I", 1],
                [2, "4. Earlier section", 4],
                [2, "5. Following section", 4],
                [2, "6. Next section", 6],
            ],
        )
    )
    proposal = propose(
        source, generation=Generation(depth=depth), metadata=WorkMetadata()
    )
    output = render(proposal, root_page="Book:Work")
    assert not proposal.unresolved
    if depth == 1:
        assert len(output) == 1
        assert proposal.pages[0].scans == ScanRange(first=1, last=20)
    else:
        children = proposal.pages[0].pages
        assert children[0].scans == ScanRange(first=4, last=4)
        assert children[1].scans == ScanRange(first=4, last=5)
        assert children[2].scans == ScanRange(first=6, last=20)
        assert 'from="4" to="4"' in output[1].body
        assert 'from="4" to="5"' in output[2].body


def test_three_successive_headings_can_share_scan(tmp_path):
    source = extract_pdf(
        pdf(tmp_path, [[1, "First", 1], [1, "Second", 1], [1, "Third", 1]])
    )
    proposal = propose(source, generation=Generation(), metadata=WorkMetadata())
    assert [p.scans for p in proposal.pages] == [
        ScanRange(first=1, last=1),
        ScanRange(first=1, last=1),
        ScanRange(first=1, last=20),
    ]
    assert len(render(proposal, root_page="Book:Work")) == 3


def test_general_range_overlap_still_rejected(proposal):
    proposal.pages[0].scans = ScanRange(first=1, last=3)
    with pytest.raises(ValueError, match="overlap"):
        render(proposal, root_page="Book:Work")


def test_exclusions_cannot_overlap_content(proposal):
    from wtbot.work_outline import Exclusion

    proposal.exclusions = [
        Exclusion(scans=ScanRange(first=1, last=1), reason="Invalid duplicate")
    ]
    with pytest.raises(ValueError, match="overlap"):
        render(proposal, root_page="Book:Work")


def test_series_page_is_named_frontmatter_not_a_numbered_part(tmp_path):
    source = extract_pdf(
        pdf(
            tmp_path,
            [
                [1, "Cover", 1],
                [1, "Half Title", 2],
                [1, "Series Page", 5],
                [1, "Title Page", 6],
                [1, "Copyright Page", 7],
                [1, "Table of Contents", 8],
                [1, "FOREWORD TO THE ROUTLEDGE CLASSICS EDITION", 10],
                [1, "Basic Principles", 12],
            ],
        )
    )
    proposal = propose(source, generation=Generation(), metadata=WorkMetadata())
    assert [page.path for page in proposal.pages] == [
        "Cover",
        "Half_Title",
        "Series_Page",
        "Title_Page",
        "Copyright_Page",
        "Table_of_Contents",
        "FOREWORD_TO_THE_ROUTLEDGE_CLASSICS_EDITION",
        "Part_1",
    ]
    assert proposal.pages[2].scans == ScanRange(first=5, last=5)
