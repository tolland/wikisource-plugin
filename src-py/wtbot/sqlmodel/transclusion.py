from sqlmodel import Field, SQLModel


class Transclusion(SQLModel, table=True):
    """A mainspace page pulling in Page: content via
    ``<pages index="..." from="N" to="M" />``. Needed to fetch "the Index plus
    any work that transcludes it" and to invalidate a composed work's rendered
    view when one of its constituent Pages changes."""

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk")
    source_page_pk: int = Field(foreign_key="page.pk")  # the mainspace page
    index_title: str = Field(index=True)  # target Index: title
    from_page: int
    to_page: int
