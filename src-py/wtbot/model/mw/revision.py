from typing import Optional

from sqlalchemy import Integer, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey
from wtbot.model.base import Base


class Revision(Base):
    __tablename__ = "revision"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page: Mapped[Optional[int]] = mapped_column(ForeignKey("page.id"))
    timestamp: Mapped[Optional[str]] = mapped_column(Text)
    #
    contributor_username: Mapped[Optional[str]] = mapped_column(Text)
    contributor_id: Mapped[Optional[int]] = mapped_column(Integer)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    origin: Mapped[Optional[str]] = mapped_column(Text)
    model: Mapped[Optional[str]] = mapped_column(Text)
    format: Mapped[Optional[str]] = mapped_column(Text)
    sha1: Mapped[Optional[str]] = mapped_column(Text)
    text: Mapped[Optional[str]] = mapped_column(Text)
