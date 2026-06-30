from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.sqlmodel import Namespace, NsRole

router = APIRouter(prefix="/namespaces", tags=["namespaces"])


@router.get("/", response_model=list[Namespace])
def list_namespaces(
    session: Session = Depends(get_session),
    site_pk: int | None = None,
    role: NsRole | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Namespace]:
    statement = (
        select(Namespace)
        .order_by(Namespace.site_pk, Namespace.key)
        .offset(offset)
        .limit(limit)
    )
    if site_pk is not None:
        statement = statement.where(Namespace.site_pk == site_pk)
    if role is not None:
        statement = statement.where(Namespace.role == role)
    return list(session.exec(statement).all())


@router.get("/{namespace_pk}", response_model=Namespace)
def get_namespace(
    namespace_pk: int, session: Session = Depends(get_session)
) -> Namespace:
    namespace = session.get(Namespace, namespace_pk)
    if namespace is None:
        raise HTTPException(status_code=404, detail="namespace not found")
    return namespace
