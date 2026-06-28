from typing import Optional

from sqlalchemy import Integer, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey
from wtbot.model.base import Base


class Site(Base):
    __tablename__ = "site"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sitename: Mapped[Optional[str]] = mapped_column(Text)
    dbname: Mapped[Optional[str]] = mapped_column(Text)
    base: Mapped[Optional[str]] = mapped_column(Text)
    generator: Mapped[Optional[str]] = mapped_column(Text)
    case: Mapped[Optional[str]] = mapped_column(Text)
