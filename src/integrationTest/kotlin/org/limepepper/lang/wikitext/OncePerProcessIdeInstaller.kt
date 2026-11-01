package org.limepepper.lang.wikitext

import com.intellij.ide.starter.ide.IdeInstaller
import com.intellij.ide.starter.ide.InstalledIde
import com.intellij.ide.starter.ide.installer.ExistingIdeInstaller
import com.intellij.ide.starter.models.IdeInfo
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.nio.file.Path

/** Share only the distribution copy; Starter still owns each scenario's mutable directories. */
internal class OncePerProcessIdeInstaller(private val source: Path) : IdeInstaller {
    private val mutex = Mutex()
    private var installation: Pair<String, InstalledIde>? = null

    override suspend fun install(ideInfo: IdeInfo): Pair<String, InstalledIde> = mutex.withLock {
        installation ?: ExistingIdeInstaller(source).install(ideInfo).also { installation = it }
    }
}
