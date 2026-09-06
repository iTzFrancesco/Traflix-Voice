package it.traflix.voice

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToInt

/** Keeps native results visible to the same Hub statistics and Groq quota views. */
class VoiceMetricsStore(context: Context) {
  private val appContext = context.applicationContext
  private val statsFile = File(appContext.dataDir, "stats.json")
  private val usageFile = File(appContext.dataDir, "groq_usage.json")
  private val lockFile = File(appContext.dataDir, "metrics.lock")

  fun record(text: String, durationMs: Long) {
    val durationMinutes = (durationMs.coerceAtLeast(0L) / 60_000f)
    val words = text.trim().split(Regex("\\s+")).count { it.isNotEmpty() }
    if (words == 0 || durationMinutes <= 0f) return

    withFileLock {
      val stats = readObject(statsFile)
      val totalWords = stats.optInt("total_words", 0) + words
      val totalTime = stats.optDouble("total_time", 0.0).toFloat() + durationMinutes
      val averageWpm = if (totalTime > 0f) (totalWords / totalTime).roundToInt() else 0
      atomicWrite(
        statsFile,
        JSONObject()
          .put("total_words", totalWords)
          .put("avg_wpm", averageWpm)
          .put("total_time", totalTime),
      )

      val now = Date()
      val date = DATE_FORMAT.format(now)
      val currentHour = System.currentTimeMillis() / HOUR_MS
      val usage = readObject(usageFile)
      val sameDate = usage.optString("date") == date
      val storedHour = usage.optLong("hour_key", -1L)
      val dailySeconds = if (sameDate) usage.optDouble("audio_seconds", 0.0) else 0.0
      val hourlySeconds = if (sameDate && storedHour == currentHour) {
        usage.optDouble("audioSecondsHourly", 0.0)
      } else {
        0.0
      }
      val nextHour = (currentHour + 1L) * HOUR_MS
      atomicWrite(
        usageFile,
        JSONObject()
          .put("date", date)
          .put("audio_seconds", dailySeconds + durationMs / 1000.0)
          .put("audioSecondsHourly", hourlySeconds + durationMs / 1000.0)
          .put("hourly_reset", TIME_FORMAT.format(Date(nextHour)))
          .put("hour_key", currentHour),
      )
    }
  }

  private fun readObject(file: File): JSONObject {
    if (!file.exists()) return JSONObject()
    return runCatching { JSONObject(file.readText()) }.getOrElse { JSONObject() }
  }

  private fun atomicWrite(file: File, value: JSONObject) {
    file.parentFile?.mkdirs()
    val temporary = File(file.parentFile, "${file.name}.tmp")
    temporary.writeText(value.toString())
    if (!temporary.renameTo(file)) {
      temporary.delete()
      throw IllegalStateException("Impossibile salvare le statistiche")
    }
  }

  private fun <T> withFileLock(block: () -> T): T {
    lockFile.parentFile?.mkdirs()
    return RandomAccessFile(lockFile, "rw").use { accessFile ->
      accessFile.channel.lock().use { block() }
    }
  }

  private companion object {
    const val HOUR_MS = 3_600_000L
    val DATE_FORMAT = SimpleDateFormat("yyyy-MM-dd", Locale.ITALY)
    val TIME_FORMAT = SimpleDateFormat("HH:mm", Locale.ITALY)
  }
}
