from uuid import uuid4

from fastapi import Depends
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import Session

from wtbot.deps import get_session
from wtbot.model import DatabaseIdentity


def get_database_id(session: Session = Depends(get_session)) -> str:
    identity = session.get(DatabaseIdentity, 1)
    if identity is None:
        # Supports metadata-created fixtures too; Alembic seeds deployed databases.
        session.execute(
            insert(DatabaseIdentity)
            .values(pk=1, uuid=str(uuid4()))
            .on_conflict_do_nothing()
        )
        session.commit()
        identity = session.get(DatabaseIdentity, 1)
    assert identity is not None
    return identity.uuid
