import hashlib
import string

"""MediaWiki content-hash encodings.

MediaWiki hashes revision text with SHA-1 but *reports it in two different
encodings depending on the surface*, which is a silent-mismatch trap for any
cross-wiki comparison:

- ``action=query&prop=revisions&rvprop=sha1`` (and therefore pywikibot's
  ``Revision.sha1``, and therefore ``Page.sha1`` in this codebase) returns
  **40-char lowercase hex**;
- the XML export (``Special:Export``, dump files) and the ``rev_sha1`` database
  column store **31-char base-36**, zero-padded.

They are the same digest. Comparing one against the other silently never
matches, which would make cross-wiki base discovery (see
docs/design/upstream-sync-discussion.md section 3) conclude "unrelated
histories" for pages
that are in fact identical.
"""

_BASE36_DIGITS = string.digits + string.ascii_lowercase

BASE36_LENGTH = 31
HEX_LENGTH = 40


def hex_to_base36(hex_digest: str) -> str:
    """Convert an API-style hex sha1 to the dump/database base-36 form."""
    value = int(hex_digest, 16)
    return _to_base36(value).rjust(BASE36_LENGTH, "0")


def base36_to_hex(base36_digest: str) -> str:
    """Convert a dump/database base-36 sha1 to the API-style hex form."""
    return f"{int(base36_digest, 36):0{HEX_LENGTH}x}"


def content_sha1_base36(text: str) -> str:
    """The base-36 sha1 MediaWiki would store for ``text``.

    Lets a locally computed or transformed body be compared against a
    dump/database hash without a round trip to the wiki.
    """
    return hex_to_base36(hashlib.sha1(text.encode("utf-8")).hexdigest())


def normalize_sha1(digest: str | None) -> str | None:
    """Coerce either encoding to base-36 so two sources can be compared.

    Length is the discriminator: base-36 digests are 31 chars, hex are 40, and
    the alphabets overlap, so nothing shorter is guessable. Anything else is
    returned unchanged rather than mangled.
    """
    if digest is None:
        return None
    if len(digest) == HEX_LENGTH:
        return hex_to_base36(digest)
    if len(digest) == BASE36_LENGTH:
        return digest
    return digest


def _to_base36(value: int) -> str:
    if value == 0:
        return "0"
    out: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        out.append(_BASE36_DIGITS[remainder])
    return "".join(reversed(out))
