package it.traflix.voice

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sqrt

/** Constant gain for quiet PCM16 speech. Never trims or gates audio samples. */
internal class VoicePcmGain {
  private val activeFrameRms = mutableListOf<Double>()
  private var frameEnergy = 0.0
  private var frameSamples = 0
  private var peak = 0

  fun analyze(samples: ShortArray, count: Int = samples.size) {
    for (index in 0 until count) {
      val sample = samples[index].toInt()
      peak = maxOf(peak, abs(sample))
      frameEnergy += sample.toDouble() * sample
      frameSamples += 1
      if (frameSamples == FRAME_SAMPLES) {
        val rms = sqrt(frameEnergy / frameSamples) / Short.MAX_VALUE
        if (rms >= ACTIVITY_THRESHOLD) activeFrameRms.add(rms)
        frameEnergy = 0.0
        frameSamples = 0
      }
    }
  }

  fun recommendedGain(): Double {
    val frames = activeFrameRms.toMutableList()
    if (frameSamples > 0) {
      val rms = sqrt(frameEnergy / frameSamples) / Short.MAX_VALUE
      if (rms >= ACTIVITY_THRESHOLD) frames.add(rms)
    }
    if (frames.isEmpty() || peak == 0) return 1.0
    frames.sort()
    val speechRms = frames[((frames.size - 1) * 0.6).roundToInt()]
    return minOf(MAX_GAIN, TARGET_RMS / speechRms, PEAK_CEILING * Short.MAX_VALUE / peak)
      .coerceAtLeast(1.0)
  }

  fun applyToWav(file: File) {
    val gain = recommendedGain()
    if (gain <= 1.0) return
    RandomAccessFile(file, "rw").use { audio ->
      val buffer = ByteArray(32 * 1024)
      val pcm = ByteBuffer.wrap(buffer).order(ByteOrder.LITTLE_ENDIAN)
      var position = WAV_HEADER_BYTES
      while (position < audio.length()) {
        audio.seek(position)
        val count = minOf(buffer.size.toLong(), audio.length() - position).toInt()
        require(count % 2 == 0) { "Invalid PCM16 audio length" }
        audio.readFully(buffer, 0, count)
        for (offset in 0 until count step 2) {
          val sample = (pcm.getShort(offset) * gain).roundToInt()
            .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
          pcm.putShort(offset, sample.toShort())
        }
        audio.seek(position)
        audio.write(buffer, 0, count)
        position += count
      }
    }
  }

  private companion object {
    const val FRAME_SAMPLES = 320
    const val ACTIVITY_THRESHOLD = 0.0015
    const val TARGET_RMS = 0.08
    const val MAX_GAIN = 4.0
    const val PEAK_CEILING = 0.98
    const val WAV_HEADER_BYTES = 44L
  }
}
