package it.traflix.voice

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.file.Files
import kotlin.math.abs
import kotlin.math.sin
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VoicePcmGainTest {
  private fun quietSpeech(): ShortArray = ShortArray(8_000) {
    (327 * sin(2 * Math.PI * 220 * it / 16_000)).toInt().toShort()
  }

  @Test
  fun raisesQuietSpeechWithoutChangingItsLengthOrHeader() {
    val samples = quietSpeech()
    val gain = VoicePcmGain()
    gain.analyze(samples)
    assertEquals(4.0, gain.recommendedGain(), 0.001)
    val file = Files.createTempFile("voice-gain", ".wav").toFile()
    try {
      val header = ByteArray(44) { it.toByte() }
      val pcm = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
      samples.forEach { pcm.putShort(it) }
      file.writeBytes(header + pcm.array())
      gain.applyToWav(file)
      val result = file.readBytes()
      assertEquals(44 + samples.size * 2, result.size)
      assertArrayEquals(header, result.copyOfRange(0, 44))
      val decoded = ByteBuffer.wrap(result).order(ByteOrder.LITTLE_ENDIAN)
      for (index in samples.indices) {
        assertEquals((samples[index] * 4).toShort(), decoded.getShort(44 + index * 2))
      }
    } finally {
      file.delete()
    }
  }

  @Test
  fun doesNotAmplifySilenceOrLoudAudio() {
    for (samples in listOf(ShortArray(320), ShortArray(320) { 10_000 })) {
      val gain = VoicePcmGain()
      gain.analyze(samples)
      assertEquals(1.0, gain.recommendedGain(), 0.001)
    }
  }

  @Test
  fun limitsGainByTheStrongestPeakIncludingNegativeFullScale() {
    val samples = quietSpeech()
    samples[100] = 29_000
    val gain = VoicePcmGain()
    gain.analyze(samples)
    assertTrue(gain.recommendedGain() * 29_000 <= 0.98 * Short.MAX_VALUE + 1)
    samples[100] = Short.MIN_VALUE
    val fullScaleGain = VoicePcmGain()
    fullScaleGain.analyze(samples)
    assertEquals(1.0, fullScaleGain.recommendedGain(), 0.001)
  }

  @Test
  fun callbackBlockBoundariesDoNotAffectGain() {
    val samples = quietSpeech()
    samples[100] = 20_000
    val whole = VoicePcmGain().apply { analyze(samples) }
    val blocks = VoicePcmGain()
    for (start in samples.indices step 512) {
      blocks.analyze(samples.copyOfRange(start, minOf(start + 512, samples.size)))
    }
    assertEquals(whole.recommendedGain(), blocks.recommendedGain(), 0.00001)
    assertTrue(samples.any { abs(it.toInt()) > 0 })
  }
}
