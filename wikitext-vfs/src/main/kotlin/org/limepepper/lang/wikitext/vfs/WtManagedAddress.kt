package org.limepepper.lang.wikitext.vfs

/** Address boundary for managed Wikisource files. */
@JvmInline
value class WtManagedAddress private constructor(val backendPath: String) {
    val url: String get() = "$PROTOCOL://$backendPath"

    val rootPath: String get() = "/"
    val isFamilyContainer: Boolean get() = backendPath != "/" && '/' !in backendPath.trim('/')
    val familyName: String get() = backendPath.trim('/').substringBefore('/')

    companion object {
        const val PROTOCOL = "wikisource-wtbot"

        fun fromPath(path: String): WtManagedAddress {
            require(path.startsWith('/')) { "Expected an absolute wtbot VFS path: $path" }
            return WtManagedAddress(path)
        }

        fun fromUrl(url: String): WtManagedAddress {
            val prefix = "$PROTOCOL://"
            require(url.startsWith(prefix)) { "Not a managed wtbot URL: $url" }
            return fromPath(url.removePrefix(prefix))
        }
    }
}
