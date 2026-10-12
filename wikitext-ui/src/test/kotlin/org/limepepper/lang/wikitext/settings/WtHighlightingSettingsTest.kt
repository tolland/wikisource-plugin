package org.limepepper.lang.wikitext.settings

import com.intellij.testFramework.LightPlatformTestCase
import com.intellij.psi.PsiFileFactory
import com.intellij.lang.annotation.AnnotationSession
import com.intellij.codeInsight.daemon.impl.AnnotationHolderImpl
import org.limepepper.lang.wikitext.annotator.WtSentenceBandAnnotator
import org.limepepper.lang.wikitext.WtFileType
import org.limepepper.lang.wikitext.WtLanguage
import org.limepepper.lang.wikitext.parser.WtParserDefinition
import com.intellij.lang.LanguageParserDefinitions
import java.awt.Container
import javax.swing.JCheckBox
import javax.swing.JSlider

class WtHighlightingSettingsTest : LightPlatformTestCase() {
    private val parser = WtParserDefinition()
    private lateinit var original: WtHighlightingSettings.Options
    private val settings get() = WtHighlightingSettings.getInstance()

    override fun setUp() {
        super.setUp()
        LanguageParserDefinitions.INSTANCE.addExplicitExtension(WtLanguage, parser)
        original = settings.state
        settings.loadState(WtHighlightingSettings.Options())
    }

    override fun tearDown() {
        try {
            settings.loadState(original)
            LanguageParserDefinitions.INSTANCE.removeExplicitExtension(WtLanguage, parser)
        } finally {
            super.tearDown()
        }
    }

    fun testSameFileRespondsToStrengthAndDisableChanges() {
        val file = PsiFileFactory.getInstance(project).createFileFromText(
            "bands.wt", WtFileType, "First clause, second sentence.",
        )
        val annotator = WtSentenceBandAnnotator()
        fun backgrounds(): List<java.awt.Color> {
            val holder = AnnotationHolderImpl(AnnotationSession(file), false)
            holder.runAnnotatorWithContext(file, annotator)
            holder.assertAllAnnotationsCreated()
            return holder.mapNotNull { it.enforcedTextAttributes?.backgroundColor }
        }
        settings.update(WtHighlightingSettings.Options(bandStrength = 12))
        val quiet = backgrounds()
        assertEquals(2, quiet.size)
        settings.update(WtHighlightingSettings.Options(bandStrength = 100))
        val strong = backgrounds()
        assertEquals(2, strong.size)
        assertFalse(quiet == strong)
        settings.update(WtHighlightingSettings.Options(bandsEnabled = false, bandStrength = 100))
        assertEmpty(backgrounds())
        settings.update(WtHighlightingSettings.Options(bandStrength = 100))
        assertEquals(strong, backgrounds())
    }

    fun testReferenceHighlightingIsIndependentAndCanBeDisabled() {
        val file = PsiFileFactory.getInstance(project).createFileFromText(
            "refs.wt", WtFileType, "Body<ref>Note with ''italics''.</ref><ref name=\"note\"/>Tail",
        )
        val references = com.intellij.psi.util.PsiTreeUtil.findChildrenOfType(
            file, org.limepepper.lang.wikitext.psi.WtReferenceTag::class.java,
        ).toList()
        assertEquals(2, references.size)
        val annotator = org.limepepper.lang.wikitext.annotator.WtReferenceAnnotator()
        fun annotations(): AnnotationHolderImpl {
            val holder = AnnotationHolderImpl(AnnotationSession(file), false)
            references.forEach { ref ->
                holder.runAnnotatorWithContext(ref, annotator)
                ref.referenceBody?.let { holder.runAnnotatorWithContext(it, annotator) }
            }
            holder.assertAllAnnotationsCreated()
            return holder
        }
        settings.update(WtHighlightingSettings.Options(bandsEnabled = false))
        val annotations = annotations()
        assertEquals(4, annotations.size)
        assertEquals(1, annotations.count {
            it.textAttributes == org.limepepper.lang.wikitext.annotator.WtReferenceAnnotator.REFERENCE_CONTENT
        })
        settings.update(WtHighlightingSettings.Options(referencesEnabled = false))
        assertEmpty(annotations())
    }

    fun testPersistenceAndDisabledStrategy() {
        val state = WtHighlightingSettings.Options(false, 72)
        settings.loadState(state)
        state.bandStrength = 1
        assertEquals(72, settings.state.bandStrength)
        assertNull(settings.bandHighlighting())
        settings.loadState(WtHighlightingSettings.Options(bandStrength = 0))
        assertNull(settings.bandHighlighting())
        settings.loadState(WtHighlightingSettings.Options(bandStrength = 150))
        assertEquals(100, settings.state.bandStrength)
    }

    fun testSettingsApplyResetAndCancel() {
        val configurable = WtHighlightingConfigurable()
        try {
            val panel = configurable.createComponent()
            fun descendants(parent: Container): List<java.awt.Component> =
                parent.components.flatMap { listOf(it) + if (it is Container) descendants(it) else emptyList() }
            val children = descendants(panel as Container)
            val checkbox = children.filterIsInstance<JCheckBox>().first()
            val slider = children.filterIsInstance<JSlider>().single()
            val referenceBox = children.filterIsInstance<JCheckBox>().last()
            assertFalse(configurable.isModified)
            slider.value = 65
            checkbox.doClick()
            referenceBox.doClick()
            assertFalse(slider.isEnabled)
            assertTrue(configurable.isModified)
            assertEquals(WtHighlightingSettings.Options(), settings.state)
            configurable.apply()
            assertEquals(WtHighlightingSettings.Options(false, 65, false), settings.state)
            assertFalse(configurable.isModified)
            slider.value = 20
            configurable.reset()
            assertEquals(65, slider.value)
            assertFalse(configurable.isModified)
        } finally {
            configurable.disposeUIResources()
        }
    }
}
