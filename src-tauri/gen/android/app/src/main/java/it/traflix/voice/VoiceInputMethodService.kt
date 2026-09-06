package it.traflix.voice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.inputmethodservice.InputMethodService
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import java.io.File

class VoiceInputMethodService : InputMethodService(), VoiceKeyboardView.Listener,
  VoiceAudioRecorder.Listener {
  override val context
    get() = this

  private val mainHandler = Handler(Looper.getMainLooper())
  private lateinit var settingsStore: VoiceSettingsStore
  private lateinit var recorder: VoiceAudioRecorder
  private lateinit var cloudTranscriber: GroqCloudTranscriber
  private lateinit var historyStore: VoiceHistoryStore
  private lateinit var metricsStore: VoiceMetricsStore
  private var keyboardView: VoiceKeyboardView? = null
  private var currentEditorInfo: EditorInfo? = null
  private var editorGeneration = 0L
  private var recordingGeneration: Long? = null
  private var recordingForegroundActive = false

  override fun onCreate() {
    super.onCreate()
    settingsStore = VoiceSettingsStore(this)
    recorder = VoiceAudioRecorder(this, this)
    cloudTranscriber = GroqCloudTranscriber(this)
    historyStore = VoiceHistoryStore(this)
    metricsStore = VoiceMetricsStore(this)
  }

  override fun onStartInput(attribute: EditorInfo?, restarting: Boolean) {
    super.onStartInput(attribute, restarting)
    currentEditorInfo = attribute
    editorGeneration += 1
    recordingGeneration = null
    keyboardView?.refreshMode()
  }

  override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
    super.onStartInputView(info, restarting)
    currentEditorInfo = info ?: currentEditorInfo
    keyboardView?.refreshMode()
  }

  override fun onFinishInput() {
    recorder.cancel()
    stopRecordingForeground()
    recordingGeneration = null
    keyboardView?.setState(MicIndicatorState.IDLE)
    currentEditorInfo = null
    super.onFinishInput()
  }

  override fun onCreateInputView(): View {
    return VoiceKeyboardView(this, settingsStore).also { keyboardView = it }
  }

  override fun onRecordingStartRequested() {
    if (isSensitiveField()) {
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Campo protetto: dettatura disattivata",
      )
      return
    }

    if (!hasMicrophonePermission()) {
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Abilita il microfono nelle impostazioni",
      )
      openAppSettings()
      return
    }

    if (!startRecordingForeground()) {
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Impossibile avviare il servizio microfono",
      )
      return
    }

    recordingGeneration = editorGeneration
    keyboardView?.setState(MicIndicatorState.STARTING)
    if (recorder.start()) {
      keyboardView?.setState(MicIndicatorState.RECORDING)
    } else {
      stopRecordingForeground()
    }
  }

  override fun onRecordingStopRequested() {
    if (recordingGeneration == null) return
    keyboardView?.setState(MicIndicatorState.PROCESSING)
    recorder.stop()
  }

  override fun onSwitchKeyboardRequested() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
      switchToPreviousInputMethod()
    } else {
      requestHideSelf(0)
      Toast.makeText(this, "Seleziona la tastiera dal selettore Android", Toast.LENGTH_SHORT).show()
    }
  }

  override fun onMeter(value: Float) {
    keyboardView?.setVolume(value)
  }

  override fun onRecordingFinished(file: File, durationMs: Long) {
    stopRecordingForeground()
    keyboardView?.setState(MicIndicatorState.PROCESSING, "Trascrizione Groq Cloud")
    cloudTranscriber.transcribe(
      file,
      settingsStore.transcriptionLanguage(),
      object : GroqCloudTranscriber.Listener {
        override fun onSuccess(text: String) {
          file.delete()
          historyStore.append(text)
          metricsStore.record(text, durationMs)
          commitIfEditorStillCurrent(text)
        }

        override fun onFailure(message: String) {
          file.delete()
          recordingGeneration = null
          keyboardView?.setState(MicIndicatorState.ERROR, message)
        }
      },
    )
  }

  override fun onRecordingError(message: String) {
    stopRecordingForeground()
    recordingGeneration = null
    keyboardView?.setState(MicIndicatorState.ERROR, message)
  }

  override fun onDestroy() {
    recorder.shutdown()
    stopRecordingForeground()
    cloudTranscriber.shutdown()
    mainHandler.removeCallbacksAndMessages(null)
    keyboardView = null
    super.onDestroy()
  }

  private fun commitIfEditorStillCurrent(text: String) {
    val targetGeneration = recordingGeneration
    if (targetGeneration == null || targetGeneration != editorGeneration) {
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Il campo attivo è cambiato",
      )
      recordingGeneration = null
      return
    }

    if (isSensitiveField()) {
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Campo protetto: testo non inserito",
      )
      recordingGeneration = null
      return
    }

    val committed = currentInputConnection?.commitText(text, 1) == true
    keyboardView?.setState(
      if (committed) MicIndicatorState.SUCCESS else MicIndicatorState.ERROR,
      if (committed) "Testo inserito" else "Impossibile inserire il testo",
    )
    recordingGeneration = null
    if (committed) {
      mainHandler.postDelayed({ keyboardView?.setState(MicIndicatorState.IDLE) }, 1_200L)
    }
  }

  private fun isSensitiveField(): Boolean {
    val inputType = currentEditorInfo?.inputType ?: return false
    val variation = inputType and InputType.TYPE_MASK_VARIATION
    val inputClass = inputType and InputType.TYPE_MASK_CLASS
    if (inputClass == InputType.TYPE_CLASS_TEXT) {
      return variation == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
        variation == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD ||
        variation == InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
    }
    if (inputClass == InputType.TYPE_CLASS_NUMBER) {
      return variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD
    }
    return inputClass == InputType.TYPE_CLASS_PHONE
  }

  private fun hasMicrophonePermission(): Boolean =
    checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
      android.content.pm.PackageManager.PERMISSION_GRANTED

  private fun openAppSettings() {
    val intent = Intent(
      Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
      Uri.parse("package:$packageName"),
    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    startActivity(intent)
  }

  @Suppress("DEPRECATION")
  private fun startRecordingForeground(): Boolean {
    if (recordingForegroundActive) return true

    return runCatching {
      createRecordingNotificationChannel()
      val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
      val contentIntent = launchIntent?.let {
        PendingIntent.getActivity(
          this,
          0,
          it,
          PendingIntent.FLAG_UPDATE_CURRENT or pendingIntentMutabilityFlag(),
        )
      }
      val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        Notification.Builder(this, RECORDING_CHANNEL_ID)
      } else {
        Notification.Builder(this)
      }
      val notification = builder
        .setSmallIcon(android.R.drawable.ic_btn_speak_now)
        .setContentTitle("Traflix Voice")
        .setContentText("Registrazione in corso")
        .setCategory(Notification.CATEGORY_PROGRESS)
        .setOngoing(true)
        .apply { if (contentIntent != null) setContentIntent(contentIntent) }
        .build()

      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        startForeground(
          RECORDING_NOTIFICATION_ID,
          notification,
          android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
        )
      } else {
        startForeground(RECORDING_NOTIFICATION_ID, notification)
      }
      recordingForegroundActive = true
      true
    }.getOrElse {
      recordingForegroundActive = false
      false
    }
  }

  @Suppress("DEPRECATION")
  private fun stopRecordingForeground() {
    if (!recordingForegroundActive) return
    runCatching { stopForeground(true) }
    recordingForegroundActive = false
  }

  private fun createRecordingNotificationChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val manager = getSystemService(NotificationManager::class.java)
    manager.createNotificationChannel(
      NotificationChannel(
        RECORDING_CHANNEL_ID,
        "Registrazione vocale",
        NotificationManager.IMPORTANCE_LOW,
      ).apply {
        description = "Stato della registrazione Traflix Voice"
        setShowBadge(false)
      },
    )
  }

  private fun pendingIntentMutabilityFlag(): Int =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
      PendingIntent.FLAG_IMMUTABLE
    } else {
      0
    }

  private companion object {
    const val RECORDING_CHANNEL_ID = "traflix_voice_recording"
    const val RECORDING_NOTIFICATION_ID = 7101
  }
}
