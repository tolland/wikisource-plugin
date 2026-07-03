"""Single source of truth for the wtbot data model.

These SQLModel classes define the SQLite schema shared by the IntelliJ plugin
(via JDBC) and the pywikibot worker. The former hand-written
``schema/schema.sql`` was removed so the model has one authority -- these
classes. See ``src-py/DESIGN.md`` for the rationale behind each table.
"""

from wtbot.model.commit import Commit, CommitStatus
from wtbot.model.edit_journal import EditJournal
from wtbot.model.fetch_request import FetchKind, FetchRequest, FetchStatus
from wtbot.model.file_blob import FileBlob
from wtbot.model.namespace import Namespace, NsRole, role_for_canonical
from wtbot.model.page import FetchState, Page
from wtbot.model.page_meta import (
    FileMeta,
    FileOrigin,
    IndexMeta,
    PageMeta,
    default_short_name,
)
from wtbot.model.site import Site
from wtbot.model.site_credential import SiteCredential
from wtbot.model.transclusion import Transclusion

__all__ = [
    "Site",
    "Namespace",
    "NsRole",
    "role_for_canonical",
    "Page",
    "FetchState",
    "IndexMeta",
    "PageMeta",
    "FileMeta",
    "FileOrigin",
    "default_short_name",
    "FileBlob",
    "Transclusion",
    "FetchRequest",
    "FetchKind",
    "FetchStatus",
    "EditJournal",
    "Commit",
    "CommitStatus",
    "SiteCredential",
]
