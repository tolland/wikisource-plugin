from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

FILE_NAMESPACE_KEY = 6  # MediaWiki core namespace; unlike extension IDs, fixed.


class Namespace(SQLModel, table=True):
    """Per-site namespace identity and capabilities from ``siteinfo``.

    Page behaviour is determined separately by content_model.
    """

    __table_args__ = (UniqueConstraint("site_pk", "key", name="uq_ns_site_key"),)

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk")

    key: int  # site-local numeric id (104 or 250 ...)
    canonical_name: str  # 'Page', 'Index', 'File' -- stable across sites
    local_name: str  # display name on this wiki (may be localized)
    subpages: bool = False
    content: bool = False  # True for main content namespaces
    case: str | None = None  # 'first-letter' | 'case-sensitive'
