package org.limepepper.lang.wikitext.vfs

import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import java.io.IOException

/** Metadata-only selection. Never open a default body to decide whether it is indexable. */
fun indexableWorkContent(backend: VfsBackend, work: WtAttachedWork): List<WtManagedAddress> {
    if (backend.cacheIdentity != work.connection) throw IOException("Work belongs to another backend")
    val paths = work.content.map { it.backendPath }
    val stats = backend.statBulk(paths)
    if (stats.map { it.path } != paths) throw IOException("Incomplete work metadata")
    if (stats.any { it.databaseId != work.databaseId || (backend.requiresDatabaseIdentity && it.databaseId == null) })
        throw IOException("Work belongs to another database")
    val indexPath = WtPaths.aspectPath(work.index.backendPath, WtPaths.WIKITEXT)
    if (stats.none { it.path == indexPath && it.exists && it.contentModel == "proofread-index" })
        throw IOException("Attached Index is unavailable")
    return stats.filter {
        it.exists && it.kind == NodeKind.file &&
            it.contentModel in setOf("proofread-index", "proofread-page", "wikitext") &&
            (!it.placeholder || it.dirty)
    }.map { WtManagedAddress.fromPath(it.path) }
}
