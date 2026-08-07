from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware UTC now. Use as a Field default_factory so timestamps are
    consistent and comparable across the plugin and the pywikibot worker."""
    return datetime.now(timezone.utc)


def as_utc(moment: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime, leave an aware one alone.

    SQLite has no timezone type, so a timestamp stored aware comes back naive
    and comparing it to one from the API raises TypeError. Everything this
    codebase stores is UTC, so the missing tzinfo is a lossy round-trip rather
    than an unknown zone -- but that has to be said explicitly at the boundary
    instead of assumed at each comparison.
    """
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=timezone.utc)
