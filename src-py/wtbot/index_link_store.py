from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from wtbot.model import IndexLink, LinkOrigin, NsRole, Page, PageLink, Site
from wtbot.page_link_store import find_pair, pair_pages, unpair
from wtbot.remote_link_store import LinkError

"""Putting a work under cross-site tracking, and finding the ones that are.

Three operations, and the whole of the work-level model:

- **link** two ``Index:`` pages. The pairing is an ordinary ``PageLink`` (see
  ``wtbot.model.index_link`` for why); this adds the ``IndexLink`` that says
  the pairing is a *work*, and adopts the page pairs that already belong to it.
- **adopt** the children. Pairing a work's pages (``pair-index``) and declaring
  the work tracked are separate acts that happen in either order, so linking a
  work claims the pairs that are already there rather than requiring them to be
  made again afterwards.
- **unlink**. Two widths, as with pairings: stop tracking the work, or that
  plus discard the pairings under it.

Membership is decided by the *local* index only. The other side's index title
is exactly the thing that may differ -- that is what ``--to`` is for -- so
asking "which pairs belong to this work" through both sides would answer
"none" for precisely the works that need the pairing most.
"""


def link_indexes(
    session: Session,
    local_index: Page,
    remote_index: Page,
    *,
    origin: LinkOrigin = LinkOrigin.manual,
) -> IndexLink:
    """Declare two ``Index:`` pages to be the same work.

    Idempotent: a work already linked is returned as it stands, including when
    the two sides are named the other way round. Re-declaring is not new
    information, and a second row would give one work two identities.
    """
    for page in (local_index, remote_index):
        if page.namespace_role is not NsRole.index:
            raise LinkError(
                f"{page.title} is not an Index: page (role {page.namespace_role}). "
                "A work is tracked by its index; pair other namespaces with "
                "`link add`."
            )

    pairing = pair_pages(session, local_index, remote_index, origin=origin)

    existing = session.exec(
        select(IndexLink).where(IndexLink.page_link_pk == pairing.pk)
    ).first()
    if existing is not None:
        # Adopt anyway: pages paired since the work was linked belong to it,
        # and the caller has just said so by asking again.
        adopt_children(session, existing)
        return existing

    work = IndexLink(page_link_pk=pairing.pk)
    session.add(work)
    session.flush()
    adopt_children(session, work)
    return work


def adopt_children(session: Session, work: IndexLink) -> int:
    """Point this work's page pairs at it. Returns how many were newly claimed.

    Claims a pair when its local side is a ``Page:`` of the local index, and
    only when it is unclaimed or already ours -- a pair belonging to another
    work is left alone rather than stolen. Two works sharing a page pair means
    one of the two indexes is wrong, and silently reassigning it would hide
    that at exactly the moment it could still be fixed.
    """
    from wtbot.matching import index_children

    pairing = session.get(PageLink, work.page_link_pk)
    local_index = session.get(Page, pairing.local_page_pk)
    site = session.get(Site, local_index.site_pk)

    child_pks = {
        page.pk for _, page in index_children(session, site, local_index.title)
    }
    if not child_pks:
        return 0

    claimed = 0
    candidates = session.exec(
        select(PageLink).where(
            PageLink.local_page_pk.in_(child_pks)
            | PageLink.remote_page_pk.in_(child_pks)
        )
    ).all()
    for pair in candidates:
        if pair.index_link_pk == work.pk:
            continue
        if pair.index_link_pk is not None:
            continue
        pair.index_link_pk = work.pk
        session.add(pair)
        claimed += 1
    session.flush()
    return claimed


def children_of(session: Session, work: IndexLink) -> list[PageLink]:
    """The page pairs claimed by a work, in no particular order.

    Ordering is the caller's business: the viewer wants reading order, which
    means page number, which lives on ``ProofreadPageMeta`` -- a join this module has no
    reason to force on every reader.
    """
    return list(
        session.exec(select(PageLink).where(PageLink.index_link_pk == work.pk)).all()
    )


def find_index_link(
    session: Session, local_page_pk: int, remote_page_pk: int
) -> IndexLink | None:
    """The work linking two Index pages, whichever way round it was asserted."""
    pairing = find_pair(session, local_page_pk, remote_page_pk)
    if pairing is None:
        return None
    return session.exec(
        select(IndexLink).where(IndexLink.page_link_pk == pairing.pk)
    ).first()


def work_for_index_page(session: Session, page_pk: int) -> IndexLink | None:
    """The work an Index page belongs to, from either side of the pairing."""
    return session.exec(
        select(IndexLink)
        .join(PageLink, PageLink.pk == IndexLink.page_link_pk)
        .where(
            (PageLink.local_page_pk == page_pk) | (PageLink.remote_page_pk == page_pk)
        )
    ).first()


def works_for_sites(
    session: Session,
    local_site: Site | None = None,
    remote_site: Site | None = None,
) -> list[IndexLink]:
    """Tracked works, optionally narrowed to a pair of sites.

    The site filter matches in **either orientation**, for the same reason
    every other read here does: which side was called local records how the
    assertion was made, not a hierarchy, and a viewer that swapped its two
    columns should see the same works.
    """
    local_page = aliased(Page)
    remote_page = aliased(Page)
    statement = (
        select(IndexLink)
        .join(PageLink, PageLink.pk == IndexLink.page_link_pk)
        .join(local_page, local_page.pk == PageLink.local_page_pk)
        .join(remote_page, remote_page.pk == PageLink.remote_page_pk)
        .order_by(IndexLink.pk)
    )
    if local_site is not None and remote_site is not None:
        statement = statement.where(
            (
                (local_page.site_pk == local_site.pk)
                & (remote_page.site_pk == remote_site.pk)
            )
            | (
                (local_page.site_pk == remote_site.pk)
                & (remote_page.site_pk == local_site.pk)
            )
        )
    elif local_site is not None:
        statement = statement.where(
            (local_page.site_pk == local_site.pk)
            | (remote_page.site_pk == local_site.pk)
        )
    return list(session.exec(statement).all())


def unlink_index(session: Session, work: IndexLink, *, cascade: bool = False) -> int:
    """Stop tracking a work.

    Without ``cascade`` the page pairs survive, released rather than deleted:
    "this work is no longer tracked against that one" says nothing about
    whether its pages still correspond, and the pairs are expensive to rebuild
    and carry ladders of their own.

    With ``cascade`` the pairs go too, ladders and all -- for the case the
    release is meant to fix, which is a work linked to the wrong other work.
    Every pair under it was then asserted about the wrong pages.

    Returns the number of page pairs affected either way. The Index pages' own
    pairing goes in both cases: it *is* the work.
    """
    children = children_of(session, work)
    for pair in children:
        if cascade:
            unpair(session, pair)
        else:
            pair.index_link_pk = None
            session.add(pair)

    pairing = session.get(PageLink, work.page_link_pk)
    session.delete(work)
    session.flush()
    if pairing is not None:
        unpair(session, pairing)
    return len(children)
