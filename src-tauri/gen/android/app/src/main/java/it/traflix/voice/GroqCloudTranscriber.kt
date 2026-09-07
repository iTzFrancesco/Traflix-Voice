package it.traflix.voice

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.CancellationException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import org.json.JSONObject

/** Direct Groq-only prototype client; production should use the Traflix gateway. */
class GroqCloudTranscriber(context: Context) {
  interface Listener {
    fun onSuccess(text: String)
    fun onFailure(message: String)
  }

  private val appContext = context.applicationContext
  private val mainHandler = Handler(Looper.getMainLooper())
  private val executor: ExecutorService = Executors.newSingleThreadExecutor {
    Thread(it, "traflix-voice-cloud").apply { isDaemon = true }
  }
  private val requestLock = Any()
  private val requestGeneration = AtomicLong(0L)
  private val pendingFiles = linkedSetOf<File>()
  @Volatile private var activeConnection: HttpURLConnection? = null

  fun transcribe(file: File, language: String, listener: Listener) {
    cancel()
    val generation = requestGeneration.incrementAndGet()
    val queuedAt = SystemClock.elapsedRealtime()
    synchronized(requestLock) { pendingFiles.add(file) }
    Log.i(TAG, "transcription queued bytes=${file.length()} language=$language")
    executor.execute {
      if (!isCurrent(generation)) {
        forgetFile(file)
        file.delete()
        return@execute
      }
      Log.d(
        TAG,
        "transcription request started queueWaitMs=${SystemClock.elapsedRealtime() - queuedAt}",
      )
      val result = runCatching { request(file, language, generation) }
      if (!isCurrent(generation)) {
        forgetFile(file)
        file.delete()
        return@execute
      }
      mainHandler.post {
        if (!isCurrent(generation)) {
          forgetFile(file)
          file.delete()
          return@post
        }
        try {
          result.fold(
            onSuccess = { text ->
              Log.i(TAG, "transcription request succeeded textChars=${text.length}")
              listener.onSuccess(text)
            },
            onFailure = { error ->
              Log.e(TAG, "transcription request failed", error)
              listener.onFailure(error.message ?: "Errore Groq Cloud")
            },
          )
        } finally {
          forgetFile(file)
        }
      }
    }
  }

  /** Cancels the active request and invalidates callbacks waiting on the main thread. */
  fun cancel() {
    val connection: HttpURLConnection?
    val files: List<File>
    synchronized(requestLock) {
      requestGeneration.incrementAndGet()
      connection = activeConnection
      activeConnection = null
      files = pendingFiles.toList()
      pendingFiles.clear()
    }
    connection?.disconnect()
    files.forEach { file -> runCatching { file.delete() } }
    if (connection != null || files.isNotEmpty()) {
      Log.i(TAG, "transcription cancelled files=${files.size} connection=${connection != null}")
    }
  }

  fun shutdown() {
    cancel()
    executor.shutdownNow()
  }

