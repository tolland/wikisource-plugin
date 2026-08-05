from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class Site(SQLModel, table=True):
    """One MediaWiki instance. Identity is the pywikibot (family, code) pair --
    that is the request vocabulary (``title:x family:y code:z``) and what
    pywikibot itself keys on. ``host``/``api_url`` are derived/optional, never the
    key, because pageids/revids from two independent wikis are not comparable.
    """

    __table_args__ = (UniqueConstraint("family", "code", name="uq_site_family_code"),)

    pk: int | None = Field(default=None, primary_key=True)

    family: str  # pywikibot family, e.g. 'wikisource', 'mywikisource'
    code: str  # pywikibot language code, e.g. 'en'
    articlepath: str = "/wiki/$1"

    # Derived / optional -- handy for the UI and for building API calls, but not
    # part of the identity.
    host: str | None = None  # 'en.wikisource.org', 'wikisource-debian-13.lan'
    api_url: str | None = None  # full action=... endpoint
    label: str | None = None  # human-readable, for the IDE ('Local', 'en.wikisource')

    changes_seen_through: datetime | None = None
    """Newest ``recentchanges`` timestamp we have acted on for this site.

    The watermark an incremental refresh resumes from (see wtbot.incremental).
    Stored per site because it is a position in *that* wiki's change stream --
    two wikis holding the same work have unrelated ones.

    None means "never refreshed incrementally", which is not the same as "no
    changes": it downgrades the next plan to a full pass rather than letting an
    empty answer read as up to date.
    """

    created_at: datetime = Field(default_factory=utcnow)
