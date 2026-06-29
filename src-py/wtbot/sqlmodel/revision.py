from sqlmodel import Field, SQLModel, create_engine


class Revision(SQLModel, table=True):
    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int | None = Field(default=None, foreign_key="page.pk")
    contributor_username: str | None = None
    contributor_id: int | None = None
    comment: str | None = None
    origin: str | None = None
    model: str | None = None
    format: str | None = None
    sha1: str | None = None
    text: str | None = None
    timestamp: str | None = None
