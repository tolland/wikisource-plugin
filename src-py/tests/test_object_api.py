from fastapi import HTTPException
from sqlmodel import Session, select

from wtbot.api.pages import get_page, list_pages
from wtbot.main import create_app
from wtbot.sqlmodel import FileBlob, NsRole, Page, Site


def test_app_exposes_object_routes(engine):
    app = create_app(engine=engine)
    paths = set(app.openapi()["paths"])

    assert "/pages/" in paths
    assert "/file-blobs/" in paths
    assert "/edit-journal/" in paths
    assert "/namespaces/" in paths
    assert "/commits/" in paths


def test_pages_route_returns_raw_text_and_content_model(session: Session):
    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)

    page = Page(
        site_pk=site.pk,
        title="Template:TOC templates/style.css",
        namespace_role=NsRole.template,
        content_model="sanitized-css",
        text=".wst-toc-table { border-collapse: collapse; }",
        revid=268,
    )
    session.add(page)
    session.commit()
    session.refresh(page)

    [listed] = list_pages(
        session,
        site_pk=site.pk,
        content_model="sanitized-css",
        title=None,
        offset=0,
        limit=100,
    )
    assert listed.pk == page.pk
    assert listed.content_model == "sanitized-css"
    assert listed.text == page.text

    fetched = get_page(page.pk, session)
    assert fetched.title == page.title
    assert fetched.content_model == "sanitized-css"

    [exact] = list_pages(
        session,
        site_pk=site.pk,
        title=page.title,
        offset=0,
        limit=100,
    )
    assert exact.pk == page.pk


def test_pages_route_404s_for_missing_page(session: Session):
    try:
        get_page(9999, session)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("expected HTTPException")


def test_file_blob_model_available_for_object_routes(session: Session):
    site = Site(family="mywikisource", code="en")
    session.add(site)
    session.commit()
    session.refresh(site)
    page = Page(site_pk=site.pk, title="File:Example.pdf", namespace_role=NsRole.file)
    session.add(page)
    session.commit()
    session.refresh(page)

    blob = FileBlob(page_pk=page.pk, mime="application/pdf", size=123)
    session.add(blob)
    session.commit()

    rows = session.exec(select(FileBlob).where(FileBlob.page_pk == page.pk)).all()
    assert len(rows) == 1
