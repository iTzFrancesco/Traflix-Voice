package it.traflix.voice

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.ceil
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** Opt-in loopback JVM timings, not Groq latency or Android hardware measurements. */
class GroqUploadBenchmarkTest {
  @get:Rule val files = TemporaryFolder()

  @Test
  fun comparesTwentyLoopbackUploadProfiles() {
    assumeTrue("Set TRAFLIX_GROQ_UPLOAD_BENCHMARK=1 to run", System.getenv(ENABLE_ENV) == "1")
    val outputDirectory = outputDirectory()
    val profiles = buildList {
      for (seconds in listOf(1, 3, 10, 30, 60)) {
        for (readBytes in listOf(8 * 1024, 64 * 1024)) {
          for (pauseMs in listOf(0, 1)) add(Profile(size + 1, seconds, readBytes, pauseMs))
        }
      }
    }
    assertEquals(20, profiles.size)
    val samples = StringBuilder(
      "profile\tpcm_seconds\twav_bytes\tserver_read_bytes\tserver_pause_ms\ttrial\tposition\tmode\tbody_bytes\tupload_ns\ttotal_ns\tserver_reads\n",
    )
    val summary = StringBuilder(
      "profile\tpcm_seconds\twav_bytes\tserver_read_bytes\tserver_pause_ms\tpairs\tbuffered_median_ms\tfixed_buffered_median_ms\tbuffered_p95_ms\tfixed_buffered_p95_ms\tpaired_median_delta_ms\tmedian_speedup\tbuffered_median_server_reads\tfixed_buffered_median_server_reads\thelper_buffered_median_ms\thelper_buffered_p95_ms\thelper_paired_median_delta_ms\thelper_median_speedup\thelper_buffered_median_server_reads\n",
    )
    LoopbackServer().use { server ->
      val replayResults = verifyNoAutomaticReplay(server)
      val streamingResults = verifyDeliveryBeforeProducerFinishes(server)
      for (profile in profiles) {
        val file = syntheticWav(profile.seconds)
        try {
          val body = GroqMultipartBody(file, LANGUAGE, BOUNDARY)
          val expected = ByteArrayOutputStream().apply { writeLegacyBody(file, this) }.toByteArray()
          assertEquals(expected.size.toLong(), body.contentLength)
          val buffered = mutableListOf<Measurement>()
          val fixed = mutableListOf<Measurement>()
          val helperBuffered = mutableListOf<Measurement>()
          for (round in 0 until WARMUP_PAIRS + MEASURED_PAIRS) {
            val order = if ((profile.id + round) % 2 == 0) mutableListOf(0, 2) else mutableListOf(2, 0)
            order.add((profile.id + round) % 3, 3)
            for ((position, mode) in order.withIndex()) {
              val expectation = Expectation(expected, profile.readBytes, profile.pauseMs, 200)
              val measurement = upload(server, expectation, file, mode)
              if (round >= WARMUP_PAIRS) {
                when (mode) {
                  0 -> buffered.add(measurement)
                  2 -> fixed.add(measurement)
                  3 -> helperBuffered.add(measurement)
                }
                samples.append(
                  listOf(
                    profile.id, profile.seconds, file.length(), profile.readBytes, profile.pauseMs,
                    round - WARMUP_PAIRS + 1, position + 1, mode, body.contentLength,
                    measurement.uploadNs, measurement.totalNs, measurement.serverReads,
                  ).joinToString("\t"),
                ).append('\n')
              }
            }
          }
          val bufferedMs = buffered.map { it.totalNs / 1_000_000.0 }
          val fixedMs = fixed.map { it.totalNs / 1_000_000.0 }
          val helperMs = helperBuffered.map { it.totalNs / 1_000_000.0 }
          val deltas = buffered.zip(fixed) { old, new -> (old.totalNs - new.totalNs) / 1_000_000.0 }
          val helperDeltas = buffered.zip(helperBuffered) { old, new -> (old.totalNs - new.totalNs) / 1_000_000.0 }
          summary.append(
            listOf(
              profile.id, profile.seconds, file.length(), profile.readBytes, profile.pauseMs, MEASURED_PAIRS,
              number(median(bufferedMs)), number(median(fixedMs)),
              number(p95(bufferedMs)), number(p95(fixedMs)), number(median(deltas)),
              number(median(bufferedMs) / median(fixedMs)),
              number(median(buffered.map { it.serverReads.toDouble() })),
              number(median(fixed.map { it.serverReads.toDouble() })),
              number(median(helperMs)), number(p95(helperMs)), number(median(helperDeltas)),
              number(median(bufferedMs) / median(helperMs)),
              number(median(helperBuffered.map { it.serverReads.toDouble() })),
            ).joinToString("\t"),
          ).append('\n')
        } finally {
          assertTrue(file.delete())
        }
      }
      File(outputDirectory, "upload_samples.tsv").writeText(samples.toString())
      File(outputDirectory, "upload_profiles.tsv").writeText(summary.toString())
      File(outputDirectory, "upload_replay_checks.tsv").writeText(replayResults)
      File(outputDirectory, "upload_streaming_checks.tsv").writeText(streamingResults)
    }
  }

