from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class NsRole(str, Enum):
    """Portable namespace role. Numeric namespace ids are per-site (Page=104 on
    en.wikisource, 250 on a fresh ProofreadPage reinstall; Book is operator-
    chosen), so we never compare ids across wikis -- we compare roles. A role is
    resolved from the *canonical* namespace name, which is stable everywhere."""

    main = "main"
    page = "page"  # ProofreadPage Page:
    index = "index"  # ProofreadPage Index:
    file = "file"
    template = "template"
    module = "module"
    category = "category"
    author = "author"
    book = "book"  # site-custom convention (not a standard Wikisource ns)
    other = "other"


# Canonical MediaWiki namespace names -> role. Names are stable across installs;
# only the integer key moves. Custom roles (e.g. Book) are matched here too but
# may also be set via a per-site override at fetch time.
_CANONICAL_TO_ROLE: dict[str, NsRole] = {
    "": NsRole.main,
    "Page": NsRole.page,
    "Index": NsRole.index,
    "File": NsRole.file,
    "Template": NsRole.template,
    "Module": NsRole.module,
    "Category": NsRole.category,
    "Author": NsRole.author,
    "Book": NsRole.book,
}


def role_for_canonical(canonical_name: str) -> NsRole:
    """Map a canonical namespace name (from siteinfo) to a portable role."""
    return _CANONICAL_TO_ROLE.get(canonical_name, NsRole.other)


class Namespace(SQLModel, table=True):
    """Per-site namespace map, populated from each wiki's ``siteinfo``. Lets a
    Page from a 250-wiki and a Page from a 104-wiki be recognised as the same
    kind of object."""

    __table_args__ = (
        UniqueConstraint("site_pk", "key", name="uq_ns_site_key"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk")

    key: int  # site-local numeric id (104 or 250 ...)
    canonical_name: str  # 'Page', 'Index', 'File' -- stable across sites
    local_name: str  # display name on this wiki (may be localized)
    role: NsRole = NsRole.other
