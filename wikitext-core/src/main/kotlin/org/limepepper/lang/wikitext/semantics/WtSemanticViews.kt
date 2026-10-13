package org.limepepper.lang.wikitext.semantics

import com.intellij.openapi.util.TextRange
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.psi.WtHtmlTag

/** A snapshot for one read/annotation pass. Keep smart pointers to source PSI across edits, not views. */
sealed interface WtSemanticView {
    val source: WtHtmlTag
}

/** Absolute source range excludes quotes, so navigation and future references can target the value. */
data class WtTagAttribute(val name: String, val value: String, val valueRange: TextRange)

class WtTagView internal constructor(
    val source: WtHtmlTag,
    val name: String,
    val attributes: List<WtTagAttribute>,
    val openingRange: TextRange,
    val closingRange: TextRange?,
    val bodyRange: TextRange?,
) {
    val isSelfClosing: Boolean get() = source.htmlTagSelfclose != null
    fun attribute(name: String): WtTagAttribute? = attributes.firstOrNull { it.name == name }
}

class WtReferenceView internal constructor(val tag: WtTagView) : WtSemanticView {
    override val source: WtHtmlTag get() = tag.source
    val name: String? get() = tag.attribute("name")?.value
    val group: String? get() = tag.attribute("group")?.value
    val isReuse: Boolean get() = tag.isSelfClosing
    val bodyRange: TextRange? get() = tag.bodyRange
}

enum class WtSectionBoundary { BEGIN, END }

/** A marker is a source element; any span between markers belongs to a separate analysis. */
class WtSectionMarkerView internal constructor(
    val tag: WtTagView,
    val boundary: WtSectionBoundary,
    val label: WtTagAttribute,
) : WtSemanticView {
    override val source: WtHtmlTag get() = tag.source
    val name: String get() = label.value
}

object WtSemanticViews {
    // Tolerant source extraction, not an XML parser or extension-specific validity check.
    private val attributePattern = Regex("""([^\s=/>]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")

    fun tag(element: PsiElement): WtTagView? {
        val source = element as? WtHtmlTag ?: return null
        val opening = source.htmlTagOpen ?: source.htmlTagSelfclose ?: return null
        val text = opening.text
        val name = text.drop(1).takeWhile { it.isLetterOrDigit() || it == '-' || it == ':' }
        if (name.isEmpty()) return null
        // Exclude the final '/>' from unquoted attribute values such as <section begin=p-8/>.
        val attributesEnd = text.length - if (source.htmlTagSelfclose != null) 2 else 1
        val attributesText = text.substring(1 + name.length, attributesEnd.coerceAtLeast(1 + name.length))
        val attributesOffset = opening.textRange.startOffset + 1 + name.length
        val attributes = attributePattern.findAll(attributesText).map { match ->
            val value = (2..4).firstNotNullOf { match.groups[it] }
            WtTagAttribute(
                match.groupValues[1], value.value,
                TextRange(value.range.first, value.range.last + 1).shiftRight(attributesOffset),
            )
        }.toList()
        val closing = source.htmlTagClose?.textRange
        val body = if (source.htmlTagSelfclose != null) null else TextRange(
            opening.textRange.endOffset, closing?.startOffset ?: source.textRange.endOffset,
        )
        return WtTagView(source, name, attributes, opening.textRange, closing, body)
    }

    fun of(element: PsiElement): WtSemanticView? {
        val tag = tag(element) ?: return null
        return when {
            tag.name.equals("ref", ignoreCase = true) -> WtReferenceView(tag)
            tag.name.equals("section", ignoreCase = true) && tag.isSelfClosing -> {
                val begin = tag.attribute("begin")
                val end = tag.attribute("end")
                when {
                    begin != null && end == null -> WtSectionMarkerView(tag, WtSectionBoundary.BEGIN, begin)
                    end != null && begin == null -> WtSectionMarkerView(tag, WtSectionBoundary.END, end)
                    else -> null
                }
            }
            else -> null
        }
    }

    fun reference(element: PsiElement): WtReferenceView? = of(element) as? WtReferenceView
}
