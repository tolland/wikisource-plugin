package org.limepepper.lang.wikitext.vfs.backend

/**
 * Abstraction over the wtbot FastAPI VFS endpoints.
 * Implementations: [HttpVfsBackend] (real), [FakeVfsBackend] (tests/offline).
 */
interface VfsBackend {
    /** Returns stat for any path; [StatResult.exists] is false for unknown paths. */
    fun stat(path: String): StatResult

    /** Lists the children of a directory path. */
    fun listChildren(path: String): ListChildrenResult

    /** Reads raw content of a file path. */
    fun readContent(path: String): ContentResult

    /**
     * Writes the full new content of a file path, replacing its body.
     * [baseRevid] is the revid the edit started from — a server-side mismatch
     * against the current cached revid comes back as [WriteStatus.conflict],
     * not an exception.
     */
    fun writeContent(
        path: String,
        contentBase64: String,
        baseRevid: Long?,
        comment: String? = null,
    ): WriteResult
}
