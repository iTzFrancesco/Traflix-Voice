package it.traflix.voice

import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceDataResetStoreTest {
  @Test
  fun clearHistoryAndStatsRemovesHistoryAndResetsStatsOnly() {
    val dataDirectory = Files.createTempDirectory("voice-data-reset").toFile()
    try {
      val history = dataDirectory.resolve("history.json")
      val stats = dataDirectory.resolve("stats.json")
      val usage = dataDirectory.resolve("groq_usage.json")
      history.writeText("[{\"text\":\"dettato\"}]")
      stats.writeText("{\"total_words\":12,\"avg_wpm\":90,\"total_time\":0.2}")
      usage.writeText("{\"audio_seconds\":42}")

      VoiceDataResetStore.clearHistoryAndStats(dataDirectory) { source, target ->
        Files.move(
          source.toPath(),
          target.toPath(),
          java.nio.file.StandardCopyOption.REPLACE_EXISTING,
          java.nio.file.StandardCopyOption.ATOMIC_MOVE,
        )
      }

      assertFalse(history.exists())
      assertEquals(
        "{\"total_words\":0,\"avg_wpm\":0,\"total_time\":0.0}",
        stats.readText(),
      )
      assertTrue(usage.exists())
      assertEquals("{\"audio_seconds\":42}", usage.readText())
    } finally {
      dataDirectory.deleteRecursively()
    }
  }

  @Test
  fun fileLockSerializesThreadsInTheSameProcess() {
    val dataDirectory = Files.createTempDirectory("voice-data-lock").toFile()
    val lockFile = dataDirectory.resolve("history.lock")
    val firstEntered = CountDownLatch(1)
    val releaseFirst = CountDownLatch(1)
    val secondEntered = CountDownLatch(1)
    val executor = Executors.newFixedThreadPool(2)
    try {
      executor.submit {
        VoiceDataFileLocks.withLockFile(lockFile) {
          firstEntered.countDown()
          releaseFirst.await(3, TimeUnit.SECONDS)
        }
      }
      assertTrue(firstEntered.await(3, TimeUnit.SECONDS))

      executor.submit {
        VoiceDataFileLocks.withLockFile(lockFile) { secondEntered.countDown() }
      }
      assertFalse(secondEntered.await(100, TimeUnit.MILLISECONDS))

      releaseFirst.countDown()
      assertTrue(secondEntered.await(3, TimeUnit.SECONDS))
    } finally {
      releaseFirst.countDown()
      executor.shutdownNow()
      dataDirectory.deleteRecursively()
    }
  }
}
