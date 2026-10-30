package org.limepepper.lang.wikitext.search

import com.intellij.openapi.actionSystem.DataContext
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.platform.searchEverywhere.SeItem
import com.intellij.platform.searchEverywhere.SeItemsProvider
import com.intellij.platform.searchEverywhere.SeItemsProviderFactory
import com.intellij.platform.searchEverywhere.SeParams
import com.intellij.platform.searchEverywhere.presentations.SeBasicItemPresentationBuilder
import com.intellij.platform.searchEverywhere.presentations.SeItemPresentation
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Static probe of backend-independent search; deliberately does not enumerate or index files. */
@Suppress("UnstableApiUsage")
class WtStubSearchProviderFactory : SeItemsProviderFactory {
    override val id: String = "wikisource.stub"

    override suspend fun getItemsProvider(project: Project?, dataContext: DataContext): SeItemsProvider? =
        project?.let { WtStubSearchProvider(it) }
}

@Suppress("UnstableApiUsage")
private object StubPage : SeItem {
    const val PATH = "/mywikisource/en/Page/Stevenson-Persuasive Definitions-1938.pdf/13/@wikitext"

    override fun weight(): Int = 100

    override suspend fun presentation(): SeItemPresentation = SeBasicItemPresentationBuilder()
        .withText("aspirations — Stevenson, Persuasive Definitions, page 13 [static demo]")
        .withDescription("wikisource://$PATH")
        .build()
}

@Suppress("UnstableApiUsage")
private class WtStubSearchProvider(private val project: Project) : SeItemsProvider {
    override val id: String = "wikisource.stub"
    override val displayName: String = "Wikisource (static demo)"

    override suspend fun collectItems(params: SeParams, collector: SeItemsProvider.Collector) {
        val query = params.inputQuery.trim()
        if (query.isNotEmpty() &&
            ("aspirations".contains(query, ignoreCase = true) || StubPage.PATH.contains(query, ignoreCase = true))) {
            collector.put(StubPage)
        }
    }

    override suspend fun itemSelected(item: SeItem, modifiers: Int, searchText: String): Boolean {
        // Resolving an uncached VFS path can call the sidecar; keep it off the EDT.
        val file = withContext(Dispatchers.IO) {
            VirtualFileManager.getInstance().findFileByUrl("wikisource://${StubPage.PATH}")
        }
        ApplicationManager.getApplication().invokeLater {
            if (!project.isDisposed) {
                if (file != null && file.isValid) {
                    OpenFileDescriptor(project, file).navigate(true)
                } else {
                    Messages.showInfoMessage(project, "The static demo page is unavailable on the current backend.", "Wikisource Search")
                }
            }
        }
        return true
    }

    override suspend fun canBeShownInFindResults(): Boolean = false

    override fun dispose() {}
}
