from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class Site(SQLModel, table=True):
    """One MediaWiki instance, registered before anything fetches from it.

    Two identities, for two audiences. The pywikibot (family, code) pair is
    what pywikibot keys on and stays unique. ``label`` is what a *person* names
    the wiki -- and what the CLI and API take, because the alternative was
    passing family/code/api_url on every call, which meant any typo silently
    registered a new, credential-less wiki and fetched from it anonymously.
    Sites are created deliberately now (see ``wtbot site add``); nothing
    conjures one from the parameters of a fetch.

    ``api_url`` is derived/optional, never the key, because pageids/revids
    from two independent wikis are not comparable. (A ``host`` column used to
    sit beside it; nothing ever read it, so it was dropped.)

    ``family``/``code`` survive the move to generated pywikibot config on
    purpose. The family is the AutoFamily name for ``api_url`` sites, and it
    must be operator-chosen: pywikibot's process-global Site cache ignores the
    port, so two local wikis distinguished only by port would silently share
    one APISite if the name were derived from the URL (see
    wtbot.wiki.client). For family-file sites the pair is the whole address.
    """

    __table_args__ = (
        UniqueConstraint("family", "code", name="uq_site_family_code"),
        UniqueConstraint("label", name="uq_site_label"),
    )

    pk: int | None = Field(default=None, primary_key=True)

    family: str  # pywikibot family, e.g. 'wikisource', 'mywikisource'
    code: str  # pywikibot language code, e.g. 'en'
    articlepath: str = "/wiki/$1"

    # Derived / optional -- handy for the UI and for building API calls, but not
    # part of the identity.
    api_url: str | None = None  # full action=... endpoint
    # The operator-facing handle: unique, and what --label resolves against.
    # Nullable only because fixtures build Site rows directly; every creation
    # surface requires one.
    label: str | None = None  # 'local', 'en.wikisource', 'staging'

    read_throttle: float | None = None
    """Per-site minimum seconds between API reads.

    None inherits the process-wide ``RateLimitPolicy``. A local Docker wiki
    can use a much smaller value without weakening the conservative Wikimedia
    policy for every other registered site.
    """

    created_at: datetime = Field(default_factory=utcnow)
