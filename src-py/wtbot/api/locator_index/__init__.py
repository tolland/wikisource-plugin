from wtbot.api.locator_index.router import router
from wtbot.api.locator_index.schemas import (
    LocatorIndexDump,
    PageIndexEntry,
    PagelistAssignmentEntry,
    PageNumberMatch,
    PageRef,
    SectionMatch,
)

"""GET /locator-index/{sections,page-numbers,dump} — see `router` for the
endpoints and their docstring, `schemas` for the request/response shapes.
Both are re-exported here so `from wtbot.api import locator_index` and
`locator_index.router` keep working exactly as before the package split."""

__all__ = [
    "router",
    "LocatorIndexDump",
    "PageIndexEntry",
    "PagelistAssignmentEntry",
    "PageNumberMatch",
    "PageRef",
    "SectionMatch",
]
