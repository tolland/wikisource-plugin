"""Typed domain errors for the VFS service layer.

The service raises these instead of `fastapi.HTTPException` so it can be
exercised in tests (and reused behind other transports) without an HTTP
stack; `wtbot.api.vfs` maps each to a status code at the boundary.
"""


class VfsError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(VfsError):
    """Path does not resolve to any node."""


class NotADirectory(VfsError):
    """list_children() on a leaf."""


class NotAFile(VfsError):
    """read/write on a directory or other non-content node."""


class NotDeletable(VfsError):
    """delete on a synthetic node (root, site, `Pages`, `wikitext`) -- there is
    no title behind it to remove."""


class DeleteBlocked(VfsError):
    """The delete would lose local edits or strand rows that reference the
    title; the message says which."""
