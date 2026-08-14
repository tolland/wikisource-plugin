from datetime import datetime

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class SiteCredential(SQLModel, table=True):
    """Per-site login credential. Deliberately separate from the Site row so
    Site rows are safe to inspect and log without leaking secrets. The password
    field is plaintext -- acceptable for a local single-user dev tool; the DB
    lives in the same process-local directory as the pywikibot config."""

    __tablename__ = "sitecredential"

    site_pk: int = Field(primary_key=True, foreign_key="site.pk")
    username: str
    bot_name: str | None = None  # BotPasswords suffix (without @)
    password: str
    updated_at: datetime = Field(default_factory=utcnow)
