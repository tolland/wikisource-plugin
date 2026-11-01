package org.limepepper.lang.wikitext.tool

import com.intellij.ide.util.treeView.AbstractTreeStructure
import com.intellij.ide.util.treeView.NodeDescriptor
import com.intellij.openapi.diagnostic.logger
import com.intellij.ui.tree.LeafState
import org.limepepper.lang.wikitext.vfs.WtPaths
import org.limepepper.lang.wikitext.vfs.WtAttachedWork
import org.limepepper.lang.wikitext.vfs.WtManagedAddress
import org.limepepper.lang.wikitext.vfs.WtWorkAttachments
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException

private val STRUCTURE_LOG = logger<WikisourceTreeStructure>()

/** Synthetic root element for the backend relationship browser. */
internal object WikisourceRootElement {
    override fun toString(): String = "Wikisource"
}

internal object AttachedWorksElement {
    override fun toString() = "Attached works"
}

internal data class AttachedWorkElement(val work: WtAttachedWork) {
    override fun toString() = work.name
}

internal data class AttachedContentElement(val parent: AttachedWorkElement, val address: WtManagedAddress) {
    override fun toString() = if (address.backendPath == WtPaths.aspectPath(parent.work.index.backendPath, WtPaths.WIKITEXT))
        "Index text" else "Page ${WtPaths.nodePath(address.backendPath).substringAfter("/Page/")}"
}

/** Leaf shown in place of children when the sidecar is unreachable. */
internal class BackendErrorElement(val parent: Any, val message: String) {
    override fun toString(): String = "⚠ $message"
}

/** Relationship view over API nodes; editor files are resolved separately by WtWikiFiles. */
internal class WikisourceTreeStructure(
    private val model: WikiBrowserModel,
    private val attachments: WtWorkAttachments,
) : AbstractTreeStructure() {

    override fun getRootElement(): Any = WikisourceRootElement

    override fun getChildElements(element: Any): Array<Any> = when (element) {
        WikisourceRootElement -> topLevelElements()
        AttachedWorksElement -> attachments.attachments().map(::AttachedWorkElement).toTypedArray()
        is AttachedWorkElement -> element.work.content.map { AttachedContentElement(element, it) }.toTypedArray()
        is WikiBrowserNode -> if (element.isDirectory) directoryChildren(element) else EMPTY
        else -> EMPTY
    }

    private fun topLevelElements(): Array<Any> = try {
        (listOf(AttachedWorksElement) + model.roots()).toTypedArray()
    } catch (e: VfsBackendException) {
        STRUCTURE_LOG.warn("VFS root load failed", e)
        arrayOf(AttachedWorksElement, BackendErrorElement(WikisourceRootElement, "sidecar unavailable (${e.message})"))
    }

    private fun directoryChildren(dir: WikiBrowserNode): Array<Any> = try {
        model.children(dir).filter(::isTreeElement).map { it as Any }.toTypedArray()
    } catch (e: VfsBackendException) {
        STRUCTURE_LOG.warn("VFS children load failed for ${dir.path}", e)
        arrayOf(BackendErrorElement(dir, e.message ?: "backend error"))
    }

    override fun getParentElement(element: Any): Any? = when (element) {
        WikisourceRootElement -> null
        AttachedWorksElement -> WikisourceRootElement
        is AttachedWorkElement -> AttachedWorksElement
        is AttachedContentElement -> element.parent
        is WikiBrowserNode -> element.parent ?: WikisourceRootElement
        is BackendErrorElement -> element.parent
        else -> null
    }

    override fun getLeafState(element: Any): LeafState = when (element) {
        WikisourceRootElement -> LeafState.NEVER
        AttachedWorksElement -> LeafState.NEVER
        is AttachedWorkElement -> if (element.work.content.isEmpty()) LeafState.ALWAYS else LeafState.NEVER
        // A title with no subpages (and no pages to list) has nothing to expand.
        is WikiBrowserNode -> if (element.isDirectory && element.hasChildren) LeafState.NEVER else LeafState.ALWAYS
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
internal fun isTreeElement(file: WikiBrowserNode): Boolean =
    file.isDirectory || WtPaths.aspectOf(file.path) == null

/** Tree label: the VFS name, except `@pages`, which reads as "Pages". */
internal fun treeLabel(file: WikiBrowserNode): String =
    if (WtPaths.aspectOf(file.path) == WtPaths.PAGES) "Pages" else file.name

internal class WikisourceNodeDescriptor(
    private val nodeElement: Any,
    parentDescriptor: NodeDescriptor<*>?,
) : NodeDescriptor<Any>(null, parentDescriptor) {

    init {
        myName = (nodeElement as? WikiBrowserNode)?.let(::treeLabel) ?: nodeElement.toString()
    }

    override fun update(): Boolean = false

    override fun getElement(): Any = nodeElement

    /**
     * TreeState identifies saved tree paths by this string (plus the
     * descriptor class). The VFS path is stable across refreshes, unlike
     * display labels, so expansion/selection restore matches reliably.
     */
    override fun toString(): String = when (nodeElement) {
        is WikiBrowserNode -> nodeElement.path
        is AttachedWorkElement -> nodeElement.work.id
        is AttachedContentElement -> "${nodeElement.parent.work.id}:${nodeElement.address.url}"
        else -> nodeElement.toString()
    }
}
