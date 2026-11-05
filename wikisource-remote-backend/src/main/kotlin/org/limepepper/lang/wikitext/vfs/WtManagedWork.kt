package org.limepepper.lang.wikitext.vfs

import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import java.io.IOException

/** A bounded set of canonical content addresses, not a second directory tree. */
data class WtManagedWork(
    val index: WtManagedAddress,
    val content: List<WtManagedAddress>,
    val databaseId: String? = null,
)

/** The @pages listing is a relationship view; consume its canonical paths directly. */
fun discoverManagedWork(backend: VfsBackend, seed: WtManagedAddress): WtManagedWork {
    val seedContentPath = WtPaths.aspectPath(WtPaths.nodePath(seed.backendPath), WtPaths.WIKITEXT)
    val seedStat = backend.stat(seedContentPath)
    if (!seedStat.exists) throw IOException("Work seed is unavailable: $seedContentPath")
    val indexPath = when (seedStat.contentModel) {
        "proofread-index" -> WtPaths.nodePath(seedContentPath)
        "proofread-page" -> backend.pageNav(seedContentPath).indexPath.let(WtPaths::nodePath)
        else -> throw IOException("Select an Index or a proofread Page to attach a work")
    }
    val indexContent = WtPaths.aspectPath(indexPath, WtPaths.WIKITEXT)
    val indexStat = if (seedContentPath == indexContent) seedStat else backend.stat(indexContent)
    if (!indexStat.exists || indexStat.contentModel != "proofread-index")
        throw IOException("Work Index is unavailable: $indexPath")
    val databaseId = indexStat.databaseId
    fun checkDatabase(id: String?) {
        if (id != databaseId || (backend.requiresDatabaseIdentity && id == null))
            throw IOException("Database changed while discovering work: $indexPath")
    }
    checkDatabase(seedStat.databaseId)
    val pages = backend.listChildren(WtPaths.aspectPath(indexPath, WtPaths.PAGES))
    checkDatabase(pages.databaseId)
    val paths = buildList {
        add(indexContent)
        pages.children.filter { it.kind == NodeKind.directory }.forEach {
            add(WtPaths.aspectPath(it.path, WtPaths.WIKITEXT))
        }
    }.distinct()
    val stats = backend.statBulk(paths)
    if (stats.map { it.path } != paths) throw IOException("Incomplete work metadata: $indexPath")
    stats.forEach { checkDatabase(it.databaseId) }
    if (stats.firstOrNull()?.let { it.exists && it.kind == NodeKind.file && it.contentModel == "proofread-index" } != true)
        throw IOException("Work Index disappeared or changed type: $indexPath")
    val content = stats.filter {
        it.exists && it.kind == NodeKind.file &&
            it.contentModel in setOf("proofread-index", "proofread-page", "wikitext")
    }.map { WtManagedAddress.fromPath(it.path) }
    return WtManagedWork(WtManagedAddress.fromPath(indexPath), content, databaseId)
}
