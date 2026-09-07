package it.traflix.voice

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs
import kotlin.math.sqrt

class VoiceAudioRecorder(
  context: Context,
  private val listener: Listener,
) {
  interface Listener {
    fun onMeter(value: Float)
    fun onRecordingFinished(file: File, durationMs: Long)
    fun onRecordingError(message: String)
  }

  private val appContext = context.applicationContext
  private val audioManager = appContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager
  private val mainHandler = Handler(Looper.getMainLooper())
  private val executor: ExecutorService = Executors.newSingleThreadExecutor {
    Thread(it, "traflix-voice-audio").apply { isDaemon = true }
  }
  private val lock = Any()
  private val recording = AtomicBoolean(false)
  private val cancelled = AtomicBoolean(false)
  private var audioRecord: AudioRecord? = null
  private var outputFile: File? = null
  private var startedAt = 0L
  private var audioFocusRequest: AudioFocusRequest? = null

  private val audioFocusListener = AudioManager.OnAudioFocusChangeListener { change ->
    Log.d(TAG, "audio focus change=$change recording=${recording.get()}")
    if (change == AudioManager.AUDIOFOCUS_LOSS ||
      change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT
    ) {
      Log.w(TAG, "stopping because audio focus was lost")
      stop()
    }
  }

  fun start(): Boolean {
    Log.d(TAG, "start requested")
    if (appContext.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
      Log.w(TAG, "start rejected: microphone permission missing")
      listener.onRecordingError("Microfono non autorizzato")
      return false
    }

    synchronized(lock) {
      if (recording.get()) return false

      val minimumBuffer = AudioRecord.getMinBufferSize(
        SAMPLE_RATE,
        CHANNEL_CONFIG,
        AUDIO_FORMAT,
      )
      if (minimumBuffer <= 0) {
        Log.e(TAG, "start rejected: invalid minimum buffer=$minimumBuffer")
        listener.onRecordingError("Microfono non disponibile")
        return false
      }

      val bufferSize = maxOf(minimumBuffer * 2, FRAME_SIZE * 4)
      val record = runCatching {
        AudioRecord(
          MediaRecorder.AudioSource.VOICE_RECOGNITION,
          SAMPLE_RATE,
          CHANNEL_CONFIG,
          AUDIO_FORMAT,
          bufferSize,
        )
      }.getOrElse {
        listener.onRecordingError("Impossibile inizializzare il microfono")
        return false
      }

      if (record.state != AudioRecord.STATE_INITIALIZED) {
        Log.e(TAG, "start rejected: AudioRecord not initialized")
        record.release()
        listener.onRecordingError("Microfono non inizializzato")
        return false
      }

      val directory = File(appContext.cacheDir, "voice-recordings")
      if (!directory.exists() && !directory.mkdirs()) {
        record.release()
        listener.onRecordingError("Impossibile preparare l'audio temporaneo")
        return false
      }

      val file = File(directory, "${UUID.randomUUID()}.wav")
      if (!requestAudioFocus()) {
        Log.w(TAG, "start rejected: audio focus not granted")
        record.release()
        listener.onRecordingError("Un'altra app sta usando il microfono")
        return false
      }

      audioRecord = record
      outputFile = file
      startedAt = System.currentTimeMillis()
      cancelled.set(false)
      recording.set(true)

      runCatching { record.startRecording() }.onFailure {
        Log.e(TAG, "AudioRecord.startRecording failed", it)
        recording.set(false)
        audioRecord = null
        outputFile = null
        abandonAudioFocus()
        record.release()
        listener.onRecordingError("Impossibile avviare la registrazione")
        return false
      }

      Log.i(TAG, "recording started bufferSize=$bufferSize")
      executor.execute { capture(record, file, bufferSize) }
      return true
    }
  }

  fun stop() {
    val wasRecording = recording.compareAndSet(true, false)
    Log.d(TAG, "stop requested active=$wasRecording")
    if (!wasRecording) return
    synchronized(lock) {
      runCatching { audioRecord?.stop() }
    }
  }

  fun cancel() {
    val wasRecording = recording.compareAndSet(true, false)
    Log.d(TAG, "cancel requested active=$wasRecording")
    if (!wasRecording) return
    cancelled.set(true)
    val file = synchronized(lock) {
      runCatching { audioRecord?.stop() }
      outputFile
    }
    file?.delete()
  }

  fun shutdown() {
    cancel()
    executor.shutdownNow()
  }

  private fun capture(record: AudioRecord, file: File, bufferSize: Int) {
    Log.d(TAG, "capture loop started")
    var output: FileOutputStream? = null
    var bytesWritten = 0
    var lastMeterAt = 0L
    val buffer = ShortArray(bufferSize / BYTES_PER_SAMPLE)

    try {
      output = FileOutputStream(file)
      output.write(wavHeader(0))
      val pcm = ByteBuffer.allocate(buffer.size * BYTES_PER_SAMPLE).order(ByteOrder.LITTLE_ENDIAN)

      while (recording.get()) {
        val count = record.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
        if (count < 0) {
          if (!recording.get()) break
          throw IllegalStateException("AudioRecord.read returned $count")
        }
        if (count == 0) continue

        pcm.clear()
        var energy = 0.0
        var peak = 0
        for (index in 0 until count) {
          val sample = buffer[index].toInt()
          energy += sample.toDouble() * sample.toDouble()
          peak = maxOf(peak, abs(sample))
          pcm.putShort(buffer[index])
        }
        val pcmLength = count * BYTES_PER_SAMPLE
        output.write(pcm.array(), 0, pcmLength)
        bytesWritten += pcmLength
        val now = System.currentTimeMillis()
        if (now - lastMeterAt >= METER_INTERVAL_MS) {
          lastMeterAt = now
          val rmsLevel = sqrt(energy / count).toFloat() / Short.MAX_VALUE
          val peakLevel = peak.toFloat() / Short.MAX_VALUE
          val level = maxOf(rmsLevel * RMS_METER_GAIN, peakLevel * PEAK_METER_WEIGHT)
            .coerceIn(0f, 1f)
          mainHandler.post { listener.onMeter(level) }
        }

        if (now - startedAt >= MAX_DURATION_MS) {
          Log.w(TAG, "maximum recording duration reached")
          recording.set(false)
          runCatching { record.stop() }
        }
      }
    } catch (error: Exception) {
      Log.e(TAG, "capture loop failed", error)
      file.delete()
      abandonAudioFocus()
      if (!cancelled.get()) {
        mainHandler.post { listener.onRecordingError("Errore durante la registrazione") }
      }
      return
    } finally {
      runCatching { output?.flush() }
      runCatching { output?.close() }
      record.release()
      synchronized(lock) {
        audioRecord = null
        outputFile = null
      }
      abandonAudioFocus()
      Log.d(
        TAG,
        "capture loop finished bytes=$bytesWritten cancelled=${cancelled.get()} recording=${recording.get()}",
      )
    }

    if (cancelled.get()) {
      file.delete()
      return
    }

    if (bytesWritten == 0) {
      file.delete()
      mainHandler.post { listener.onRecordingError("Registrazione vuota") }
      return
    }

    runCatching {
      RandomAccessFile(file, "rw").use { randomAccessFile ->
        randomAccessFile.seek(0)
        randomAccessFile.write(wavHeader(bytesWritten))
      }
    }.onFailure {
      file.delete()
      mainHandler.post { listener.onRecordingError("Impossibile finalizzare l'audio") }
      return
    }

    val duration = System.currentTimeMillis() - startedAt
    Log.i(TAG, "recording finished durationMs=$duration bytes=$bytesWritten")
    mainHandler.post { listener.onRecordingFinished(file, duration) }
  }

  private fun wavHeader(dataLength: Int): ByteArray {
    val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
    header.put("RIFF".toByteArray(Charsets.US_ASCII))
    header.putInt(36 + dataLength)
    header.put("WAVE".toByteArray(Charsets.US_ASCII))
    header.put("fmt ".toByteArray(Charsets.US_ASCII))
    header.putInt(16)
    header.putShort(1)
    header.putShort(CHANNELS.toShort())
    header.putInt(SAMPLE_RATE)
    header.putInt(SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE)
    header.putShort((CHANNELS * BYTES_PER_SAMPLE).toShort())
    header.putShort(BITS_PER_SAMPLE.toShort())
    header.put("data".toByteArray(Charsets.US_ASCII))
    header.putInt(dataLength)
    return header.array()
  }

  companion object {
    private const val TAG = "VoiceAudioRecorder"
    private const val SAMPLE_RATE = 16_000
    private const val CHANNELS = 1
    private const val BITS_PER_SAMPLE = 16
    private const val BYTES_PER_SAMPLE = BITS_PER_SAMPLE / 8
    private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
    private const val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT
    private const val FRAME_SIZE = 512
    private const val METER_INTERVAL_MS = 50L
    private const val RMS_METER_GAIN = 1.25f
    private const val PEAK_METER_WEIGHT = 0.32f
    private const val MAX_DURATION_MS = 5 * 60 * 1000L
  }

  private fun requestAudioFocus(): Boolean {
    val result = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
      val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
        .setAudioAttributes(
          AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build(),
        )
        .setOnAudioFocusChangeListener(audioFocusListener)
        .build()
      audioFocusRequest = request
      audioManager.requestAudioFocus(request)
    } else {
      @Suppress("DEPRECATION")
      audioManager.requestAudioFocus(
        audioFocusListener,
        AudioManager.STREAM_VOICE_CALL,
        AudioManager.AUDIOFOCUS_GAIN_TRANSIENT,
      )
    }
    val granted = result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED
    Log.d(TAG, "audio focus request result=$result granted=$granted")
    if (!granted) abandonAudioFocus()
    return granted
  }

  private fun abandonAudioFocus() {
    if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
      audioFocusRequest?.let { audioManager.abandonAudioFocusRequest(it) }
      audioFocusRequest = null
    } else {
      @Suppress("DEPRECATION")
      audioManager.abandonAudioFocus(audioFocusListener)
    }
  }
}