  private fun verifyNoAutomaticReplay(server: LoopbackServer): String {
    val file = syntheticWav(1)
    try {
      val body = GroqMultipartBody(file, LANGUAGE, BOUNDARY)
      val expected = ByteArrayOutputStream().apply { writeLegacyBody(file, this) }.toByteArray()
      assertEquals(expected.size.toLong(), body.contentLength)
      val results = StringBuilder("mode\tfollow_redirects\tresponse_code\treturned_code\trequest_count\tredirect_target_count\ttotal_ns\n")
      for (code in listOf(301, 302, 303, 307, 308, 401, 407)) {
        for (mode in listOf(0, 2, 3)) {
          val expectation = Expectation(expected, 8 * 1024, 0, code)
          val measurement = upload(server, expectation, file, mode)
          assertEquals(code, measurement.responseCode)
          assertEquals(1, expectation.requestCount.get())
          assertEquals(0, server.redirectTargetCount.get())
          results.append(
            listOf(mode, 0, code, measurement.responseCode, expectation.requestCount.get(), server.redirectTargetCount.get(), measurement.totalNs)
              .joinToString("\t"),
          ).append('\n')
        }
      }
      // No credentials are used. This probe shows the replay behavior streaming mode removes.
      for (mode in listOf(0, 2, 3)) {
        server.redirectTargetCount.set(0)
        val expectation = Expectation(expected, 8 * 1024, 0, 307)
        val measurement = upload(server, expectation, file, mode, followRedirects = true)
        assertEquals(if (mode == 2) 307 else 200, measurement.responseCode)
        assertEquals(if (mode == 2) 1 else 2, expectation.requestCount.get())
        assertEquals(if (mode == 2) 0 else 1, server.redirectTargetCount.get())
        results.append(
          listOf(mode, 1, 307, measurement.responseCode, expectation.requestCount.get(), server.redirectTargetCount.get(), measurement.totalNs)
            .joinToString("\t"),
        ).append('\n')
      }
      return results.toString()
    } finally {
      assertTrue(file.delete())
    }
  }

