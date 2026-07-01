from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.sqlmodel import Site, SiteCredential
from wtbot.timeutil import utcnow

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("/", response_model=list[Site])
def list_sites(session: Session = Depends(get_session)) -> list[Site]:
    return list(session.exec(select(Site)).all())


@router.post("/", response_model=Site, status_code=201)
def create_site(site: Site, session: Session = Depends(get_session)) -> Site:
    session.add(site)
    session.commit()
    session.refresh(site)
    return site


@router.get("/{site_pk}", response_model=Site)
def get_site(site_pk: int, session: Session = Depends(get_session)) -> Site:
    site = session.get(Site, site_pk)
    if site is None:
        raise HTTPException(status_code=404, detail="site not found")
    return site


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
        cred = SiteCredential(site_pk=site_pk, username=body.username, password=body.password)
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
def get_credential(site_pk: int, session: Session = Depends(get_session)) -> SiteCredential:
    cred = session.get(SiteCredential, site_pk)
    if cred is None:
        raise HTTPException(status_code=404, detail="no credential configured for this site")
    return cred


@router.delete("/{site_pk}/credential", status_code=204)
def delete_credential(site_pk: int, session: Session = Depends(get_session)) -> None:
    cred = session.get(SiteCredential, site_pk)
    if cred is None:
        raise HTTPException(status_code=404, detail="no credential configured for this site")
    session.delete(cred)
    session.commit()
