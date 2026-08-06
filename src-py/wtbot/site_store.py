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


#: Label pairs meaning "mine" and "the canonical one", tried in order when a
#: caller names neither. Conventions, not magic: each is a naming an operator
#: chose, and the git one is included because `origin`/`upstream` already means
#: exactly this relationship to anyone who has forked a repository.
PAIR_CONVENTIONS: tuple[tuple[str, str], ...] = (
    ("local", "remote"),
    ("origin", "upstream"),
    ("mywikisource", "wikisource"),
)


def resolve_pair(
    session: Session,
    local_label: str | None = None,
    remote_label: str | None = None,
) -> tuple[Site, Site]:
    """The two sites of a cross-wiki operation, named or inferred.

    Both labels, or neither. One alone is refused rather than paired with
    whatever else happens to be registered: a command that silently chose the
    other side would be one typo away from proposing links against the wrong
    wiki, and that is the mistake the whole design is arranged to prevent.

    With neither, the registered labels are matched against ``PAIR_CONVENTIONS``
    in order. Nothing is guessed beyond those: two registered sites in no known
    convention have no inherent direction, so the caller is asked.
    """
    if local_label and remote_label:
        return require_site(session, local_label), require_site(session, remote_label)

    if local_label or remote_label:
        given = "local" if local_label else "remote"
        raise HTTPException(
            status_code=400,
            detail=(
                f"only the {given} site was named. Give both labels, or neither "
                "to use a naming convention."
            ),
        )

    labels = {row.label: row for row in session.exec(select(Site)).all() if row.label}
    for local, remote in PAIR_CONVENTIONS:
        if local in labels and remote in labels:
            return labels[local], labels[remote]

    conventions = ", ".join(f"{a}/{b}" for a, b in PAIR_CONVENTIONS)
    known = ", ".join(sorted(labels)) or "none"
    raise HTTPException(
        status_code=400,
        detail=(
            f"no site pair to infer: registered labels are {known}, and none of "
            f"the conventions ({conventions}) matched. Name both sides."
        ),
    )