  private fun verifyDeliveryBeforeProducerFinishes(server: LoopbackServer): String {
    val file = syntheticWav(10)
    val producer = Executors.newSingleThreadExecutor {
      Thread(it, "groq-upload-producer-test").apply { isDaemon = true }
    }
    try {
      val expected = ByteArrayOutputStream().apply { writeLegacyBody(file, this) }.toByteArray()
      val suffixBytes = "\r\n--$BOUNDARY--\r\n".toByteArray(Charsets.UTF_8).size
      val prefixBytes = expected.size.toLong() - file.length() - suffixBytes
      val firstChunkBytes = prefixBytes + COPY_BUFFER_BYTES
      val results = StringBuilder(
        "mode\tbody_bytes\tpause_after_bytes\tfirst_chunk_while_paused\tfirst_chunk_before_finish\tproducer_pause_ns\tfirst_chunk_from_start_ns\ttotal_ns\tserver_reads\n",
      )
      for (mode in listOf(3, 2)) {
        val expectation = Expectation(expected, 8 * 1024, 0, 200, firstChunkBytes)
        val gate = ProducerGate(firstChunkBytes)
        // Both modes use the helper and the same output buffer to isolate transport buffering.
        val future = producer.submit<Measurement> { upload(server, expectation, file, mode, producerGate = gate) }
        val paused: Boolean
        val deliveredWhilePaused: Boolean
        try {
          paused = gate.paused.await(5L, TimeUnit.SECONDS)
          deliveredWhilePaused = paused && expectation.firstChunkReceived.await(1L, TimeUnit.SECONDS)
        } finally {
          gate.release.countDown()
        }
        val measurement = future.get(10L, TimeUnit.SECONDS)
        assertTrue("Producer did not pause after its first WAV chunk", paused)
        assertEquals(mode == 2, deliveredWhilePaused)
        assertEquals(mode == 2, expectation.firstChunkBeforeFinish.get())
        assertEquals(0L, expectation.firstChunkReceived.count)
        results.append(
          listOf(
            mode, expected.size, firstChunkBytes, if (deliveredWhilePaused) 1 else 0,
            if (expectation.firstChunkBeforeFinish.get()) 1 else 0, gate.pauseDurationNs,
            expectation.firstChunkAtNs.get() - expectation.startedAtNs.get(), measurement.totalNs,
            measurement.serverReads,
          ).joinToString("\t"),
        ).append('\n')
      }
      return results.toString()
    } finally {
      producer.shutdownNow()
      producer.awaitTermination(5L, TimeUnit.SECONDS)
      assertTrue(file.delete())
    }
  }

  private fun upload(
    server: LoopbackServer,
    expectation: Expectation,
    file: File,
    mode: Int,
    followRedirects: Boolean = false,
    producerGate: ProducerGate? = null,
  ): Measurement {
    server.expected.set(expectation)
    val started = System.nanoTime()
    expectation.startedAtNs.set(started)
    val body = if (mode != 0 || producerGate != null) GroqMultipartBody(file, LANGUAGE, BOUNDARY) else null
    val connection = (URL("${server.baseUrl}/upload").openConnection(Proxy.NO_PROXY) as HttpURLConnection).apply {
      requestMethod = "POST"
      doInput = true
      doOutput = true
      useCaches = false
      instanceFollowRedirects = followRedirects
      connectTimeout = 10_000
      readTimeout = 45_000
      setRequestProperty("Content-Type", "multipart/form-data; boundary=$BOUNDARY")
      setRequestProperty("Accept", "application/json")
      setRequestProperty("Connection", "keep-alive")
      if (mode == 1 || mode == 2) setFixedLengthStreamingMode(requireNotNull(body).contentLength)
    }
    try {
      val uploadStarted = System.nanoTime()
      val rawOutput = connection.outputStream
      val output = if (mode == 1) rawOutput else rawOutput.buffered(COPY_BUFFER_BYTES)
      output.use {
        if (body == null) {
          writeLegacyBody(file, output)
        } else if (producerGate == null) {
          body.writeTo(output) {}
        } else {
          val observed = object : OutputStream() {
            override fun write(value: Int) {
              output.write(value)
              producerGate.bytesProduced++
            }
            override fun write(bytes: ByteArray, offset: Int, length: Int) {
              output.write(bytes, offset, length)
              producerGate.bytesProduced += length
            }
          }
          body.writeTo(observed) { producerGate.checkpoint() }
        }
        expectation.producerFinished.set(true)
        output.flush()
      }
      val uploadFinished = System.nanoTime()
      val responseCode = connection.responseCode
      val response = if (responseCode in 200..299) connection.inputStream else connection.errorStream
      response?.use { input ->
        val buffer = ByteArray(1024)
        while (input.read(buffer) != -1) { /* Consume only the synthetic local response. */ }
      }
      val finished = System.nanoTime()
      expectation.failure.get()?.let { throw AssertionError("Loopback request validation failed", it) }
      if (!followRedirects) {
        assertEquals(expectation.responseCode, responseCode)
        assertEquals(1, expectation.requestCount.get())
      }
      return Measurement(uploadFinished - uploadStarted, finished - started, responseCode, expectation.readCount.get())
    } finally {
      connection.disconnect()
      server.expected.set(null)
    }
  }

