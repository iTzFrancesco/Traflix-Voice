package it.traflix.voice

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
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
    try {
      VoiceDataFileLocks.replaceFileAtomically(temporary, historyFile)
    } catch (error: Exception) {
      temporary.delete()
      throw IllegalStateException("Impossibile salvare la cronologia", error)
    }
  }

  fun delete(index: Int, text: String, timestamp: String, wordCount: Int): Boolean =
    withFileLock {
      if (!historyFile.exists()) return@withFileLock false
      val entries = readEntries()
      if (index < 0) return@withFileLock false
      val storageIndex = entries.length() - index - 1
      val matches: (Int) -> Boolean = { candidateIndex ->
        val candidate = entries.optJSONObject(candidateIndex)
        candidate != null &&
          candidate.optString("text") == text &&
          candidate.optString("timestamp") == timestamp &&
          candidate.optInt("word_count") == wordCount
      }
      val removeIndex = when {
        storageIndex in 0 until entries.length() && matches(storageIndex) -> storageIndex
        else -> (entries.length() - 1 downTo 0).firstOrNull(matches) ?: -1
      }
      if (removeIndex < 0) return@withFileLock false
      entries.remove(removeIndex)
      atomicWrite(entries.toString())
      true
    }

  private fun <T> withFileLock(block: () -> T): T {
    return VoiceDataFileLocks.withLockFile(lockFile, block)
  }

  private companion object {
    const val MAX_ENTRIES = 50
    val TIMESTAMP_FORMAT = SimpleDateFormat("dd/MM/yyyy, HH:mm:ss", Locale.ITALY)
  }
}