  private fun request(file: File, language: String, generation: Long): String {
    ensureCurrent(generation)
    val apiKey = VoiceSecretsStore(appContext).groqApiKey()
      ?: throw IllegalStateException("Configura la chiave Groq Cloud nelle impostazioni")
    val fileBytes = file.length()
    if (!file.exists() || fileBytes <= WAV_HEADER_BYTES) {
      throw IllegalStateException("Registrazione vuota")
    }

    val boundary = "----TraflixVoice${UUID.randomUUID()}"
    val connection = (URL(ENDPOINT).openConnection() as HttpURLConnection).apply {
      requestMethod = "POST"
      connectTimeout = CONNECT_TIMEOUT_MS
      readTimeout = READ_TIMEOUT_MS
      doInput = true
      doOutput = true
      useCaches = false
      setRequestProperty("Authorization", "Bearer $apiKey")
      setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
      setRequestProperty("Accept", "application/json")
      setRequestProperty("Connection", "keep-alive")
    }
    synchronized(requestLock) {
      if (!isCurrent(generation)) {
        connection.disconnect()
        throw CancellationException("Transcription cancelled")
      }
      activeConnection = connection
    }

    val totalStartedAt = SystemClock.elapsedRealtime()
    var uploadStartedAt = 0L
    var uploadFinishedAt = 0L
    var responseHeadersAt = 0L
    var responseBodyFinishedAt = 0L

    try {
      ensureCurrent(generation)
      uploadStartedAt = SystemClock.elapsedRealtime()
      connection.outputStream.buffered(BUFFER_SIZE_BYTES).use { output ->
        writeTextPart(output, boundary, "model", MODEL)
        writeTextPart(output, boundary, "response_format", "json")
        if (language.isNotBlank() && language != "auto") {
          writeTextPart(output, boundary, "language", language)
        }
        output.write("--$boundary\r\n".toByteArray())
        output.write("Content-Disposition: form-data; name=\"file\"; filename=\"recording.wav\"\r\n".toByteArray())
        output.write("Content-Type: audio/wav\r\n\r\n".toByteArray())
        file.inputStream().buffered(BUFFER_SIZE_BYTES).use { input ->
          input.copyTo(output, BUFFER_SIZE_BYTES)
        }
        output.write("\r\n--$boundary--\r\n".toByteArray())
        output.flush()
      }
      uploadFinishedAt = SystemClock.elapsedRealtime()
      ensureCurrent(generation)

      val responseCode = connection.responseCode
      responseHeadersAt = SystemClock.elapsedRealtime()
      ensureCurrent(generation)
      val response = readResponseBody(
        if (responseCode in 200..299) connection.inputStream else connection.errorStream,
      )
      responseBodyFinishedAt = SystemClock.elapsedRealtime()

      Log.d(TAG, "Groq response code=$responseCode bodyChars=${response.length}")

      if (responseCode !in 200..299) throw cloudError(responseCode)
      val text = JSONObject(response).optString("text").trim()
      if (text.isEmpty()) throw IllegalStateException("Groq Cloud non ha restituito testo")
      return text
    } finally {
      val totalFinishedAt = SystemClock.elapsedRealtime()
      Log.i(
        TAG,
        "Groq timing bytes=$fileBytes " +
          "uploadMs=${elapsedMs(uploadStartedAt, uploadFinishedAt)} " +
          "serverWaitMs=${elapsedMs(uploadFinishedAt, responseHeadersAt)} " +
          "bodyMs=${elapsedMs(responseHeadersAt, responseBodyFinishedAt)} " +
          "totalMs=${totalFinishedAt - totalStartedAt}",
      )
      synchronized(requestLock) {
        if (activeConnection === connection) activeConnection = null
      }
      connection.disconnect()
    }
  }

  private fun ensureCurrent(generation: Long) {
    if (!isCurrent(generation)) throw CancellationException("Transcription cancelled")
  }

  private fun isCurrent(generation: Long): Boolean = requestGeneration.get() == generation

  private fun forgetFile(file: File) {
    synchronized(requestLock) { pendingFiles.remove(file) }
  }

  private fun elapsedMs(start: Long, end: Long): String =
    if (start == 0L || end == 0L) "na" else (end - start).toString()

  private fun writeTextPart(output: java.io.OutputStream, boundary: String, name: String, value: String) {
    output.write("--$boundary\r\n".toByteArray())
    output.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray())
    output.write(value.toByteArray(Charsets.UTF_8))
    output.write("\r\n".toByteArray())
  }

  private fun readResponseBody(input: InputStream?): String {
    if (input == null) return ""
    val body = ByteArrayOutputStream()
    val buffer = ByteArray(RESPONSE_READ_BUFFER_BYTES)
    var totalBytes = 0
    input.buffered(RESPONSE_READ_BUFFER_BYTES).use { bufferedInput ->
      while (true) {
        val count = bufferedInput.read(buffer)
        if (count < 0) break
        if (totalBytes + count > MAX_RESPONSE_BODY_BYTES) {
          throw IllegalStateException("Risposta Groq Cloud troppo grande")
        }
        body.write(buffer, 0, count)
        totalBytes += count
      }
    }
    return body.toString(Charsets.UTF_8.name())
  }

  private fun cloudError(responseCode: Int): IllegalStateException = when (responseCode) {
    401, 403 -> IllegalStateException("Chiave Groq Cloud non autorizzata")
    408 -> IllegalStateException("Groq Cloud ha esaurito il tempo di attesa")
    413 -> IllegalStateException("Registrazione troppo lunga per Groq Cloud")
    429 -> IllegalStateException("Limite Groq Cloud raggiunto")
    in 500..599 -> IllegalStateException("Groq Cloud non è disponibile")
    else -> IllegalStateException("Groq Cloud ha rifiutato la richiesta")
  }

  private companion object {
    const val TAG = "GroqCloudTranscriber"
    const val ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
    const val MODEL = "whisper-large-v3-turbo"
    const val CONNECT_TIMEOUT_MS = 10_000
    const val READ_TIMEOUT_MS = 45_000
    const val WAV_HEADER_BYTES = 44L
    const val BUFFER_SIZE_BYTES = 64 * 1024
    const val RESPONSE_READ_BUFFER_BYTES = 8 * 1024
    const val MAX_RESPONSE_BODY_BYTES = 1024 * 1024
  }
}
