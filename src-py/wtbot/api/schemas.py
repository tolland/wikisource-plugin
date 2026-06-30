"""
Pydantic schemas for the VFS contract between the IntelliJ plugin and wtbot.

Two surfaces:
  A) Operations  -- request/response, map to VirtualFileSystem method calls
  B) Change feed -- poll-based notification of remote-originated changes

The OpenAPI spec is generated from these by FastAPI (GET /openapi.json); the
Kotlin client is generated from that spec. This file is the source of truth.

Design invariant (load-bearing): a rename/move is represented AS a rename in
the change feed -- carrying old_path, new_path, and the stable id -- never as
a delete+create pair. The plugin cannot reconstruct rename identity from a
path diff after the fact; getting this wrong kills open editor tabs on every
remote rename. The FastAPI layer can see pageid continuity in SQLite that a
raw path diff cannot, so it is the right place to classify this.
"""

from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Shared
# --------------------------------------------------------------------------
class NodeKind(str, Enum):
    file = "file"
    directory = "directory"


class Node(BaseModel):
    """One entry as the VFS sees it. `stable_id` is the rename-survival key
    (MediaWiki pageid) -- distinct from `path`, which changes on rename."""

    path: str = Field(
        ..., description="wikisource://-relative path, uniquely identifies the node"
    )
    name: str
    kind: NodeKind
    stable_id: int | None = Field(
        None,
        description="MediaWiki pageid; survives renames. None until first remote fetch.",
    )
    revid: int | None = Field(
        None, description="Revision id as of last fetch; the conflict token."
    )
    timestamp: str | None = Field(
        None,
        description="Drives VirtualFile.getTimeStamp(). Reflects local_modified_at, "
        "NOT remote revision time -- see schema model notes.",
    )
    length: int | None = Field(
        None, description="Content length in bytes; None for directories."
    )
    writable: bool = False


class Stat(BaseModel):
    path: str
    exists: bool
    kind: NodeKind | None = None
    stable_id: int | None = None
    revid: int | None = None
    timestamp: str | None = None
    length: int | None = None


# --------------------------------------------------------------------------
# A) Operations
# --------------------------------------------------------------------------
class ListChildrenResponse(BaseModel):
    parent_path: str
    children: list[Node]


class ReadContentResponse(BaseModel):
    path: str
    revid: int | None = None
    # Body returned base64 so the OpenAPI contract is JSON-clean; the raw-bytes
    # hot path can bypass this via a separate octet-stream route if profiling
    # shows base64 overhead matters during indexing.
    content_base64: str


class WriteContentRequest(BaseModel):
    path: str
    content_base64: str
    base_revid: int | None = Field(
        None,
        description="Revid the edit is based on -- sent as basetimestamp/conflict token. "
        "A mismatch against current remote state is an edit conflict, surfaced "
        "as WriteResult.status='conflict', not an error.",
    )
    comment: str | None = None


class WriteStatus(str, Enum):
    ok = "ok"
    conflict = "conflict"
    error = "error"


class WriteResult(BaseModel):
    path: str
    status: WriteStatus
    new_revid: int | None = None
    message: str | None = None


class CommitRunResponse(BaseModel):
    handled: int = Field(
        ..., description="Number of pages whose pending local edits were pushed this run."
    )


class RenameRequest(BaseModel):
    path: str
    new_name: str
    requestor: str | None = Field(
        None,
        description="Echoed back on the resulting change-feed entry so the plugin can tell "
        "its own initiated rename from an externally-detected one (null requestor "
        "== external change, mirroring VFS getRequestor() semantics).",
    )


class DeleteRequest(BaseModel):
    path: str
    requestor: str | None = None


class CreateChildRequest(BaseModel):
    parent_path: str
    name: str
    kind: NodeKind


class OperationStatus(str, Enum):
    ok = "ok"
    error = "error"
    unsupported = "unsupported"


class OperationResult(BaseModel):
    status: OperationStatus
    node: Node | None = None
    message: str | None = None


# --------------------------------------------------------------------------
# B) Change feed
# --------------------------------------------------------------------------
class ChangeKind(str, Enum):
    create = "create"
    delete = "delete"
    content = "content"  # body changed, identity/path unchanged
    rename = "rename"  # path changed, identity (stable_id) preserved
    move = "move"  # parent changed, identity preserved


class Change(BaseModel):
    """One remote-originated change since the caller's cursor. The plugin maps
    each to the corresponding VFileEvent and a VirtualFile.refresh() call."""

    kind: ChangeKind
    stable_id: int | None = Field(
        None,
        description="Identity key; ties a rename/move's old and new paths to one node.",
    )
    path: str = Field(..., description="New/current path of the affected node.")
    old_path: str | None = Field(
        None,
        description="Required for kind in (rename, move). The plugin uses (old_path -> path) "
        "to fire VFilePropertyChangeEvent(PROP_NAME)/VFileMoveEvent and keep the open "
        "editor's identity, instead of a delete+create that would invalidate it.",
    )
    revid: int | None = None
    requestor: str | None = Field(
        None,
        description="Null if externally originated; set if this echoes a plugin-initiated op.",
    )


class ChangesSinceResponse(BaseModel):
    """Cursor-paginated. The plugin's background poller calls this on an
    interval (the same poll discussed for local_modified_at, just over HTTP)
    and replays the changes into the platform on the EDT in a write action."""

    changes: list[Change]
    next_cursor: str = Field(
        ..., description="Opaque; pass back as `cursor` on the next poll."
    )
    has_more: bool = False
