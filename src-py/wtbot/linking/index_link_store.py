from sqlalchemy import and_, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, select

from wtbot.linking.page_link_store import find_pair, pair_pages, unpair
from wtbot.linking.remote_link_store import LinkError
from wtbot.model import (
    IndexLink,
    IndexMeta,
    LinkOrigin,
    PageLink,
    ProofreadPageMeta,
    Site,
    Title,
)

"""Putting a work under cross-site tracking, and finding the ones that are.

Two operations, and the whole of the work-level model:

- **link** two ``Index:`` pages. The pairing is an ordinary ``PageLink`` (see
  ``wtbot.model.index_link`` for why); this adds the ``IndexLink`` that says
  the pairing is a *work*. It shares the pairing's primary key.
- **unlink**. Two widths, as with pairings: stop tracking the work, or that
  plus discard the pairings under it.

There is no third operation. A work's page pairs used to be *adopted* -- each
pointed at its work when the work was linked, because pairing pages and
declaring a work tracked happen in either order. Membership is now derived
(``children_of``) from each page's ``ProofreadPageMeta.index_title_pk``, so a
pair belongs to its work whenever both exist, in whichever order they came.
"""


def link_indexes(
    session: Session,
    local_index: Title,
    remote_index: Title,
    *,
    origin: LinkOrigin = LinkOrigin.manual,
) -> IndexLink:
    """Declare two ``Index:`` pages to be the same work.

    Idempotent: a work already linked is returned as it stands, including when
    the two sides are named the other way round. Re-declaring is not new
    information, and a second row would give one work two identities.
    """
    for page in (local_index, remote_index):
        meta = session.exec(
            select(IndexMeta).where(
                IndexMeta.title_pk == page.pk,
                IndexMeta.site_pk == page.site_pk,
            )
        ).first()
        if meta is None:
            raise LinkError(
                f"{page.title} has no IndexMeta row and is not a fetched "
                "ProofreadPage Index. A work can only be tracked through its "
                "proofread Index."
            )

    pairing = pair_pages(session, local_index, remote_index, origin=origin)

    assert pairing.pk is not None  # flushed by pair_pages
    existing = session.get(IndexLink, pairing.pk)
    if existing is not None:
        return existing

    work = IndexLink(pk=pairing.pk)
    session.add(work)
    session.flush()
    return work


def children_of(session: Session, work: IndexLink) -> list[PageLink]:
    """The page pairs belonging to a work, in no particular order.

    A pair belongs when one of its pages is a child of either of the work's
    indexes -- by ``ProofreadPageMeta.index_title_pk``, never by title -- and
    the other page is on the other index's site. The site condition is what
    tells two works of one index apart when that index is tracked against
    more than one wiki. The other page need not have metadata of its own: a
    target page not yet fanned out still pairs.

    Ordering is the caller's business: the viewer wants reading order, which
    means page number, which lives on ``ProofreadPageMeta`` -- a join this
    module has no reason to force on every reader.
    """
    pairing = session.get(PageLink, work.pk)
    if pairing is None:  # pragma: no cover - the shared key holds
        return []
    one = session.get(Title, pairing.local_page_pk)
    two = session.get(Title, pairing.remote_page_pk)
    if one is None or two is None:  # pragma: no cover - foreign keys hold
        return []

    local_title, remote_title = aliased(Title), aliased(Title)
    local_meta, remote_meta = aliased(ProofreadPageMeta), aliased(ProofreadPageMeta)

    def child_of(meta, index: Title, other_side, other_index: Title):
        return and_(
            meta.index_title_pk == index.pk, other_side.site_pk == other_index.site_pk
        )

    return list(
        session.exec(
            select(PageLink)
            .join(local_title, local_title.pk == PageLink.local_page_pk)
            .join(remote_title, remote_title.pk == PageLink.remote_page_pk)
            .outerjoin(local_meta, col(local_meta.title_pk) == PageLink.local_page_pk)
            .outerjoin(
                remote_meta, col(remote_meta.title_pk) == PageLink.remote_page_pk
            )
            .where(
                PageLink.pk != pairing.pk,
                or_(
                    child_of(local_meta, one, remote_title, two),
                    child_of(local_meta, two, remote_title, one),
                    child_of(remote_meta, one, local_title, two),
                    child_of(remote_meta, two, local_title, one),
                ),
            )
        ).all()
    )


def find_index_link(
    session: Session, local_page_pk: int, remote_page_pk: int
) -> IndexLink | None:
    """The work linking two Index pages, whichever way round it was asserted."""
    pairing = find_pair(session, local_page_pk, remote_page_pk)
    return session.get(IndexLink, pairing.pk) if pairing is not None else None


def work_for_index_page(session: Session, page_pk: int) -> IndexLink | None:
    """The work an Index page belongs to, from either side of the pairing."""
    return session.exec(
        select(IndexLink)
        .join(PageLink, PageLink.pk == IndexLink.pk)
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
    local_page = aliased(Title)
    remote_page = aliased(Title)
    statement = (
        select(IndexLink)
        .join(PageLink, PageLink.pk == IndexLink.pk)
        .join(local_page, local_page.pk == PageLink.local_page_pk)
        .join(remote_page, remote_page.pk == PageLink.remote_page_pk)
        .order_by(col(IndexLink.pk))
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

    Without ``cascade`` the page pairs survive untouched: "this work is no
    longer tracked against that one" says nothing about whether its pages
    still correspond, and the pairs are expensive to rebuild and carry ladders
    of their own. There is nothing to release -- membership was derived.

    With ``cascade`` the pairs go too, ladders and all -- for the case this is
    meant to fix, which is a work linked to the wrong other work. Every pair
    under it was then asserted about the wrong pages.

    Returns the number of page pairs belonging to the work either way. The
    Index pages' own pairing goes in both cases: it *is* the work.
    """
    children = children_of(session, work)
    if cascade:
        for pair in children:
            unpair(session, pair)

    pairing = session.get(PageLink, work.pk)
    session.delete(work)
    session.flush()
    if pairing is not None:
        unpair(session, pairing)
    return len(children)
