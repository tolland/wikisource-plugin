from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.model import LinkOrigin, Page, PageLink, RemoteLink, Site
from wtbot.remote_link_store import LinkError

"""Reading and writing page pairings.

The pairing is the mutable half of correspondence, and the split from
``RemoteLink`` is the point:

- **A pairing can be removed.** "These two pages are the same page" is a claim
  about the present, and a wrong one is corrected by deleting it. Deleting takes
  its revision links with it -- they were assertions made *within* the pairing,
  and a rung with no ladder is not a fact worth keeping.
- **A revision link cannot.** "These two revisions hold the same content" is a
  claim about two immutable objects; it cannot stop being true, so it is
  superseded rather than edited (see ``wtbot.remote_link_store``).

Pairings survive renames because they name page pks. Nothing here compares
titles: a page moved on either wiki keeps its pairing, which is the whole
reason this is stored rather than recomputed.
"""


def pair_pages(
    session: Session,
    local_page: Page,
    remote_page: Page,
    *,
    origin: LinkOrigin = LinkOrigin.title_match,
) -> PageLink:
    """Assert that two pages are the same page.

    Idempotent on the unordered pair, keeping the original orientation and
    origin: re-pairing is not new information, and flipping the orientation
    would silently reverse the ladder every rung is written in.
    """
    if local_page.pk == remote_page.pk:
        raise LinkError("a page cannot be paired with itself")
    if local_page.site_pk == remote_page.site_pk:
        raise LinkError(
            "a PageLink pairs pages across sites; both are on site "
            f"{local_page.site_pk}"
        )

    existing = find_pair(session, local_page.pk, remote_page.pk)
    if existing is not None:
        return existing

    link = PageLink(
        local_page_pk=local_page.pk,
        remote_page_pk=remote_page.pk,
        origin=origin,
    )
    session.add(link)
    session.flush()
    return link


def find_pair(session: Session, page_pk: int, other_page_pk: int) -> PageLink | None:
    """The pairing of two pages, whichever way round it was stored."""
    return session.exec(
        select(PageLink).where(
            (
                (PageLink.local_page_pk == page_pk)
                & (PageLink.remote_page_pk == other_page_pk)
            )
            | (
                (PageLink.local_page_pk == other_page_pk)
                & (PageLink.remote_page_pk == page_pk)
            )
        )
    ).first()


def pair_for_page(
    session: Session, page_pk: int, other_site_pk: int
) -> PageLink | None:
    """This page's pairing with a given site, from either orientation."""
    other = func.iif(
        PageLink.local_page_pk == page_pk,
        PageLink.remote_page_pk,
        PageLink.local_page_pk,
    )
    return session.exec(
        select(PageLink)
        .join(Page, Page.pk == other)
        .where(
            (PageLink.local_page_pk == page_pk) | (PageLink.remote_page_pk == page_pk),
            Page.site_pk == other_site_pk,
        )
    ).first()


def pairs_for_index(
    session: Session, local_site: Site, index_title: str
) -> list[PageLink]:
    """Every pairing whose local side belongs to one index.

    Deliberately keyed on the *local* side only: this is "show me this work",
    and the other side's index title is exactly what may differ.
    """
    from wtbot.matching import index_children

    page_pks = {page.pk for _, page in index_children(session, local_site, index_title)}
    if not page_pks:
        return []
    return list(
        session.exec(
            select(PageLink).where(
                PageLink.local_page_pk.in_(page_pks)
                | PageLink.remote_page_pk.in_(page_pks)
            )
        ).all()
    )


def unpair(session: Session, link: PageLink) -> int:
    """Remove a pairing and the revision links asserted under it.

    Returns how many rungs went with it. Cascading rather than orphaning: a
    ``RemoteLink`` whose pairing has been retracted is a claim about two
    revisions nobody says correspond, and leaving it would let a later pairing
    inherit assertions made under a different one.
    """
    rungs = session.exec(
        select(RemoteLink).where(RemoteLink.page_link_pk == link.pk)
    ).all()
    for rung in rungs:
        session.delete(rung)
    session.delete(link)
    session.flush()
    return len(rungs)


def other_side(link: PageLink, page_pk: int) -> int:
    """The page pk at the other end of a pairing."""
    if page_pk == link.local_page_pk:
        return link.remote_page_pk
    if page_pk == link.remote_page_pk:
        return link.local_page_pk
    raise LinkError(f"page {page_pk} is not part of pairing {link.pk}")
