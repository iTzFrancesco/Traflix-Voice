package it.traflix.voice

import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.util.concurrent.CancellationException
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class GroqMultipartBodyTest {
  @get:Rule val files = TemporaryFolder()

  @Test
  fun matchesLegacyEnvelopeAndExactWavBytesForConditionalAndUtf8Languages() {
    val wav = ByteArray(131_117) { (it * 31 + 17).toByte() }
    val file = files.newFile("audio.wav").apply { writeBytes(wav) }
    for (language in listOf("", " \t\r\n", "auto", "it", "en", "fr-CA", "中文-é-🗣", " auto ")) {
      for (boundary in listOf("----TraflixVoiceFixedBoundary", "custom-é-boundary")) {
        val body = GroqMultipartBody(file, language, boundary)
        val output = ByteArrayOutputStream()
        body.writeTo(output) {}
        val expected = legacyBody(wav, language, boundary)
        assertArrayEquals(expected, output.toByteArray())
        assertEquals(expected.size.toLong(), body.contentLength)
      }
    }
  }

  @Test
  fun calculatesLengthsBeyondIntRangeWithoutAllocatingTheWav() {
    val envelopeBytes = legacyBody(ByteArray(0), "中文-é", BOUNDARY).size.toLong()
    for (length in listOf(Int.MAX_VALUE.toLong() + 17L, Long.MAX_VALUE - envelopeBytes)) {
      val body = GroqMultipartBody(fileWithReportedLength(length), "中文-é", BOUNDARY)
      assertEquals(length + envelopeBytes, body.contentLength)
    }
  }

  @Test
  fun rejectsLongOverflowInsteadOfAdvertisingAWrappedLength() {
    assertThrows(ArithmeticException::class.java) {
      GroqMultipartBody(fileWithReportedLength(Long.MAX_VALUE), "it", BOUNDARY)
    }
  }

  @Test
  fun rejectsMissingDirectoryAndHeaderOnlyOrShortWavs() {
    assertThrows(IllegalStateException::class.java) {
      GroqMultipartBody(File(files.root, "missing.wav"), "auto", BOUNDARY)
    }
    assertThrows(IllegalStateException::class.java) {
      GroqMultipartBody(files.newFolder("not-a-wav"), "auto", BOUNDARY)
    }
    val file = files.newFile("short.wav")
    for (length in listOf(0, 12, 43, 44)) {
      file.writeBytes(ByteArray(length))
      assertThrows(IllegalStateException::class.java) { GroqMultipartBody(file, "auto", BOUNDARY) }
    }
  }

  @Test
  fun cancellationBeforeUploadWritesNothing() {
    val body = GroqMultipartBody(newWav(), "auto", BOUNDARY)
    val output = ByteArrayOutputStream()
    assertThrows(CancellationException::class.java) {
      body.writeTo(output) { throw CancellationException("cancelled") }
    }
    assertEquals(0, output.size())
  }

  @Test
  fun checksCancellationBetweenEveryCopyChunkAndBeforeTheSuffix() {
    val file = newWav(COPY_BUFFER_BYTES * 3 + 44)
    val expected = legacyBody(file.readBytes(), "it", BOUNDARY)
    for (cancelAfterChunks in 1..4) {
      val body = GroqMultipartBody(file, "it", BOUNDARY)
      var wavChunks = 0
      val output = ObservedOutput { write -> if (write > 1) wavChunks++ }
      assertThrows(CancellationException::class.java) {
        body.writeTo(output) {
          if (wavChunks == cancelAfterChunks) throw CancellationException("cancelled")
        }
      }
      val prefixBytes = legacyPrefix("it", BOUNDARY).size
      val wavBytes = minOf(cancelAfterChunks * COPY_BUFFER_BYTES, file.length().toInt())
      assertEquals(prefixBytes + wavBytes, output.size())
      assertArrayEquals(expected.copyOfRange(0, output.size()), output.toByteArray())
      assertTrue(output.size().toLong() < body.contentLength)
    }
  }

  @Test
  fun rejectsShortenedEnlargedAndDeletedFilesBeforeWriting() {
    for (change in listOf("shorten", "grow", "delete")) {
      val file = newWav()
      val body = GroqMultipartBody(file, "auto", BOUNDARY)
      when (change) {
        "shorten" -> RandomAccessFile(file, "rw").use { it.setLength(44L) }
        "grow" -> file.appendBytes(byteArrayOf(1))
        "delete" -> assertTrue(file.delete())
      }
      val output = ByteArrayOutputStream()
      assertThrows(IOException::class.java) { body.writeTo(output) {} }
      assertEquals(0, output.size())
    }
  }

  @Test
  fun rejectsAnEarlyEofDuringUploadWithoutFinishingTheEnvelope() {
    val file = newWav(COPY_BUFFER_BYTES * 3)
    val body = GroqMultipartBody(file, "auto", BOUNDARY)
    val output = ObservedOutput { write ->
      if (write == 2) RandomAccessFile(file, "rw").use { it.setLength(44L) }
    }
    assertThrows(IOException::class.java) { body.writeTo(output) {} }
    assertEquals(legacyPrefix("auto", BOUNDARY).size + COPY_BUFFER_BYTES, output.size())
    assertTrue(output.size().toLong() < body.contentLength)
  }

  @Test
  fun rejectsGrowthDuringUploadWithoutWritingBytesBeyondTheExpectedWav() {
    val file = newWav(COPY_BUFFER_BYTES * 2 + 44)
    val expectedWavBytes = file.length()
    val body = GroqMultipartBody(file, "auto", BOUNDARY)
    val output = ObservedOutput { write -> if (write == 2) file.appendBytes(byteArrayOf(1, 2, 3)) }
    assertThrows(IOException::class.java) { body.writeTo(output) {} }
    assertEquals(legacyPrefix("auto", BOUNDARY).size.toLong() + expectedWavBytes, output.size().toLong())
  }

  @Test
  fun rejectsSameLengthChangesWithChangedModificationTime() {
    val file = newWav(COPY_BUFFER_BYTES * 2)
    val originalModified = file.lastModified()
    val body = GroqMultipartBody(file, "auto", BOUNDARY)
    val output = ObservedOutput { write ->
      if (write == 2) {
        RandomAccessFile(file, "rw").use {
          it.seek(COPY_BUFFER_BYTES.toLong())
          it.writeByte(99)
        }
        assertTrue(file.setLastModified(originalModified + 2_000L))
      }
    }
    assertThrows(IOException::class.java) { body.writeTo(output) {} }
    assertTrue(output.size().toLong() < body.contentLength)
  }

  @Test
  fun doesNotReportSuccessIfTheFileChangesWhileTheSuffixIsWritten() {
    val file = newWav()
    val body = GroqMultipartBody(file, "auto", BOUNDARY)
    val output = ObservedOutput { write -> if (write == 3) file.appendBytes(byteArrayOf(1)) }
    assertThrows(IOException::class.java) { body.writeTo(output) {} }
    assertEquals(body.contentLength, output.size().toLong())
  }

  @Test
  fun leavesOutputOwnershipWithTheCaller() {
    val body = GroqMultipartBody(newWav(), "auto", BOUNDARY)
    val output = object : ByteArrayOutputStream() {
      var closed = false
      var flushed = false
      override fun close() { closed = true }
      override fun flush() { flushed = true }
    }
    body.writeTo(output) {}
    assertEquals(body.contentLength, output.size().toLong())
    assertFalse(output.closed)
    assertFalse(output.flushed)
  }

  private fun newWav(length: Int = 100): File =
    files.newFile().apply { writeBytes(ByteArray(length) { (it * 31 + 17).toByte() }) }

  private fun fileWithReportedLength(length: Long): File = object : File("unused-length-only.wav") {
    override fun length(): Long = length
    override fun isFile(): Boolean = true
    override fun lastModified(): Long = 1L
  }

  private fun legacyBody(wav: ByteArray, language: String, boundary: String): ByteArray =
    ByteArrayOutputStream().apply {
      write(legacyPrefix(language, boundary))
      write(wav)
      write("\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8))
    }.toByteArray()

  private fun legacyPrefix(language: String, boundary: String): ByteArray =
    ByteArrayOutputStream().apply {
      fun textPart(name: String, value: String) {
        write("--$boundary\r\n".toByteArray())
        write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray())
        write(value.toByteArray(Charsets.UTF_8))
        write("\r\n".toByteArray())
      }
      textPart("model", "whisper-large-v3-turbo")
      textPart("response_format", "json")
      if (language.isNotBlank() && language != "auto") textPart("language", language)
      write("--$boundary\r\n".toByteArray())
      write("Content-Disposition: form-data; name=\"file\"; filename=\"recording.wav\"\r\n".toByteArray())
      write("Content-Type: audio/wav\r\n\r\n".toByteArray())
    }.toByteArray()

  private class ObservedOutput(private val afterWrite: (Int) -> Unit) : ByteArrayOutputStream() {
    private var writes = 0
    override fun write(bytes: ByteArray, offset: Int, length: Int) {
      super.write(bytes, offset, length)
      afterWrite(++writes)
    }
  }

  private companion object {
    const val BOUNDARY = "----TraflixVoiceTestBoundary"
    const val COPY_BUFFER_BYTES = 64 * 1024
  }
}
