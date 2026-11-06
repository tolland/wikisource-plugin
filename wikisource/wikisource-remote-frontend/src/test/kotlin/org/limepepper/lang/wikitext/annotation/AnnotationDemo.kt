package org.limepepper.lang.wikitext.annotation

import java.awt.BorderLayout
import java.awt.Color
import java.awt.Dimension
import java.awt.Font
import java.awt.image.BufferedImage
import java.io.File
import javax.imageio.ImageIO
import javax.swing.JButton
import javax.swing.JFrame
import javax.swing.JLabel
import javax.swing.JToolBar
import javax.swing.SwingUtilities

/**
 * Manual harness for [ImageAnnotationPane] — run this main() to exercise
 * draw/move/resize/delete on a synthetic "scan" (or a real image passed as
 * argv[0]) without booting the sandbox IDE:
 *
 *   left-drag: draw box | drag box: move | drag handle: resize
 *   Delete: remove selected | Escape: cancel/deselect
 *   wheel: zoom | middle-drag: pan
 *
 * Lives in test sources so it ships nowhere.
 */
object AnnotationDemo {
    @JvmStatic
    fun main(args: Array<String>) {
        val image = args.firstOrNull()?.let { ImageIO.read(File(it)) } ?: syntheticScan()
        SwingUtilities.invokeLater {
            val pane = ImageAnnotationPane()
            val status = JLabel(" ")

            pane.model.addListener(object : BoundingBoxModel.Listener {
                override fun boxesChanged() = refresh()

                override fun selectionChanged() = refresh()

                fun refresh() {
                    val sel = pane.model.selected
                    status.text = "${pane.model.boxes().size} boxes" + (sel?.let {
                        " | selected ${it.id.take(8)}: x=%.0f y=%.0f w=%.0f h=%.0f".format(it.x, it.y, it.width, it.height)
                    } ?: "")
                }
            })

            val toolbar = JToolBar().apply {
                isFloatable = false
                add(JButton("Zoom in").apply { addActionListener { pane.zoomBy(1.25) } })
                add(JButton("Zoom out").apply { addActionListener { pane.zoomBy(0.8) } })
                add(JButton("Fit").apply { addActionListener { pane.resetZoom() } })
                add(JButton("Delete").apply {
                    addActionListener { pane.model.selectedId?.let(pane.model::remove) }
                })
                add(status)
            }

            JFrame("ImageAnnotationPane demo").apply {
                defaultCloseOperation = JFrame.EXIT_ON_CLOSE
                layout = BorderLayout()
                add(toolbar, BorderLayout.NORTH)
                add(pane.component, BorderLayout.CENTER)
                size = Dimension(900, 1000)
                setLocationRelativeTo(null)
                isVisible = true
            }
            pane.showImage(image)
        }
    }

    /** A fake book page: ruled "text" lines and a figure box to annotate. */
    private fun syntheticScan(): BufferedImage {
        val w = 1200
        val h = 1600
        val img = BufferedImage(w, h, BufferedImage.TYPE_INT_RGB)
        val g = img.createGraphics()
        g.color = Color(0xF5, 0xF0, 0xE6)
        g.fillRect(0, 0, w, h)
        g.color = Color(0x60, 0x58, 0x50)
        g.font = Font(Font.SERIF, Font.PLAIN, 28)
        g.drawString("A SYNTHETIC PAGE SCAN", 380, 120)
        for (line in 0 until 40) {
            val y = 200 + line * 32
            g.fillRect(140, y, (760 + (line * 137) % 200), 3)
        }
        g.drawRect(200, 700, 500, 300)
        g.drawString("figure", 420, 860)
        g.dispose()
        return img
    }
}
