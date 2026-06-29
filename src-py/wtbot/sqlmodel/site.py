from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class Site(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("family", "code", name="uq_site_family_code"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    family: str
    code: str
    articlepath: str
