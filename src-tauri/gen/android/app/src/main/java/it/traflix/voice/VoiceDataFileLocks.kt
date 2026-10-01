package it.traflix.voice

import android.system.Os
import java.io.File
import java.io.RandomAccessFile
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** Serializes app-process threads before acquiring cross-process file locks. */
object VoiceDataFileLocks {
  private val processLocks = ConcurrentHashMap<String, ReentrantLock>()

  fun <T> withLockFile(lockFile: File, block: () -> T): T {
    lockFile.parentFile?.mkdirs()
    val processLock = processLocks.computeIfAbsent(lockFile.canonicalPath) { ReentrantLock() }
    return processLock.withLock {
      RandomAccessFile(lockFile, "rw").use { accessFile ->
        accessFile.channel.lock().use { block() }
      }
    }
  }

  fun replaceFileAtomically(source: File, target: File) {
    Os.rename(source.absolutePath, target.absolutePath)
  }
}
