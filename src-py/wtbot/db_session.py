from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session

from wtbot.model import Site

"""Session discipline shared by the workers.

Both workers do slow network I/O between database touches, so both follow one
rule: never carry an open transaction into a wiki call. SQLite under WAL gives
readers no lock, but an unfinished transaction still pins a snapshot and, on
the write side, holds the write lock for the length of an HTTP round trip --
which is how a fetch of one page could block every other writer for as long as
the wiki took to answer.

The rule was previously spelled out as ``try: ... finally: session.rollback()``
at fourteen call sites. Written out each time it is easy to add a fifteenth
that forgets, and the reason -- which is about pywikibot, not about SQL -- had
nowhere to live. These two helpers name it instead.
"""


@contextmanager
def read_snapshot(session: Session) -> Iterator[Session]:
    """Read, then leave the session idle.

    For queries whose results are copied out and used after the transaction
    ends -- which, in the workers, is all of them.
    """
    try:
        yield session
    finally:
        session.rollback()


@contextmanager
def write_batch(session: Session) -> Iterator[Session]:
    """Commit on success, roll back on failure, end idle either way.

    The rollback in the failure path is not redundant with the caller's own
    error handling: a failed flush leaves the session in a state where the next
    statement raises something unrelated to the original fault, which is a good
    way to lose the real error.
    """
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


def detached_site(site: Site) -> Site:
    """A plain copy of a Site row, safe to use after its session closes.

    The workers hand a Site to the client factory and then make network calls
    with it. A live ORM instance would lazy-load against a session that has
    moved on (or been rolled back) at some arbitrary point inside pywikibot;
    copying the scalars is what makes the boundary explicit.
    """
    return Site(
        pk=site.pk,
        family=site.family,
        code=site.code,
        articlepath=site.articlepath,
        api_url=site.api_url,
        label=site.label,
        created_at=site.created_at,
    )
