package org.limepepper.lang.wikitext.facet

import com.intellij.facet.Facet
import com.intellij.facet.FacetType
import com.intellij.facet.FacetTypeId
import com.intellij.openapi.module.Module
import com.intellij.openapi.module.ModuleType


import org.limepepper.lang.wikitext.icons.SdkIcons
import javax.swing.Icon

/**
 * Defines the type, id, and name of the [WtFacet].
 * Provides creation of [WtFacet] and associated Configuration.
 * Allows application of this facet to all [ModuleType] instances.
 */
internal class WtFacetType :
    FacetType<WtFacet?, WtFacetConfiguration?>(DEMO_FACET_TYPE_ID, FACET_ID, FACET_NAME) {
    override fun createDefaultConfiguration(): WtFacetConfiguration {
        return WtFacetConfiguration()
    }

    override fun createFacet(
        module: Module,
        s: String,
        configuration: WtFacetConfiguration,
        facet: Facet<*>?
    ): WtFacet {
        return WtFacet(this, module, s, configuration, facet)
    }

    override fun isSuitableModuleType(type: ModuleType<*>?): Boolean {
        return true
    }

    override fun getIcon(): Icon {
        return SdkIcons.Sdk_default_icon
    }

    companion object {
        const val FACET_ID: String = "DEMO_FACET_ID"
        const val FACET_NAME: String = "SDK Facet"
        val DEMO_FACET_TYPE_ID: FacetTypeId<WtFacet?> = FacetTypeId<WtFacet?>(FACET_ID)
    }
}
