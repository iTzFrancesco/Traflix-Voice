package it.traflix.voice

import java.io.File
import java.io.IOException
import java.io.OutputStream

internal class GroqMultipartBody(
  private val file: File,
  language: String,
  boundary: String,
  fileName: String = "recording.wav",
  contentType: String = "audio/wav",
  minimumFileBytes: Long = WAV_HEADER_BYTES + 1,
) {
  private val expectedFileLength = file.length().also {
    if (!file.isFile || it < minimumFileBytes) {
      throw IllegalStateException("Registrazione vuota")
    }
  }
  private val expectedLastModified = file.lastModified()
  private val safeFileName = sanitizeFileName(fileName)
  private val safeContentType = sanitizeContentType(contentType)
  private val prefix = buildString {
    fun textPart(name: String, value: String) {
      append("--$boundary\r\n")
      append("Content-Disposition: form-data; name=\"$name\"\r\n\r\n")
      append(value)
      append("\r\n")
    }
    textPart("model", "whisper-large-v3-turbo")
    textPart("response_format", "json")
    if (language.isNotBlank() && language != "auto") textPart("language", language)
    append("--$boundary\r\n")
    append("Content-Disposition: form-data; name=\"file\"; filename=\"$safeFileName\"\r\n")
    append("Content-Type: $safeContentType\r\n\r\n")
  }.toByteArray(Charsets.UTF_8)
  private val suffix = "\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8)

  val contentLength: Long = Math.addExact(
    Math.addExact(prefix.size.toLong(), expectedFileLength),
    suffix.size.toLong(),
  )

  fun writeTo(output: OutputStream, ensureCurrent: () -> Unit) {
    ensureCurrent()
    checkFileUnchanged()
    file.inputStream().use { input ->
      if (input.channel.size() != expectedFileLength) throw changedFile()
      output.write(prefix)
      val buffer = ByteArray(COPY_BUFFER_BYTES)
      var remaining = expectedFileLength
      while (remaining > 0L) {
        ensureCurrent()
        val count = input.read(buffer, 0, minOf(remaining, buffer.size.toLong()).toInt())
        if (count < 0) throw changedFile()
        ensureCurrent()
        output.write(buffer, 0, count)
        remaining -= count
      }
      ensureCurrent()
      if (input.read() != -1 || input.channel.size() != expectedFileLength) throw changedFile()
      checkFileUnchanged()
      output.write(suffix)
      ensureCurrent()
      checkFileUnchanged()
    }
  }

  private fun checkFileUnchanged() {
    if (!file.isFile || file.length() != expectedFileLength || file.lastModified() != expectedLastModified) {
      throw changedFile()
    }
  }

  private fun changedFile(): IOException = IOException("Registrazione modificata durante l'invio")

  private fun sanitizeFileName(value: String): String = value
    .substringAfterLast('/')
    .substringAfterLast('\\')
    .map { character ->
      if (character.isLetterOrDigit() || character in setOf('.', '-', '_')) character else '_'
    }
    .joinToString("")
    .trim('.', '_')
    .take(120)
    .ifBlank { "audio.bin" }

  private fun sanitizeContentType(value: String): String =
    value.takeIf { CONTENT_TYPE_PATTERN.matches(it) } ?: "application/octet-stream"

  private companion object {
    const val WAV_HEADER_BYTES = 44L
    const val COPY_BUFFER_BYTES = 64 * 1024
    val CONTENT_TYPE_PATTERN = Regex("[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")
  }
}
