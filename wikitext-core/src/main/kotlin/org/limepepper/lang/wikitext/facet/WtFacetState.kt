package org.limepepper.lang.wikitext.facet

/**
 * A simple class to store state for the [DemoFacet].
 * In this case it is just a string containing a path to an SDK.
 */
class WtFacetState internal constructor() {
    var myPathToSdk: String = DEMO_FACET_INIT_PATH

    var wtFacetState: String
        get() = myPathToSdk
        set(newPath) {
            myPathToSdk = newPath
        }

    companion object {
        const val DEMO_FACET_INIT_PATH: String = ""
    }
}