import hashlib

import pytest

from wtbot.wiki.sha1 import (
    base36_to_hex,
    content_sha1_base36,
    hex_to_base36,
    normalize_sha1,
)

"""The two encodings MediaWiki reports the same content hash in.

Values are real, taken from the en.wikisource XML dump of
Page:Canadian patent 29537.djvu/2 (base-36) and from what this wiki's
action API returns for the same imported revisions (hex).
"""

# (dump base-36, API hex) for the four revisions of Page:...djvu/2
KNOWN_PAIRS = [
    (
        "7qzy4bystlkoytnzaivpq46nv4bbd1d",
        "425897494d2dce61e94808a0458462461a9d41c1",
    ),
    (
        "ti1n0sdo5tixoaccq10j25r8cwn0lqn",
        "fc8e21d69447543d938056ac42171de2bbf8250f",
    ),
    (
        "d8royu8iytefd8uu41iir20wxrp7rym",
        "716046b28cd450cf98ac91961d28f565aeb69e4e",
    ),
    (
        "ber7rim00nw9gknuje381xd89o14ne7",
        "61ad96427deee611bb5bac3b8fa3318ceb46e06f",
    ),
]


@pytest.mark.parametrize(("base36", "hex_digest"), KNOWN_PAIRS)
def test_encodings_round_trip(base36: str, hex_digest: str) -> None:
    assert hex_to_base36(hex_digest) == base36
    assert base36_to_hex(base36) == hex_digest


@pytest.mark.parametrize(("base36", "hex_digest"), KNOWN_PAIRS)
def test_normalize_accepts_either_encoding(base36: str, hex_digest: str) -> None:
    assert normalize_sha1(hex_digest) == base36
    assert normalize_sha1(base36) == base36


def test_raw_encodings_never_intersect() -> None:
    """The failure this module exists to prevent: intersecting dump hashes
    against API hashes matches nothing, so a page identical on both wikis
    reads as 'unrelated histories'."""
    dump_side = {base36 for base36, _ in KNOWN_PAIRS}
    api_side = {hex_digest for _, hex_digest in KNOWN_PAIRS}
    assert dump_side & api_side == set()

    # Normalised, the same two sets are identical.
    assert {normalize_sha1(d) for d in api_side} == dump_side


def test_base36_is_zero_padded_to_31_chars() -> None:
    """A small digest must not shorten the string -- the length is what
    normalize_sha1 discriminates on."""
    padded = hex_to_base36(f"{1:040x}")
    assert len(padded) == 31
    assert padded.endswith("1")
    assert normalize_sha1(padded) == padded


def test_content_hash_matches_a_locally_computed_digest() -> None:
    text = '<noinclude><pagequality level="3" user="Someone" /></noinclude>body'
    expected = hex_to_base36(hashlib.sha1(text.encode("utf-8")).hexdigest())
    assert content_sha1_base36(text) == expected
    assert len(content_sha1_base36(text)) == 31


def test_normalize_passes_through_unrecognised_lengths() -> None:
    assert normalize_sha1(None) is None
    assert normalize_sha1("") == ""
    assert normalize_sha1("not-a-digest") == "not-a-digest"
