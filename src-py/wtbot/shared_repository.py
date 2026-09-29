from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from wtbot.model import FetchState, IndexMeta, Site, Title
from wtbot.title_store import ensure_title

"""The shared file repository -- Commons -- as an ordinary registered site.

A Wikimedia wiki serves most of its ``File:`` pages from Commons: the local
wiki reports such a title ``missing`` but ``known``, with
``imagerepository: shared``, and has no page for it. The page, with real ids,
exists only on Commons, so that is where we fetch it -- through a registered
Site like any other, authenticated once a credential is attached.

The site is created at startup if absent (after the migrations), without a
credential: attaching one is the operator's step, as for any site. Until then
a fetch from it is refused like a fetch from any credential-less site.
"""

SHARED_REPOSITORY_FAMILY = "commons"
SHARED_REPOSITORY_CODE = "commons"
SHARED_REPOSITORY_LABEL = "commons"

#: The default description-page model on Commons, and our guess for a File:
#: title before its page is fetched.
FILE_CONTENT_MODEL = "wikitext"


def shared_repository_site(session: Session) -> Site | None:
    return session.exec(
        select(Site).where(
            Site.family == SHARED_REPOSITORY_FAMILY,
            Site.code == SHARED_REPOSITORY_CODE,
        )
    ).first()


def is_shared_repository(site: Site) -> bool:
    return (site.family, site.code) == (
        SHARED_REPOSITORY_FAMILY,
        SHARED_REPOSITORY_CODE,
    )


def ensure_shared_repository_site(engine: Engine) -> None:
    """Register Commons if it is not registered. The label is only taken if
    free: an operator may already call another site ``commons``."""
    with Session(engine) as session:
        if shared_repository_site(session) is not None:
            return
        label_taken = (
            session.exec(
                select(Site).where(Site.label == SHARED_REPOSITORY_LABEL)
            ).first()
            is not None
        )
        session.add(
            Site(
                family=SHARED_REPOSITORY_FAMILY,
                code=SHARED_REPOSITORY_CODE,
                label=None if label_taken else SHARED_REPOSITORY_LABEL,
            )
        )
        session.commit()


def index_file_title_name(index_title: str) -> str:
    """``Index:Foo.djvu`` -> ``File:Foo.djvu``: ProofreadPage's own rule."""
    _, _, basename = index_title.partition(":")
    return f"File:{basename}"


def local_file_title_pk(session: Session, index: Title) -> int:
    """The ``File:`` title on the index's own site -- where MediaWiki looks
    first, and so the reference until a fetch says the file is shared."""
    title = ensure_title(
        session,
        site_pk=index.site_pk,
        title=index_file_title_name(index.title),
        expected_content_model=FILE_CONTENT_MODEL,
    )
    assert title.pk is not None  # flushed by ensure_title
    return title.pk


def move_to_shared_repository(
    session: Session, local_file: Title, repository: Site
) -> Title:
    """The file behind [local_file] is served from [repository]: record the
    local title as fetched-and-absent, and repoint every index that named it
    at the repository's title, which is returned."""
    assert repository.pk is not None and local_file.pk is not None
    shared = ensure_title(
        session,
        site_pk=repository.pk,
        title=local_file.title,
        expected_content_model=FILE_CONTENT_MODEL,
    )
    assert shared.pk is not None
    local_file.fetch_status = FetchState.done
    session.add(local_file)
    for meta in session.exec(
        select(IndexMeta).where(IndexMeta.file_title_pk == local_file.pk)
    ).all():
        meta.file_title_pk = shared.pk
        session.add(meta)
    return shared


def move_to_local(session: Session, local_file: Title) -> None:
    """The index's own site holds [local_file] (a fetch just found it there):
    repoint the site's indexes that named a same-titled file elsewhere. A
    local upload shadows the shared one, as MediaWiki resolves it."""
    assert local_file.pk is not None
    elsewhere = select(Title.pk).where(
        Title.title == local_file.title, Title.site_pk != local_file.site_pk
    )
    for meta in session.exec(
        select(IndexMeta).where(
            IndexMeta.site_pk == local_file.site_pk,
            col(IndexMeta.file_title_pk).in_(elsewhere),
        )
    ).all():
        meta.file_title_pk = local_file.pk
        session.add(meta)
