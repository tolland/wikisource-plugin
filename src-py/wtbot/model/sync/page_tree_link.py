from datetime import datetime

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class PageTreeLink(SQLModel, table=True):
    """A root PageLink whose descendants correspond by relative subpage path."""

    pk: int = Field(primary_key=True, foreign_key="pagelink.pk")
    created_at: datetime = Field(default_factory=utcnow)
