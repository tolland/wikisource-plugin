package org.limepepper.lang.wikitext.tool

import com.intellij.ide.util.treeView.AbstractTreeStructure
import com.intellij.ide.util.treeView.NodeDescriptor
import com.intellij.openapi.diagnostic.logger
import com.intellij.ui.tree.LeafState
import org.limepepper.lang.wikitext.vfs.WtPaths
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.WtVirtualFileSystem
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

private val STRUCTURE_LOG = logger<WikisourceTreeStructure>()

/** Synthetic root element for the whole `wikisource://` tree. */
internal object WikisourceRootElement {
    override fun toString(): String = "wikisource://"
}

/** Leaf shown in place of children when the sidecar is unreachable. */
internal class BackendErrorElement(val parent: Any, val message: String) {
    override fun toString(): String = "⚠ $message"
}

/**
 * [AbstractTreeStructure] over the `wikisource://` VFS for the browser tool
 * window. Elements are the path-cached [WtVirtualFile] instances themselves
 * (plus [WikisourceRootElement] and [BackendErrorElement]), so element
 * equality — and with it AsyncTreeModel's expansion/selection preservation
 * across invalidations — falls out of [WtVirtualFileSystem]'s identity cache.
 *
 * A title is a directory node that lists its aspect files (`@wikitext`,
 * `@props`) next to its subpages. The tree shows only the titles and the
 * `@pages` container: aspects are what a node *offers* (double-click opens the
 * default one, the context menu the rest), not part of the hierarchy a reader
 * browses. See [isTreeElement].
 *
 * Child computation blocks on the sidecar; StructureTreeModel only calls it
 * on its background invoker thread, never on the EDT.
 */
internal class WikisourceTreeStructure(
    private val fs: WtVirtualFileSystem?,
) : AbstractTreeStructure() {

    override fun getRootElement(): Any = WikisourceRootElement

    override fun getChildElements(element: Any): Array<Any> = when (element) {
        WikisourceRootElement -> topLevelElements()
        is WtVirtualFile -> if (element.isDirectory) directoryChildren(element) else EMPTY
        else -> EMPTY
    }

    private fun topLevelElements(): Array<Any> {
        val fileSystem = fs
            ?: return arrayOf(BackendErrorElement(WikisourceRootElement, "wikisource filesystem not registered"))
        return try {
            WtVfsService.instance.backend.listChildren("/").children.map { child ->
                fileSystem.getOrCreate(
                    path = child.path,
                    name = child.name,
                    isDir = child.kind == NodeKind.directory,
                    stableId = child.stableId,
                    revid = child.revid,
                    contentModel = child.contentModel,
                    qualityLevel = child.qualityLevel,
                    dirty = child.dirty,
                    hasReferenceImage = child.hasReferenceImage,
                    placeholder = child.placeholder,
                    length = child.length,
                    timestamp = child.timestamp,
                    hasChildren = child.hasChildren,
                    aspects = child.aspects,
                ) as Any
            }.toTypedArray()
        } catch (e: VfsBackendException) {
            STRUCTURE_LOG.warn("VFS root load failed", e)
            arrayOf(BackendErrorElement(WikisourceRootElement, "sidecar not running (${e.message})"))
        }
    }

    private fun directoryChildren(dir: WtVirtualFile): Array<Any> = try {
        dir.children.filter { isTreeElement(it as WtVirtualFile) }.map { it as Any }.toTypedArray()
    } catch (e: VfsBackendException) {
        STRUCTURE_LOG.warn("VFS children load failed for ${dir.path}", e)
        arrayOf(BackendErrorElement(dir, e.message ?: "backend error"))
    }

    override fun getParentElement(element: Any): Any? = when (element) {
        WikisourceRootElement -> null
        is WtVirtualFile -> element.parent ?: WikisourceRootElement
        is BackendErrorElement -> element.parent
        else -> null
    }

    override fun getLeafState(element: Any): LeafState = when (element) {
        WikisourceRootElement -> LeafState.NEVER
        // A title with no subpages (and no pages to list) has nothing to expand.
        is WtVirtualFile -> if (element.isDirectory && element.hasChildren) LeafState.NEVER else LeafState.ALWAYS
        else -> LeafState.ALWAYS
    }

    override fun createDescriptor(element: Any, parentDescriptor: NodeDescriptor<*>?): NodeDescriptor<*> =
        WikisourceNodeDescriptor(element, parentDescriptor)

    override fun commit() {}
    override fun hasSomethingToCommit(): Boolean = false

    private companion object {
        private val EMPTY: Array<Any> = emptyArray()
    }
}

/**
 * Whether a child of a title node belongs in the tree: titles and the `@pages`
 * container do; aspect files do not.
 */
internal fun isTreeElement(file: WtVirtualFile): Boolean =
    file.isDirectory || WtPaths.aspectOf(file.path) == null

/** Tree label: the VFS name, except `@pages`, which reads as "Pages". */
internal fun treeLabel(file: WtVirtualFile): String =
    if (WtPaths.aspectOf(file.path) == WtPaths.PAGES) "Pages" else file.name

internal class WikisourceNodeDescriptor(
    private val nodeElement: Any,
    parentDescriptor: NodeDescriptor<*>?,
) : NodeDescriptor<Any>(null, parentDescriptor) {

    init {
        myName = (nodeElement as? WtVirtualFile)?.let(::treeLabel) ?: nodeElement.toString()
    }

    override fun update(): Boolean = false

    override fun getElement(): Any = nodeElement

    /**
     * TreeState identifies saved tree paths by this string (plus the
     * descriptor class). The VFS path is stable across refreshes, unlike
     * display labels, so expansion/selection restore matches reliably.
     */
    override fun toString(): String = when (nodeElement) {
        is WtVirtualFile -> nodeElement.path
        else -> nodeElement.toString()
    }
}
