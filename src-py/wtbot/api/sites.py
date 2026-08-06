from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.model import Site, SiteCredential
from wtbot.site_delete import SiteDeletePlan, execute_site_delete, plan_site_delete
from wtbot.site_store import require_site, site_by_label
from wtbot.timeutil import utcnow

router = APIRouter(prefix="/sites", tags=["sites"])

"""Site registration.

A site is registered before anything fetches from it, and is addressed by its
``label`` thereafter. Nothing creates one implicitly: a fetch for an unknown
label is an error, not an invitation to register a wiki nobody configured and
then read from it with whatever credentials that new row happens to have (none).
"""


class SiteRequest(BaseModel):
    family: str
    code: str
    label: str = Field(
        description=(
            "Unique operator-facing name; what --label and the fetch API "
            "resolve against."
        )
    )
    articlepath: str = "/wiki/$1"
    api_url: str | None = None


@router.get("/", response_model=list[Site])
def list_sites(session: Session = Depends(get_session)) -> list[Site]:
    """
    List all sites.

    :param session:
    :return:
    """
    return list(session.exec(select(Site)).all())


@router.post("/", response_model=Site, status_code=201)
def create_site(body: SiteRequest, session: Session = Depends(get_session)) -> Site:
    """Register a wiki. The label must be free, and so must (family, code)."""
    if site_by_label(session, body.label) is not None:
        raise HTTPException(
            status_code=409, detail=f"a site is already labelled {body.label!r}"
        )
    clash = session.exec(
        select(Site).where(Site.family == body.family, Site.code == body.code)
    ).first()
    if clash is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{body.family}:{body.code} is already registered as "
                f"{clash.label!r}"
            ),
        )
    site = Site(**body.model_dump())
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


@router.get("/by-label/{label}", response_model=Site)
def get_site_by_label(label: str, session: Session = Depends(get_session)) -> Site:
    """Resolve a label. Registered before the catch-all /sites/{site_pk},
    which would otherwise swallow it and 422 on the int parse."""
    return require_site(session, label)


@router.get("/{site_pk}", response_model=Site)
def get_site(site_pk: int, session: Session = Depends(get_session)) -> Site:
    site = session.get(Site, site_pk)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site


@router.put("/{site_pk}", response_model=Site)
def update_site(
    site_pk: int, body: SiteRequest, session: Session = Depends(get_session)
) -> Site:
    site = session.get(Site, site_pk)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")

    site.family = body.family
    site.code = body.code
    site.articlepath = body.articlepath
    site.api_url = body.api_url
    site.label = body.label
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


@router.get("/{site_pk}/delete-plan", response_model=SiteDeletePlan)
def site_delete_plan(
    site_pk: int, session: Session = Depends(get_session)
) -> SiteDeletePlan:
    """What DELETE /sites/{site_pk} would remove, without removing it.

    Deleting a site takes its whole local cache with it -- pages, revisions,
    the fetch queue, the edit journal -- so the consequences are enumerable
    before they are consequences (see `wtbot site delete`, which shows this
    unless --force is given)."""
    site = session.get(Site, site_pk)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return plan_site_delete(session, site)


@router.delete("/{site_pk}", response_model=SiteDeletePlan)
def delete_site(
    site_pk: int, session: Session = Depends(get_session)
) -> SiteDeletePlan:
    """Delete a site and everything that only exists because of it.

    Returns what was deleted -- the same shape the delete-plan endpoint
    previews. Content rows shared with another site survive."""
    site = session.get(Site, site_pk)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return execute_site_delete(session, site)


# ---------------------------------------------------------------------------
# Credential sub-resource  (one credential row per site at most)
# ---------------------------------------------------------------------------


class CredentialRequest(BaseModel):
    username: str
    password: str
    bot_name: str | None = None


@router.put("/{site_pk}/credential", response_model=SiteCredential)
def upsert_credential(
    site_pk: int,
    body: CredentialRequest,
    session: Session = Depends(get_session),
) -> SiteCredential:
    if session.get(Site, site_pk) is None:
        raise HTTPException(status_code=404, detail="site not found")
    cred = session.get(SiteCredential, site_pk)
    if cred is None:
        cred = SiteCredential(
            site_pk=site_pk, username=body.username, password=body.password
        )
    else:
        cred.username = body.username
        cred.password = body.password
        cred.updated_at = utcnow()
    cred.bot_name = body.bot_name
    session.add(cred)
    session.commit()
    session.refresh(cred)
    return cred


@router.get("/{site_pk}/credential", response_model=SiteCredential)
def get_credential(
    site_pk: int, session: Session = Depends(get_session)
) -> SiteCredential:
    cred = session.get(SiteCredential, site_pk)
    if cred is None:
        raise HTTPException(
            status_code=404, detail="no credential configured for this site"
        )
    return cred


@router.delete("/{site_pk}/credential", status_code=204)
def delete_credential(site_pk: int, session: Session = Depends(get_session)) -> None:
    cred = session.get(SiteCredential, site_pk)
    if cred is None:
        raise HTTPException(
            status_code=404, detail="no credential configured for this site"
        )
    session.delete(cred)
    session.commit()
