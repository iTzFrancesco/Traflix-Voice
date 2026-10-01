package it.traflix.voice

import android.content.Context
import java.io.File

/** Coordinates Hub clears with native IME and accessibility persistence. */
class VoiceDataResetStore(context: Context) {
  private val dataDirectory = context.applicationContext.dataDir

  fun clearHistoryAndStats() = clearHistoryAndStats(dataDirectory)

  companion object {
    internal fun clearHistoryAndStats(
      dataDirectory: File,
      replaceFile: (File, File) -> Unit = VoiceDataFileLocks::replaceFileAtomically,
    ) {
      dataDirectory.mkdirs()
      val historyLock = File(dataDirectory, "history.lock")
      val metricsLock = File(dataDirectory, "metrics.lock")

      VoiceDataFileLocks.withLockFile(historyLock) {
        VoiceDataFileLocks.withLockFile(metricsLock) {
          val historyFile = File(dataDirectory, "history.json")
          if (historyFile.exists() && !historyFile.delete()) {
            throw IllegalStateException("Impossibile cancellare la cronologia")
          }
          atomicWrite(
            File(dataDirectory, "stats.json"),
            "{\"total_words\":0,\"avg_wpm\":0,\"total_time\":0.0}",
            replaceFile,
          )
        }
      }
    }

    private fun atomicWrite(file: File, contents: String, replaceFile: (File, File) -> Unit) {
      val temporary = File(file.parentFile, "${file.name}.tmp")
      temporary.writeText(contents)
      try {
        replaceFile(temporary, file)
      } catch (error: Exception) {
        temporary.delete()
        throw IllegalStateException("Impossibile azzerare le statistiche", error)
      }
    }
  }
}
