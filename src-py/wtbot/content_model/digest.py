from wtbot.content_model.document import parse_document
from wtbot.wiki.sha1 import content_sha1_base36

"""A hash that answers "are these two bodies the same content?" without parsing.

``Content.content_sha1`` cannot answer it. It covers the bytes the wiki served,
and a ``proofread-page`` body embeds ``<pagequality level="3" user="X" />`` in
its own text -- the username names an account on *that* wiki, so the same
transcription hashes differently on the two sides as a matter of course. That is
why cross-site sameness is decided by the content-model comparison rather than
by a hash.

The comparison is the right answer and an expensive one: the anchor search walks
a page's stored revisions newest-first and, before this existed, parsed every
one of them on every walk. So the *result* of the model-aware normalisation is
hashed once, when the content row is written, and the walk compares two strings.

The digest covers exactly what the comparison treats as deciding sameness:

- everything comparable (for ``proofread-page``: header, body and footer),
- plus the metadata the comparison treats as *significant* -- the proofreading
  level, which is directional and must not be flattened,
- with the site-local fields blanked (the ``user`` attribute).

So two digests are equal exactly when the comparison would return
``same_transcription`` at a significance other than ``metadata_significant`` --
which is the predicate the anchor search runs. Equal digests still leave the
reviewer-facing difference (which user, if any) to the full comparison; the
digest decides *whether* a pair matches, never *what* to show about it.

**Not comparable across content models.** Two documents of different models can
in principle produce the same canonical string, and a match between them would
be an artefact of the normalisation rather than a fact about the text. Callers
compare digests only when the two rows share a content model, and fall back to
the full comparison otherwise.
"""


def comparable_sha1(text: str, content_model: str | None) -> str:
    """The base-36 sha1 of ``text``'s canonical form under its content model."""
    return content_sha1_base36(parse_document(text, content_model).canonical_text)
