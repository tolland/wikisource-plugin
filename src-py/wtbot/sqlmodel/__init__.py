"""Single source of truth for the wtbot data model.

These SQLModel classes define the SQLite schema shared by the IntelliJ plugin
(via JDBC) and the pywikibot worker. The former hand-written
``schema/schema.sql`` was removed so the model has one authority -- these
classes. See ``src-py/DESIGN.md`` for the rationale behind each table.
"""

from wtbot.sqlmodel.commit import Commit, CommitStatus
from wtbot.sqlmodel.edit_journal import EditJournal
from wtbot.sqlmodel.fetch_request import FetchKind, FetchRequest, FetchStatus
from wtbot.sqlmodel.file_blob import FileBlob
from wtbot.sqlmodel.namespace import Namespace, NsRole, role_for_canonical
from wtbot.sqlmodel.page import FetchState, Page
from wtbot.sqlmodel.site import Site
from wtbot.sqlmodel.site_credential import SiteCredential
from wtbot.sqlmodel.transclusion import Transclusion

__all__ = [
    "Site",
    "Namespace",
    "NsRole",
    "role_for_canonical",
    "Page",
    "FetchState",
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
