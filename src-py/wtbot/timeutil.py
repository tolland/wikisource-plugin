from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware UTC now. Use as a Field default_factory so timestamps are
    consistent and comparable across the plugin and the pywikibot worker."""
    return datetime.now(timezone.utc)
