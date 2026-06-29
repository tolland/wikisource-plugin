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
}
