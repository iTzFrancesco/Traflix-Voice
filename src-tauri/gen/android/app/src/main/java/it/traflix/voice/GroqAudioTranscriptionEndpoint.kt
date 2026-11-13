package it.traflix.voice

import android.content.Context
import android.net.Uri
import android.webkit.MimeTypeMap
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.InternalCoroutinesApi
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext

/** App endpoint shared by the file picker and Android's audio-share target. */
class GroqAudioTranscriptionEndpoint(context: Context) {
  private val appContext = context.applicationContext
  private val transcriber = GroqCloudTranscriber(appContext)

  @OptIn(InternalCoroutinesApi::class)
  suspend fun transcribe(
    uri: Uri,
    displayName: String,
    mimeType: String,
    language: String,
  ): GroqAudioTranscript {
    val upload = withContext(Dispatchers.IO) {
      val coroutineContext = currentCoroutineContext()
      copyForUpload(uri, displayName, mimeType) { coroutineContext.ensureActive() }
    }
    try {
      return suspendCancellableCoroutine { continuation ->
        transcriber.transcribe(
          file = upload.file,
          language = language,
          listener = object : GroqCloudTranscriber.Listener {
            override fun onSuccess(text: String) {
              val token = continuation.tryResume(GroqAudioTranscript(text, language)) ?: return
              continuation.completeResume(token)
            }

            override fun onFailure(message: String) {
              val token = continuation.tryResumeWithException(IllegalStateException(message)) ?: return
              continuation.completeResume(token)
            }
          },
          uploadFileName = upload.fileName,
          contentType = upload.contentType,
          minimumFileBytes = 1,
        )
        continuation.invokeOnCancellation { transcriber.cancel() }
      }
    } catch (error: CancellationException) {
      transcriber.cancel()
      throw error
    } finally {
      upload.file.delete()
    }
  }

  fun shutdown() {
    transcriber.shutdown()
  }

  private fun copyForUpload(
    uri: Uri,
    displayName: String,
    suppliedMimeType: String,
    ensureActive: () -> Unit,
  ): PreparedUpload {
    val metadata = resolveMetadata(displayName, suppliedMimeType.ifBlank {
      runCatching { appContext.contentResolver.getType(uri) }.getOrNull().orEmpty()
    })
    val temporary = File.createTempFile("traflix-audio-", ".${metadata.extension}", appContext.cacheDir)
    try {
      val input = appContext.contentResolver.openInputStream(uri)
        ?: throw IllegalStateException("Non riesco ad aprire il file audio selezionato")
      input.use { source ->
        temporary.outputStream().buffered(COPY_BUFFER_BYTES).use { output ->
          val buffer = ByteArray(COPY_BUFFER_BYTES)
          var totalBytes = 0L
          while (true) {
            ensureActive()
            val count = source.read(buffer)
            if (count < 0) break
            totalBytes += count
            if (totalBytes > MAX_UPLOAD_BYTES) {
              throw IllegalStateException("Il file supera il limite Groq di 25 MB")
            }
            output.write(buffer, 0, count)
          }
          ensureActive()
          if (totalBytes == 0L) throw IllegalStateException("Il file audio è vuoto")
        }
      }
      return PreparedUpload(temporary, metadata.fileName, metadata.contentType)
    } catch (error: Exception) {
      temporary.delete()
      throw error
    }
  }

  private fun resolveMetadata(displayName: String, mimeType: String): UploadMetadata {
    val name = displayName.substringAfterLast('/').substringAfterLast('\\').ifBlank { "audio" }
    val suppliedExtension = name.substringAfterLast('.', "").lowercase()
    val normalizedMimeType = mimeType.substringBefore(';').trim().lowercase()
    val extension = when {
      suppliedExtension == "opus" -> "ogg"
      suppliedExtension in MIME_BY_EXTENSION -> suppliedExtension
      normalizedMimeType in EXTENSION_BY_MIME -> EXTENSION_BY_MIME.getValue(normalizedMimeType)
      else -> MimeTypeMap.getSingleton().getExtensionFromMimeType(normalizedMimeType)
        ?.lowercase()
        ?.takeIf { it in MIME_BY_EXTENSION }
    } ?: throw IllegalStateException("Formato audio non supportato da Groq")

    val dot = name.lastIndexOf('.')
    val base = if (dot > 0) name.substring(0, dot) else name
    val safeBase = base
      .map { character -> if (character.isLetterOrDigit() || character in setOf('-', '_')) character else '_' }
      .joinToString("")
      .take(96)
      .ifBlank { "audio" }
    val contentType = MIME_BY_EXTENSION.getValue(extension)
    return UploadMetadata("$safeBase.$extension", extension, contentType)
  }

  private data class PreparedUpload(val file: File, val fileName: String, val contentType: String)
  private data class UploadMetadata(val fileName: String, val extension: String, val contentType: String)

  private companion object {
    const val MAX_UPLOAD_BYTES = 25L * 1024L * 1024L
    const val COPY_BUFFER_BYTES = 64 * 1024

    val MIME_BY_EXTENSION = mapOf(
      "flac" to "audio/flac",
      "mp3" to "audio/mpeg",
      "mp4" to "audio/mp4",
      "mpeg" to "audio/mpeg",
      "mpga" to "audio/mpeg",
      "m4a" to "audio/mp4",
      "ogg" to "audio/ogg",
      "wav" to "audio/wav",
      "webm" to "audio/webm",
    )
    val EXTENSION_BY_MIME = mapOf(
      "audio/flac" to "flac",
      "audio/mpeg" to "mp3",
      "audio/mp4" to "m4a",
      "audio/ogg" to "ogg",
      "audio/wav" to "wav",
      "audio/x-wav" to "wav",
      "audio/webm" to "webm",
    )
  }
}

data class GroqAudioTranscript(val text: String, val language: String)
