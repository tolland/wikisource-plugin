"""Single source of truth for the wtbot data model.

These SQLModel classes define the SQLite schema shared by the IntelliJ plugin
(via JDBC) and the pywikibot worker. The former hand-written
``schema/schema.sql`` was removed so the model has one authority -- these
classes. See ``src-py/DESIGN.md`` for the rationale behind each table.
"""

from wtbot.model.box_range_link import BoxRangeLink
from wtbot.model.commit import Commit, CommitStatus
from wtbot.model.content import Content
from wtbot.model.edit_journal import EditJournal
from wtbot.model.fetch_request import FetchKind, FetchRequest, FetchStatus
from wtbot.model.file_blob import FileBlob
from wtbot.model.file_meta import FileMeta, FileOrigin
from wtbot.model.index_meta import IndexMeta
from wtbot.model.namespace import Namespace, NsRole, role_for_canonical
from wtbot.model.ocr_backend import OcrBackendConfig, OcrBackendKind
from wtbot.model.page import FetchState, Page
from wtbot.model.page_meta import (
    PageMeta,
    default_short_name,
)
from wtbot.model.remote_link import LinkOrigin, RemoteLink
from wtbot.model.revision import Revision
from wtbot.model.scan_annotation import AnnotationCategory, ScanAnnotation
from wtbot.model.site import Site
from wtbot.model.site_credential import SiteCredential
from wtbot.model.slot import MAIN_SLOT, Slot
from wtbot.model.text_target_anchor import TextTargetAnchor
from wtbot.model.transclusion import Transclusion

__all__ = [
    "AnnotationCategory",
    "ScanAnnotation",
    "TextTargetAnchor",
    "BoxRangeLink",
    "OcrBackendConfig",
    "OcrBackendKind",
    "Site",
    "Namespace",
    "NsRole",
    "role_for_canonical",
    "Page",
    "FetchState",
    "Revision",
    "RemoteLink",
    "LinkOrigin",
    "Slot",
    "MAIN_SLOT",
    "Content",
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
