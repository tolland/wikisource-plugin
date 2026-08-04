from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from wtbot.model import LinkOrigin, Page, RemoteLink, Revision

"""Reading and writing asserted cross-site revision correspondence.

Three rules, all of them enforced here rather than left to callers:

- **Append-only.** There is no update and no retract in this module. A
  correspondence that has broken is superseded by a later row
  (``origin=reconciled``), never edited, so the ladder stays a record of what
  was believed when.
- **Cross-site only.** A link between two revisions of the same site is
  meaningless -- within a site, revision ancestry already says everything -- so
  it is refused rather than stored.
- **Page correspondence is derived.** ``corresponding_page`` walks
  ``link -> revision -> page``; no page-pair table exists, because a target
  redlink must have no link rather than a link to nothing.
"""


class LinkError(ValueError):
    """A correspondence that cannot be asserted as stated."""


def assert_link(
    session: Session,
    *,
    local_revision_pk: int,
    remote_revision_pk: int,
    origin: LinkOrigin,
) -> RemoteLink:
    """Record that two revisions hold the same content.

    Idempotent on the pair: re-asserting an existing link returns the row
    already stored, keeping its original origin. That the two sides were
    already linked is not new information, and overwriting the origin would
    quietly rewrite history in a table whose whole point is that it does not.
    """
    local, remote = _load_pair(session, local_revision_pk, remote_revision_pk)

    local_page = session.get(Page, local.page_pk)
    remote_page = session.get(Page, remote.page_pk)
    if local_page is None or remote_page is None:  # pragma: no cover - FK holds
        raise LinkError("a linked revision has no page")
    if local_page.site_pk == remote_page.site_pk:
        raise LinkError(
            "a RemoteLink asserts correspondence across sites; "
            f"both revisions are on site {local_page.site_pk}"
        )

    existing = session.exec(
        select(RemoteLink).where(
            RemoteLink.local_revision_pk == local_revision_pk,
            RemoteLink.remote_revision_pk == remote_revision_pk,
        )
    ).first()
    if existing is not None:
        return existing

    link = RemoteLink(
        local_revision_pk=local_revision_pk,
        remote_revision_pk=remote_revision_pk,
        origin=origin,
    )
    session.add(link)
    session.flush()
    return link


def ladder(
    session: Session, *, local_page_pk: int, remote_page_pk: int
) -> list[RemoteLink]:
    """Every link asserted between two pages, oldest first.

    Ordered by ``pk``, which is insertion order. Wall-clock assertion time is
    deliberately not stored: it would be a second, less reliable answer to the
    same question -- clocks move, primary keys do not.
    """
    local_revision = aliased(Revision)
    remote_revision = aliased(Revision)
    return list(
        session.exec(
            select(RemoteLink)
            .join(
                local_revision,
                RemoteLink.local_revision_pk == local_revision.pk,
            )
            .join(
                remote_revision,
                RemoteLink.remote_revision_pk == remote_revision.pk,
            )
            .where(
                local_revision.page_pk == local_page_pk,
                remote_revision.page_pk == remote_page_pk,
            )
            .order_by(RemoteLink.pk)
        ).all()
    )


def current_anchor(
    session: Session, *, local_page_pk: int, remote_page_pk: int
) -> RemoteLink | None:
    """The most recent link for a page pair -- the base a push works from.

    None means the pair has never been linked, which is a different state from
    "linked but diverged": the latter has an anchor whose revisions are no
    longer either side's head.
    """
    rungs = ladder(session, local_page_pk=local_page_pk, remote_page_pk=remote_page_pk)
    return rungs[-1] if rungs else None


def corresponding_page(
    session: Session, *, page_pk: int, other_site_pk: int
) -> Page | None:
    """The page on ``other_site_pk`` that any link says corresponds to ``page_pk``.

    Derived from the links rather than stored, and it works in both directions:
    a page appears as the local side of some links and the remote side of
    others depending on which way the correspondence was asserted.

    Returns None when nothing links the two, including the redlink case. That
    absence is the honest answer -- whether a page *should* exist on the other
    side is a pairing question, answered by title matching, not by this table.
    """
    for near, far in (
        (RemoteLink.local_revision_pk, RemoteLink.remote_revision_pk),
        (RemoteLink.remote_revision_pk, RemoteLink.local_revision_pk),
    ):
        near_revision = aliased(Revision)
        far_revision = aliased(Revision)
        far_page = aliased(Page)
        found = session.exec(
            select(far_page)
            # From the link outwards, not from the page: selecting the page as
            # the lead entity would put it in the FROM clause and then join it
            # a second time under the same alias.
            .select_from(RemoteLink)
            .join(near_revision, near == near_revision.pk)
            .join(far_revision, far == far_revision.pk)
            .join(far_page, far_revision.page_pk == far_page.pk)
            .where(
                near_revision.page_pk == page_pk,
                far_page.site_pk == other_site_pk,
            )
            .order_by(RemoteLink.pk.desc())
        ).first()
        if found is not None:
            return found
    return None


def links_for_revision(session: Session, revision_pk: int) -> list[RemoteLink]:
    """Every link touching a revision, from either side."""
    return list(
        session.exec(
            select(RemoteLink)
            .where(
                (RemoteLink.local_revision_pk == revision_pk)
                | (RemoteLink.remote_revision_pk == revision_pk)
            )
            .order_by(RemoteLink.pk)
        ).all()
    )


def _load_pair(
    session: Session, local_revision_pk: int, remote_revision_pk: int
) -> tuple[Revision, Revision]:
    if local_revision_pk == remote_revision_pk:
        raise LinkError("a revision cannot be linked to itself")

    local = session.get(Revision, local_revision_pk)
    remote = session.get(Revision, remote_revision_pk)
    if local is None:
        raise LinkError(f"no revision with pk {local_revision_pk}")
    if remote is None:
        raise LinkError(f"no revision with pk {remote_revision_pk}")
    return local, remote
