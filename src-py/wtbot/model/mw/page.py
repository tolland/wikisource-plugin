from typing import List
from typing import Optional

from sqlalchemy import Integer, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship
from wtbot.model.base import Base


class Page(Base):
    __tablename__ = "page"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[Optional[int]] = mapped_column(Integer)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=False)
    ns: Mapped[int] = mapped_column(Integer, CheckConstraint("ns in (0, 1)"))
    site: Mapped[Optional[str]] = mapped_column(Text)
    latest_revision_id: Mapped[Optional[int]] = mapped_column(Integer)
    oldest_revision_id: Mapped[Optional[int]] = mapped_column(Integer)

    revisions: Mapped[List["Site"]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"Page(id={self.id}, title={self.title})"
