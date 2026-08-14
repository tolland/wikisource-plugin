from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class IndexMeta(SQLModel, table=True):
    """Curated per-Index metadata.

    `short_name` seeds generated child names —
    ``File:{short_name}_page_{page}_image_{n}.jpg`` — because the full Index
    title (spaces, punctuation, extension) makes miserable filenames.

    Unique per *site*, not globally: the common scenario is a local staging
    instance synced back to upstream wikisource, so generated names must be
    collision-free within the site they will be pushed to; the same work
    staged for two sites may happily reuse one short name.
    """

    __table_args__ = (
        UniqueConstraint("site_pk", "short_name", name="uq_indexmeta_site_short"),
        UniqueConstraint("page_pk", name="uq_indexmeta_page"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)
    site_pk: int = Field(foreign_key="site.pk", index=True)

    short_name: str
    page_count: int | None = None  # total pages per the Index (pagelist/IndexPage)
    # Room to grow: image_name_pattern, OCR region templates, ...
