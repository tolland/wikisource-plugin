from sqlalchemy.dialects.sqlite import insert

from wtbot.sqlmodel import Site, Page


def upsert_site(session, *, family: str, code: str, articlepath: str) -> Site:
    stmt = insert(Site).values(
        family=family,
        code=code,
        articlepath=articlepath,
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["family", "code"],
        set_={
            "articlepath": stmt.excluded.articlepath,
        },
    ).returning(Site)

    return session.exec(stmt).one()


def upsert_page(
    session,
    *,
    site_pk: int,
    page_id: int,
    title: str,
    text: str,
    content_model: str,
    latest_revision_id: int,
    oldest_revision_id: int,

) -> Page:
    stmt = insert(Page).values(
        site_pk=site_pk,
        page_id=page_id,
        title=title,
        text=text,
        content_model=content_model,
        latest_revision_id=latest_revision_id,
        oldest_revision_id=oldest_revision_id,
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["site_pk", "page_id"],
        set_={
            "title": stmt.excluded.title,
            "text": stmt.excluded.text,
            "oldest_revision_id": stmt.excluded.oldest_revision_id,
            "latest_revision_id": stmt.excluded.latest_revision_id,
            "content_model": stmt.excluded.content_model,
        },
    ).returning(Page)

    return session.exec(stmt).one()
