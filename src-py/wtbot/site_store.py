from fastapi import HTTPException
from sqlmodel import Session, select

from wtbot.model import Site, SiteCredential

"""Resolving a site by the name a person gave it.

One lookup, in one place, because the alternative -- every caller doing its own
``select(Site).where(...)`` and falling back to creating one -- is how a wiki
came to be registered by a typo in a fetch request and then read anonymously.
"""


def site_by_label(session: Session, label: str) -> Site | None:
    return session.exec(select(Site).where(Site.label == label)).first()


def require_site(session: Session, label: str) -> Site:
    """The site called ``label``, or a 404 naming what is registered.

    The error lists the known labels: the overwhelmingly likely cause is a
    typo or a site nobody has registered yet, and both are answered by seeing
    the list.
    """
    site = site_by_label(session, label)
    if site is not None:
        return site
    known = sorted(row.label for row in session.exec(select(Site)).all() if row.label)
    raise HTTPException(
        status_code=404,
        detail=(
            f"no site labelled {label!r}. "
            + (f"Registered: {', '.join(known)}." if known else "None registered.")
            + " Register one with `wtbot site add`."
        ),
    )


def has_credential(session: Session, site: Site) -> bool:
    return session.get(SiteCredential, site.pk) is not None
