package org.limepepper.lang.wikitext.tool

import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.content.ContentFactory

class MyToolWindowFactory : ToolWindowFactory {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val contentFactory = ContentFactory.getInstance()
        toolWindow.contentManager.addContent(
            contentFactory.createContent(
                WikisourceBrowserToolWindowTab(project, toolWindow).createComponent(),
                "Browser",
                false,
            ),
        )
        toolWindow.contentManager.addContent(
            contentFactory.createContent(
                WikisourceDebugToolWindowTab().createComponent(),
                "Debug",
                false,
            ),
        )
    }
}
