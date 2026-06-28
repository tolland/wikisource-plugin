from typing import Optional

from sqlalchemy import Integer, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from wtbot.model.base import Base


class Namespace(Base):
    __tablename__ = "namespace"
    key: Mapped[int] = mapped_column(Integer, primary_key=True)
    case: Mapped[Optional[str]] = mapped_column(Text)
    name: Mapped[Optional[str]] = mapped_column(Text)
