import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from wtbot.api.viewer import get_index_page, list_index_pages
from wtbot.sqlmodel import NsRole, Page, Site


def _add_page(
    engine,
    title: str,
    role: NsRole,
    text: str | None,
    content_model: str | None = None,
) -> Page:
    session = Session(engine)
    site = session.exec(
        select(Site).where(Site.family == "mywikisource", Site.code == "en")
    ).first()
    if site is None:
        site = Site(family="mywikisource", code="en", articlepath="/wiki/$1")
        session.add(site)
        session.commit()
        session.refresh(site)

    page = Page(
        site_pk=site.pk,
        title=title,
        namespace_role=role,
        content_model=content_model,
        text=text,
        page_count=12 if content_model == "proofread-index" else None,
        revid=123,
    )
    session.add(page)
    session.commit()
    session.refresh(page)
    session.expunge(page)
    session.close()
    return page


def test_viewer_lists_only_index_pages(engine):
    index_page = _add_page(
        engine,
        "Index:Example.djvu",
        NsRole.index,
        "index body",
        content_model="proofread-index",
    )
    _add_page(
        engine,
        "Index:Example.djvu/styles.css",
        NsRole.index,
        ".pagetext {}",
        content_model="sanitized-css",
    )
    _add_page(
        engine,
        "Page:Example.djvu/1",
        NsRole.page,
        "page body",
        content_model="proofread-page",
    )

    with Session(engine) as session:
        pages = list_index_pages(session)

    assert [page.model_dump() for page in pages] == [
        {
            "pk": index_page.pk,
            "title": "Index:Example.djvu",
            "page_count": 12,
            "revid": 123,
            "content_model": "proofread-index",
            "body_length": 10,
        }
    ]


def test_viewer_returns_index_page_body(engine):
    index_page = _add_page(
        engine,
        "Index:Example.djvu",
        NsRole.index,
        "{{Header}}",
        content_model="proofread-index",
    )

    with Session(engine) as session:
        page = get_index_page(index_page.pk, session)

    assert page.body == "{{Header}}"  # viewer response field (not DB column)


def test_viewer_404s_for_non_index_page(engine):
    page = _add_page(
        engine,
        "Page:Example.djvu/1",
        NsRole.page,
        "page body",
        content_model="proofread-page",
    )

    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc_info:
            get_index_page(page.pk, session)

    assert exc_info.value.status_code == 404


def test_viewer_404s_for_index_namespace_asset(engine):
    page = _add_page(
        engine,
        "Index:Example.djvu/styles.css",
        NsRole.index,
        ".pagetext {}",
        content_model="sanitized-css",
    )

    with Session(engine) as session:
        with pytest.raises(HTTPException) as exc_info:
            get_index_page(page.pk, session)

    assert exc_info.value.status_code == 404
