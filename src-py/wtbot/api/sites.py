from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.sqlmodel import Site

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
