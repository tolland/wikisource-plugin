package org.limepepper.lang.wikitext.vfs

import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import java.io.IOException

/** A bounded set of canonical content addresses, not a second directory tree. */
data class WtManagedWork(
    val index: WtManagedAddress,
    val content: List<WtManagedAddress>,
)

/** The @pages listing is a relationship view; consume its canonical paths directly. */
fun discoverManagedWork(backend: VfsBackend, seed: WtManagedAddress): WtManagedWork {
    val seedContentPath = WtPaths.aspectPath(WtPaths.nodePath(seed.backendPath), WtPaths.WIKITEXT)
    val seedStat = backend.stat(seedContentPath)
    if (!seedStat.exists) throw IOException("Work seed is unavailable: $seedContentPath")
    val indexPath = when (seedStat.contentModel) {
        "proofread-index" -> WtPaths.nodePath(seedContentPath)
        "proofread-page" -> backend.pageNav(seedContentPath).indexPath.let(WtPaths::nodePath)
        else -> throw IOException("Select an Index or a proofread Page to search a work")
    }
    val pages = backend.listChildren(WtPaths.aspectPath(indexPath, WtPaths.PAGES))
    val paths = buildList {
        add(WtPaths.aspectPath(indexPath, WtPaths.WIKITEXT))
        pages.children.filter { it.kind == NodeKind.directory }.forEach {
            add(WtPaths.aspectPath(it.path, WtPaths.WIKITEXT))
        }
    }.distinct()
    val content = backend.statBulk(paths).filter {
        it.exists && it.kind == NodeKind.file &&
            it.contentModel in setOf("proofread-index", "proofread-page", "wikitext")
    }.map { WtManagedAddress.fromPath(it.path) }
    return WtManagedWork(WtManagedAddress.fromPath(indexPath), content)
}
