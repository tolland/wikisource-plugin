from uuid import uuid4

from sqlalchemy import CheckConstraint
from sqlmodel import Field, SQLModel


class DatabaseIdentity(SQLModel, table=True):
    """Identity of this cache database, preserved through service restarts."""

    __table_args__ = (CheckConstraint("pk = 1", name="singleton"),)
    pk: int = Field(default=1, primary_key=True)
    uuid: str = Field(default_factory=lambda: str(uuid4()))