  private fun syntheticWav(seconds: Int): File {
    val dataBytes = seconds * 16_000 * 2
    val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
      put("RIFF".toByteArray(Charsets.US_ASCII))
      putInt(dataBytes + 36)
      put("WAVEfmt ".toByteArray(Charsets.US_ASCII))
      putInt(16)
      putShort(1.toShort())
      putShort(1.toShort())
      putInt(16_000)
      putInt(32_000)
      putShort(2.toShort())
      putShort(16.toShort())
      put("data".toByteArray(Charsets.US_ASCII))
      putInt(dataBytes)
    }.array()
    return files.newFile().apply {
      outputStream().use { output ->
        output.write(header)
        val buffer = ByteArray(8 * 1024) { (it * 31 + 17).toByte() }
        var remaining = dataBytes
        while (remaining > 0) {
          val count = minOf(remaining, buffer.size)
          output.write(buffer, 0, count)
          remaining -= count
        }
      }
    }
  }

  private fun writeLegacyBody(file: File, output: OutputStream) {
    fun textPart(name: String, value: String) {
      output.write("--$BOUNDARY\r\n".toByteArray())
      output.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray())
      output.write(value.toByteArray(Charsets.UTF_8))
      output.write("\r\n".toByteArray())
    }
    textPart("model", "whisper-large-v3-turbo")
    textPart("response_format", "json")
    if (LANGUAGE.isNotBlank() && LANGUAGE != "auto") textPart("language", LANGUAGE)
    output.write("--$BOUNDARY\r\n".toByteArray())
    output.write("Content-Disposition: form-data; name=\"file\"; filename=\"recording.wav\"\r\n".toByteArray())
    output.write("Content-Type: audio/wav\r\n\r\n".toByteArray())
    file.inputStream().buffered(COPY_BUFFER_BYTES).use { it.copyTo(output, COPY_BUFFER_BYTES) }
    output.write("\r\n--$BOUNDARY--\r\n".toByteArray())
  }

  private fun outputDirectory(): File {
    val path = System.getenv(OUTPUT_ENV)
    require(!path.isNullOrBlank()) { "Set $OUTPUT_ENV to an absolute evidence directory outside the repository" }
    val directory = File(path)
    require(directory.isAbsolute) { "$OUTPUT_ENV must be absolute" }
    val canonical = directory.canonicalFile
    val repository = generateSequence(File(System.getProperty("user.dir")).canonicalFile) { it.parentFile }
      .firstOrNull { File(it, ".git").exists() }
    require(repository == null || !canonical.toPath().startsWith(repository.toPath())) {
      "$OUTPUT_ENV must be outside the repository"
    }
    require(canonical.isDirectory || canonical.mkdirs()) { "Cannot create benchmark evidence directory" }
    return canonical
  }

  private fun median(values: List<Double>): Double {
    val sorted = values.sorted()
    val middle = sorted.size / 2
    return if (sorted.size % 2 == 0) (sorted[middle - 1] + sorted[middle]) / 2.0 else sorted[middle]
  }

  private fun p95(values: List<Double>): Double = values.sorted()[ceil(values.size * 0.95).toInt() - 1]

  private fun number(value: Double): String = String.format(Locale.ROOT, "%.6f", value)

  private data class Profile(val id: Int, val seconds: Int, val readBytes: Int, val pauseMs: Int)
  private data class Measurement(val uploadNs: Long, val totalNs: Long, val responseCode: Int, val serverReads: Int)

  private class ProducerGate(private val afterBytes: Long) {
    val paused = CountDownLatch(1)
    val release = CountDownLatch(1)
    var bytesProduced = 0L
    var pauseDurationNs = 0L
    private var didPause = false

    fun checkpoint() {
      if (!didPause && bytesProduced >= afterBytes) {
        didPause = true
        val started = System.nanoTime()
        paused.countDown()
        check(release.await(10L, TimeUnit.SECONDS)) { "Producer gate was not released" }
        pauseDurationNs = System.nanoTime() - started
      }
    }
  }

  private class Expectation(
    val bytes: ByteArray,
    val readBytes: Int,
    val pauseMs: Int,
    val responseCode: Int,
    val firstChunkBytes: Long = 0L,
  ) {
    val requestCount = AtomicInteger(0)
    val readCount = AtomicInteger(0)
    val failure = AtomicReference<Throwable?>(null)
    val producerFinished = AtomicBoolean(false)
    val firstChunkBeforeFinish = AtomicBoolean(false)
    val firstChunkReceived = CountDownLatch(1)
    val firstChunkAtNs = AtomicLong(0L)
    val startedAtNs = AtomicLong(0L)
  }

  private class LoopbackServer : AutoCloseable {
    val expected = AtomicReference<Expectation?>(null)
    val redirectTargetCount = AtomicInteger(0)
    private val executor = Executors.newSingleThreadExecutor {
      Thread(it, "groq-upload-loopback-test").apply { isDaemon = true }
    }
    private val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0).apply {
      executor = this@LoopbackServer.executor
      createContext("/upload") { exchange -> handle(exchange) }
      createContext("/unexpected") { exchange ->
        redirectTargetCount.incrementAndGet()
        handle(exchange, redirected = true)
      }
      start()
    }
    val baseUrl: String = "http://127.0.0.1:${server.address.port}"

    private fun handle(exchange: HttpExchange, redirected: Boolean = false) {
      val expectation = expected.get()
      if (expectation == null) {
        exchange.sendResponseHeaders(500, -1L)
        exchange.close()
        return
      }
      try {
        expectation.requestCount.incrementAndGet()
        assertEquals("POST", exchange.requestMethod)
        assertEquals(expectation.bytes.size.toLong(), exchange.requestHeaders.getFirst("Content-Length")?.toLongOrNull())
        assertEquals(null, exchange.requestHeaders.getFirst("Transfer-Encoding"))
        exchange.requestBody.use { input ->
          val buffer = ByteArray(expectation.readBytes)
          var offset = 0
          while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            expectation.readCount.incrementAndGet()
            assertTrue("Loopback request exceeds its expected length", offset + count <= expectation.bytes.size)
            for (index in 0 until count) {
              if (buffer[index] != expectation.bytes[offset + index]) {
                throw AssertionError("Loopback multipart bytes differ at index=${offset + index}")
              }
            }
            offset += count
            if (expectation.firstChunkBytes > 0L && offset >= expectation.firstChunkBytes &&
              expectation.firstChunkAtNs.compareAndSet(0L, System.nanoTime())) {
              expectation.firstChunkBeforeFinish.set(!expectation.producerFinished.get())
              expectation.firstChunkReceived.countDown()
            }
            if (expectation.pauseMs > 0) Thread.sleep(expectation.pauseMs.toLong())
          }
          assertEquals(expectation.bytes.size, offset)
        }
        val responseCode = if (redirected) 200 else expectation.responseCode
        if (responseCode in 300..399) {
          exchange.responseHeaders.set("Location", "$baseUrl/unexpected")
        }
        if (responseCode == 401) exchange.responseHeaders.set("WWW-Authenticate", "Basic realm=\"offline\"")
        if (responseCode == 407) exchange.responseHeaders.set("Proxy-Authenticate", "Basic realm=\"offline\"")
        val response = "{}".toByteArray(Charsets.UTF_8)
        exchange.responseHeaders.set("Content-Type", "application/json")
        exchange.sendResponseHeaders(responseCode, response.size.toLong())
        exchange.responseBody.use { it.write(response) }
      } catch (error: Throwable) {
        expectation.failure.set(error)
        runCatching { exchange.sendResponseHeaders(500, -1L) }
      } finally {
        exchange.close()
      }
    }

    override fun close() {
      server.stop(0)
      executor.shutdownNow()
    }
  }

  private companion object {
    // Modes: 0 legacy buffered, 1 original raw fixed, 2 buffered fixed, 3 production helper buffered.
    const val ENABLE_ENV = "TRAFLIX_GROQ_UPLOAD_BENCHMARK"
    const val OUTPUT_ENV = "TRAFLIX_GROQ_UPLOAD_BENCHMARK_OUTPUT"
    const val BOUNDARY = "----TraflixVoiceLoopbackBenchmark"
    const val LANGUAGE = "it"
    const val COPY_BUFFER_BYTES = 64 * 1024
    const val WARMUP_PAIRS = 2
    const val MEASURED_PAIRS = 10
  }
}
