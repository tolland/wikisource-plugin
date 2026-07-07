package org.limepepper.lang.wikitext.vfs.backend

/**
 * Minimal JSON object reader backed by a regex-based field extractor.
 *
 * Covers the subset of JSON returned by the VFS endpoints:
 *   - top-level string/number/bool/null scalar fields
 *   - a single level of object arrays
 *
 * Not a general-purpose parser — does not handle nested objects beyond one
 * level or escaped characters beyond \" inside strings.
 * Replace with kotlinx.serialization if schemas grow complex.
 */
internal class JsonReader(private val json: String) {

    fun string(key: String): String =
        stringOrNull(key) ?: error("missing string field '$key' in JSON")

    fun stringOrNull(key: String): String? {
        // Hand-rolled scan instead of a `(?:[^"\\]|\\.)*`-style regex: Java's
        // regex engine recurses per repetition, and long values (e.g. a
        // base64-encoded page body) blow the stack with that pattern.
        val keyToken = "\"$key\""
        var i = json.indexOf(keyToken)
        if (i == -1) return null
        i += keyToken.length
        while (i < json.length && json[i].isWhitespace()) i++
        if (i >= json.length || json[i] != ':') return null
        i++
        while (i < json.length && json[i].isWhitespace()) i++
        if (i >= json.length || json[i] != '"') return null
        i++
        val sb = StringBuilder()
        while (i < json.length && json[i] != '"') {
            if (json[i] == '\\' && i + 1 < json.length) {
                sb.append(json[i]).append(json[i + 1])
                i += 2
            } else {
                sb.append(json[i])
                i++
            }
        }
        return sb.toString()
    }

    fun bool(key: String): Boolean =
        boolOrDefault(key, false).also {
            check(Regex(""""$key"\s*:\s*(true|false)""").containsMatchIn(json)) {
                "missing bool field '$key'"
            }
        }

    fun boolOrDefault(key: String, default: Boolean): Boolean {
        val m = Regex(""""$key"\s*:\s*(true|false)""").find(json) ?: return default
        return m.groupValues[1] == "true"
    }

    fun longOrNull(key: String): Long? {
        val m = Regex(""""$key"\s*:\s*(\d+)""").find(json) ?: return null
        return m.groupValues[1].toLong()
    }

    /**
     * Extracts a nested JSON object value for [key] as its own [JsonReader],
     * or null when the key is absent or its value is `null`. The returned
     * reader sees only the nested object's text, so its field keys cannot
     * collide with same-named keys elsewhere in the parent.
     */
    fun objectOrNull(key: String): JsonReader? {
        val keyToken = "\"$key\""
        var i = json.indexOf(keyToken)
        if (i == -1) return null
        i += keyToken.length
        while (i < json.length && json[i].isWhitespace()) i++
        if (i >= json.length || json[i] != ':') return null
        i++
        while (i < json.length && json[i].isWhitespace()) i++
        if (i >= json.length || json[i] != '{') return null
        val start = i
        var depth = 0
        var inString = false
        while (i < json.length) {
            val c = json[i]
            when {
                inString -> when (c) {
                    '\\' -> i++ // skip the escaped char
                    '"' -> inString = false
                }
                c == '"' -> inString = true
                c == '{' -> depth++
                c == '}' -> {
                    depth--
                    if (depth == 0) return JsonReader(json.substring(start, i + 1))
                }
            }
            i++
        }
        return null
    }

    /**
     * Extracts a JSON array value for [key] and maps each element object
     * through [block]. Objects must be flat (no nested arrays/objects).
     */
    fun <T> array(key: String, block: (JsonReader) -> T): List<T> {
        // Find the array bracket after the key
        val keyIdx = json.indexOf(""""$key"""") + key.length + 2
        val arrStart = json.indexOf('[', keyIdx)
        if (arrStart == -1) return emptyList()

        val items = mutableListOf<T>()
        var depth = 0
        var objStart = -1
        var i = arrStart

        while (i < json.length) {
            when (json[i]) {
                '[' -> depth++
                '{' -> { if (depth == 1) objStart = i; depth++ }
                '}' -> {
                    depth--
                    if (depth == 1 && objStart != -1) {
                        items += block(JsonReader(json.substring(objStart, i + 1)))
                        objStart = -1
                    }
                }
                ']' -> { depth--; if (depth == 0) break }
            }
            i++
        }
        return items
    }
}
