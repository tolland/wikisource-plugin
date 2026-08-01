from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""Content-addressed body store, mirroring MediaWiki's ``content`` table.

MediaWiki splits ``content`` from ``text`` because ``content_address`` may point
into External Store and ``old_flags`` carries compression. We hold text directly
in SQLite, so the two are merged here -- the indirection buys nothing.

The one place this deliberately diverges from MediaWiki is that it carries
**two** hashes, because for ``proofread-page`` they are genuinely different
quantities (see docs/proofread-page-sha1-discordance.md):

- ``content_sha1`` is ours, over the bytes the API actually served us. It is
  the only portable identity token, and the one cross-wiki comparison joins on.
- ``remote_sha1`` is the wiki's own ``content_sha1``, over the bytes it stored.
  ProofreadPage can store a structured, wrapper-free form and serve a
  reconstructed ``text/x-wiki`` form, so this may hash bytes we never receive.

MediaWiki needs only one because it hashes what it stores; we cannot see those
bytes, so we cannot reproduce it.
"""


class Content(SQLModel, table=True):
    """One distinct body, keyed by our hash of it.

    Rows are shared across revisions *and across sites*: two revisions on two
    different wikis holding the same text resolve to one row, which is what
    turns cross-wiki "is this the same content?" into a join rather than a
    comparison.
    """

    __table_args__ = (
        # Keyed by (hash, model) rather than hash alone: identical bytes under
        # two content models are not interchangeable, and the pair still gives
        # the cross-site dedup the join relies on.
        UniqueConstraint("content_sha1", "content_model", name="uq_content_sha1_model"),
    )

    pk: int | None = Field(default=None, primary_key=True)

    content_sha1: str = Field(index=True)
    """Base-36 SHA-1 of ``text`` as UTF-8, computed by us. The comparison token."""

    content_model: str | None = None  # 'wikitext', 'proofread-page', ...
    text: str
    size: int  # byte length of `text` as UTF-8

    remote_sha1: str | None = None
    """The wiki's ``content_sha1``. Informational: usable to *prove* equality
    when it matches a hash we hold, never to prove difference when it doesn't."""

    remote_size: int | None = None
    """The wiki's ``content_size`` -- **not a byte length of any serialization**,
    and never comparable to :attr:`size`.

    ``Content::getSha1()`` is not overridden by ProofreadPage, so it falls
    through to core and hashes the *serialized* form -- the bytes the API
    serves, which is why ``remote_sha1`` can agree with ours. But both
    ProofreadPage content classes **do** override ``getSize()`` to sum their
    component parts:

        PageContent::getSize()  = header + body + footer sizes
        IndexContent::getSize() = sum of field values + category texts

    Neither includes the ``<noinclude>``/``<pagequality>`` wrappers or, for an
    index, the template call and field names. So an empty Page: whose served
    text is 86 bytes of wrapper reports ``content_size`` 0, and the two
    disagreeing is correct rather than a fault. The pair are measures of
    different things by construction, not a hash and a length of the same
    bytes."""

    @property
    def sha1_agrees(self) -> bool | None:
        """Whether the wiki's hash covers the same bytes it served us.

        None when we have no remote hash to compare. True makes ``remote_sha1``
        a verified shortcut for this row -- which is what lets a cheap metadata
        probe stand in for fetching content, without relying on the 2018
        touch-edit heuristic.
        """
        if self.remote_sha1 is None:
            return None
        return self.remote_sha1 == self.content_sha1
