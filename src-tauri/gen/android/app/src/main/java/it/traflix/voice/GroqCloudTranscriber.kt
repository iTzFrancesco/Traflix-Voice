package it.traflix.voice

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
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

  fun transcribe(file: File, language: String, listener: Listener) {
    Log.i(TAG, "transcription queued bytes=${file.length()} language=$language")
    executor.execute {
      Log.d(TAG, "transcription request started")
      val result = runCatching { request(file, language) }
      mainHandler.post {
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
      }
    }
  }

  fun shutdown() {
    executor.shutdownNow()
  }

  private fun request(file: File, language: String): String {
    val apiKey = VoiceSecretsStore(appContext).groqApiKey()
      ?: throw IllegalStateException("Configura la chiave Groq Cloud nelle impostazioni")
    if (!file.exists() || file.length() <= WAV_HEADER_BYTES) {
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
    }

    try {
      connection.outputStream.use { output ->
        writeTextPart(output, boundary, "model", MODEL)
        writeTextPart(output, boundary, "response_format", "json")
        if (language.isNotBlank() && language != "auto") {
          writeTextPart(output, boundary, "language", language)
        }
        output.write("--$boundary\r\n".toByteArray())
        output.write("Content-Disposition: form-data; name=\"file\"; filename=\"recording.wav\"\r\n".toByteArray())
        output.write("Content-Type: audio/wav\r\n\r\n".toByteArray())
        file.inputStream().use { input -> input.copyTo(output) }
        output.write("\r\n--$boundary--\r\n".toByteArray())
        output.flush()
      }

      val responseCode = connection.responseCode
      val response = (if (responseCode in 200..299) connection.inputStream else connection.errorStream)
        ?.bufferedReader(Charsets.UTF_8)
        ?.use { it.readText() }
        .orEmpty()

      Log.d(TAG, "Groq response code=$responseCode bodyChars=${response.length}")

      if (responseCode !in 200..299) throw cloudError(responseCode)
      val text = JSONObject(response).optString("text").trim()
      if (text.isEmpty()) throw IllegalStateException("Groq Cloud non ha restituito testo")
      return text
    } finally {
      connection.disconnect()
    }
  }

  private fun writeTextPart(output: java.io.OutputStream, boundary: String, name: String, value: String) {
    output.write("--$boundary\r\n".toByteArray())
    output.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray())
    output.write(value.toByteArray(Charsets.UTF_8))
    output.write("\r\n".toByteArray())
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
  }
}
