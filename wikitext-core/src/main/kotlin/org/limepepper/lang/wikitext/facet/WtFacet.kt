package org.limepepper.lang.wikitext.facet

import com.intellij.facet.Facet
import com.intellij.facet.FacetType
import com.intellij.openapi.module.Module


/**
 * Demo Facet class. Everything is handled by the super class.
 */
class WtFacet(
    facetType: FacetType<*, *>,
    module: Module,
    name: String,
    configuration: WtFacetConfiguration,
    underlyingFacet: Facet<*>?
) : Facet<WtFacetConfiguration?>(facetType, module, name, configuration, underlyingFacet)