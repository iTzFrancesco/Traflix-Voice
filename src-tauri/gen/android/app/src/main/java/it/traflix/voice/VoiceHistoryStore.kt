package it.traflix.voice

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Uses the same app-private history.json schema as the Tauri Hub. */
class VoiceHistoryStore(context: Context) {
  private val appContext = context.applicationContext
  private val historyFile = File(appContext.dataDir, "history.json")
  private val lockFile = File(appContext.dataDir, "history.lock")

  fun append(text: String) {
    val trimmed = text.trim()
    if (trimmed.isEmpty()) return
    withFileLock {
      val entries = readEntries()
      entries.put(
        JSONObject()
          .put("text", trimmed)
          .put("timestamp", TIMESTAMP_FORMAT.format(Date()))
          .put("word_count", trimmed.split(Regex("\\s+")).size),
      )
      while (entries.length() > MAX_ENTRIES) entries.remove(0)
      atomicWrite(entries.toString())
    }
  }

  fun clear() {
    withFileLock {
      if (historyFile.exists()) historyFile.delete()
    }
  }

  private fun readEntries(): JSONArray {
    if (!historyFile.exists()) return JSONArray()
    return runCatching { JSONArray(historyFile.readText()) }.getOrElse { JSONArray() }
  }

  private fun atomicWrite(contents: String) {
    historyFile.parentFile?.mkdirs()
    val temporary = File(historyFile.parentFile, "${historyFile.name}.tmp")
    temporary.writeText(contents)
    if (!temporary.renameTo(historyFile)) {
      temporary.delete()
      throw IllegalStateException("Impossibile salvare la cronologia")
    }
  }

  private fun <T> withFileLock(block: () -> T): T {
    lockFile.parentFile?.mkdirs()
    return RandomAccessFile(lockFile, "rw").use { accessFile ->
      accessFile.channel.lock().use { block() }
    }
  }

  private companion object {
    const val MAX_ENTRIES = 50
    val TIMESTAMP_FORMAT = SimpleDateFormat("dd/MM/yyyy, HH:mm:ss", Locale.ITALY)
  }
}
