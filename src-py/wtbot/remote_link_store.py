from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from wtbot.model import LinkOrigin, Page, Revision, RevisionLink

"""Reading and writing asserted cross-site revision correspondence.

Three rules, all of them enforced here rather than left to callers:

- **Append-only.** There is no update and no retract in this module. A
  correspondence that has broken is superseded by a later row
  (``origin=reconciled``), never edited, so the ladder stays a record of what
  was believed when.
- **Cross-site only.** A link between two revisions of the same site is
  meaningless -- within a site, revision ancestry already says everything -- so
  it is refused rather than stored.
- **One correspondence per other site.** A revision may correspond to one
  revision on each of several sites, but never to two revisions on the same
  site. Candidates may be many-valued; asserted links are not.
- **The pair is unordered.** ``local``/``remote`` name the direction an
  assertion was made from, not a hierarchy, so every read here matches a pair in
  either orientation and ``assert_link`` treats an existing reversed row as the
  same link. A page pair has exactly one ladder and therefore one anchor, no
  matter which way round the caller asks. The database enforces the same thing
  (``uq_revisionlink_pair``), because a convention only the store honours is one
  raw ``session.add`` away from being untrue.
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
    page_link_pk: int | None = None,
) -> RevisionLink:
    """Record that two revisions hold the same content.

    Idempotent on the *unordered* pair: re-asserting an existing link returns
    the row already stored -- including one stored with the two sides the other
    way round -- and keeps its original origin. That the two sides were already
    linked is not new information, and overwriting the origin would quietly
    rewrite history in a table whose whole point is that it does not.
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

    existing = find_link(
        session,
        revision_pk=local_revision_pk,
        other_revision_pk=remote_revision_pk,
    )
    if existing is not None:
        return existing

    _assert_site_cardinality(
        session,
        revision=local,
        other_revision=remote,
        other_site_pk=remote_page.site_pk,
    )
    _assert_site_cardinality(
        session,
        revision=remote,
        other_revision=local,
        other_site_pk=local_page.site_pk,
    )

    link = RevisionLink(
        local_revision_pk=local_revision_pk,
        remote_revision_pk=remote_revision_pk,
        origin=origin,
        page_link_pk=page_link_pk or _pairing_for(session, local_page, remote_page).pk,
    )
    session.add(link)
    session.flush()
    return link


def _assert_site_cardinality(
    session: Session,
    *,
    revision: Revision,
    other_revision: Revision,
    other_site_pk: int,
) -> None:
    """A revision has zero or one counterpart on any particular other site."""
    if revision.pk is None or other_revision.pk is None:  # pragma: no cover
        raise LinkError("cannot link an unpersisted revision")

    for link in links_for_revision(session, revision.pk):
        linked_pk = (
            link.remote_revision_pk
            if link.local_revision_pk == revision.pk
            else link.local_revision_pk
        )
        linked_revision = session.get(Revision, linked_pk)
        if linked_revision is None:  # pragma: no cover - FK holds
            continue
        linked_page = session.get(Page, linked_revision.page_pk)
        if linked_page is None:  # pragma: no cover - FK holds
            continue
        if linked_page.site_pk == other_site_pk and linked_pk != other_revision.pk:
            raise LinkError(
                f"revision {revision.pk} already corresponds to revision "
                f"{linked_pk} on site {other_site_pk}; it cannot also correspond "
                f"to revision {other_revision.pk} on that site"
            )


def _pairing_for(session: Session, local_page: Page, remote_page: Page):
    """The pairing this rung belongs under, created if the caller did not.

    A revision link always implies its page pairing -- asserting two revisions
    correspond asserts their pages do -- so the pairing is materialised rather
    than left for a caller to remember. Imported here to keep the dependency
    one-way at module load: the pairing store reads links, not the reverse.
    """
    from wtbot.page_link_store import pair_pages

    return pair_pages(session, local_page, remote_page)


def find_link(
    session: Session, *, revision_pk: int, other_revision_pk: int
) -> RevisionLink | None:
    """The link between two revisions, whichever way round it was stored."""
    return session.exec(
        select(RevisionLink).where(
            _either_way(
                RevisionLink.local_revision_pk,
                RevisionLink.remote_revision_pk,
                revision_pk,
                other_revision_pk,
            )
        )
    ).first()


def ladder(session: Session, *, page_pk: int, other_page_pk: int) -> list[RevisionLink]:
    """Every link asserted between two pages, oldest first.

    The two arguments are interchangeable: a page pair has one ladder, not one
    per direction of asking.

    Ordered by ``pk``, which is insertion order. Wall-clock assertion time is
    deliberately not stored: it would be a second, less reliable answer to the
    same question -- clocks move, primary keys do not.
    """
    local_revision = aliased(Revision)
    remote_revision = aliased(Revision)
    return list(
        session.exec(
            select(RevisionLink)
            .join(
                local_revision,
                RevisionLink.local_revision_pk == local_revision.pk,
            )
            .join(
                remote_revision,
                RevisionLink.remote_revision_pk == remote_revision.pk,
            )
            .where(
                _either_way(
                    local_revision.page_pk,
                    remote_revision.page_pk,
                    page_pk,
                    other_page_pk,
                )
            )
            .order_by(RevisionLink.pk)
        ).all()
    )


def current_anchor(
    session: Session, *, page_pk: int, other_page_pk: int
) -> RevisionLink | None:
    """The most recent link for a page pair -- the base a push works from.

    None means the pair has never been linked, which is a different state from
    "linked but diverged": the latter has an anchor whose revisions are no
    longer either side's head.
    """
    rungs = ladder(session, page_pk=page_pk, other_page_pk=other_page_pk)
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
        (RevisionLink.local_revision_pk, RevisionLink.remote_revision_pk),
        (RevisionLink.remote_revision_pk, RevisionLink.local_revision_pk),
    ):
        near_revision = aliased(Revision)
        far_revision = aliased(Revision)
        far_page = aliased(Page)
        found = session.exec(
            select(far_page)
            # From the link outwards, not from the page: selecting the page as
            # the lead entity would put it in the FROM clause and then join it
            # a second time under the same alias.
            .select_from(RevisionLink)
            .join(near_revision, near == near_revision.pk)
            .join(far_revision, far == far_revision.pk)
            .join(far_page, far_revision.page_pk == far_page.pk)
            .where(
                near_revision.page_pk == page_pk,
                far_page.site_pk == other_site_pk,
            )
            .order_by(RevisionLink.pk.desc())
        ).first()
        if found is not None:
            return found
    return None


def links_for_revision(session: Session, revision_pk: int) -> list[RevisionLink]:
    """Every link touching a revision, from either side."""
    return list(
        session.exec(
            select(RevisionLink)
            .where(
                (RevisionLink.local_revision_pk == revision_pk)
                | (RevisionLink.remote_revision_pk == revision_pk)
            )
            .order_by(RevisionLink.pk)
        ).all()
    )


def _either_way(left, right, first: int, second: int):
    """Match a two-column pair against two values in either orientation.

    Written once because forgetting it in one query is invisible until the day
    a link happens to have been asserted the other way round, and then a page
    pair silently has two ladders.
    """
    return ((left == first) & (right == second)) | ((left == second) & (right == first))


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
