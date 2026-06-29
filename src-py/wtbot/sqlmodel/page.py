from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class Page(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("site_pk", "page_id", name="uq_page_site_pk_page_id"),
        UniqueConstraint("site_pk", "title", name="uq_page_site_pk_title"),
    )
    pk: int | None = Field(default=None, primary_key=True)

    site_pk: int = Field(foreign_key="site.pk")
    page_id: int

    title: str

    # site: Site = Relationship(back_populates="pages")

    title: str
    content_model: str
    latest_revision_id: int
    oldest_revision_id: int
    text: str

    def __repr__(self):
        return f"Page(id={self.id}, title={self.title})"
