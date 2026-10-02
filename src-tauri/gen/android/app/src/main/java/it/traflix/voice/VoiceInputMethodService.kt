package it.traflix.voice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.inputmethodservice.InputMethodService
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import java.io.File
import java.lang.ref.WeakReference
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class VoiceInputMethodService : InputMethodService(), VoiceKeyboardView.Listener,
  VoiceAudioRecorder.Listener {
  override val context
    get() = this

  private val mainHandler = Handler(Looper.getMainLooper())
  private val persistenceExecutor: ExecutorService = Executors.newSingleThreadExecutor {
    Thread(it, "traflix-voice-persistence").apply { isDaemon = true }
  }
  private lateinit var settingsStore: VoiceSettingsStore
  private lateinit var recorder: VoiceAudioRecorder
  private lateinit var cloudTranscriber: GroqCloudTranscriber
  private lateinit var historyStore: VoiceHistoryStore
  private lateinit var metricsStore: VoiceMetricsStore
  private lateinit var runtimeStateStore: VoiceRuntimeStateStore
  private var keyboardView: VoiceKeyboardView? = null
  private var currentEditorInfo: EditorInfo? = null
  private var editorGeneration = 0L
  private var recordingGeneration: Long? = null
  private var transcriptionPending = false
  private var recordingForegroundActive = false

  override fun onCreate() {
    super.onCreate()
    settingsStore = VoiceSettingsStore(this)
    recorder = VoiceAudioRecorder(this, this)
    cloudTranscriber = GroqCloudTranscriber(this)
    historyStore = VoiceHistoryStore(this)
    metricsStore = VoiceMetricsStore(this)
    runtimeStateStore = VoiceRuntimeStateStore(this)
    runtimeStateStore.reset()
    removeRecordingNotification()
  }

  override fun onStartInput(attribute: EditorInfo?, restarting: Boolean) {
    super.onStartInput(attribute, restarting)
    val keepCompletedRecordingPending = transcriptionPending
    if (!keepCompletedRecordingPending) cloudTranscriber.cancel()
    if (recordingGeneration != null && !keepCompletedRecordingPending) {
      recorder.cancel()
      stopRecordingForeground()
      keyboardView?.setState(MicIndicatorState.IDLE)
    }
    currentEditorInfo = attribute
    editorGeneration += 1
    activeService = WeakReference(this)
    if (!keepCompletedRecordingPending) recordingGeneration = null
    keyboardView?.refreshMode()
  }

  override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
    super.onStartInputView(info, restarting)
    currentEditorInfo = info ?: currentEditorInfo
    keyboardView?.refreshMode()
  }

  override fun onFinishInput() {
    editorGeneration += 1
    val keepCompletedTranscription = transcriptionPending && VoiceOverlayVisibility.isDeviceAvailable(this)
    // Retain a stopped recording or pending result across editor changes,
    // but never send it to the replacement editor.
    if (!keepCompletedTranscription) {
      transcriptionPending = false
      cloudTranscriber.cancel()
      recorder.cancel()
      recordingGeneration = null
      keyboardView?.setState(MicIndicatorState.IDLE)
    }
    if (!keepCompletedTranscription) stopRecordingForeground()
    currentEditorInfo = null
    super.onFinishInput()
  }

  override fun onCreateInputView(): View {
    return VoiceKeyboardView(this, settingsStore).also { keyboardView = it }
  }

  override fun onRecordingStartRequested() {
    if (recordingGeneration != null || transcriptionPending) return
    if (!VoiceOverlayVisibility.isDeviceAvailable(this)) return
    if (currentEditorInfo == null || currentInputConnection == null) {
      keyboardView?.setState(MicIndicatorState.ERROR, "Apri un campo di testo o il terminale")
      return
    }
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
    transcriptionPending = true
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

  override fun onCopyRecoverableText(text: String) {
    copyRecoverableText(text)
  }

  override fun onMeter(value: Float) {
    keyboardView?.setVolume(value)
  }

  override fun onRecordingFinished(file: File, durationMs: Long) {
    stopRecordingForeground()
    if (!VoiceOverlayVisibility.isDeviceAvailable(this)) {
      file.delete()
      transcriptionPending = false
      recordingGeneration = null
      keyboardView?.setState(MicIndicatorState.IDLE)
      return
    }
    transcriptionPending = true
    keyboardView?.setState(MicIndicatorState.PROCESSING, "Trascrizione Groq Cloud")
    cloudTranscriber.transcribe(
      file,
      settingsStore.transcriptionLanguage(),
      object : GroqCloudTranscriber.Listener {
        override fun onSuccess(text: String) {
          file.delete()
          transcriptionPending = false
          persistTranscript(text, durationMs)
          commitIfEditorStillCurrent(text)
        }

        override fun onFailure(message: String) {
          file.delete()
          transcriptionPending = false
          recordingGeneration = null
          keyboardView?.setState(MicIndicatorState.ERROR, message)
        }
      },
    )
  }

  override fun onRecordingError(message: String) {
    cloudTranscriber.cancel()
    stopRecordingForeground()
    transcriptionPending = false
    recordingGeneration = null
    keyboardView?.setState(MicIndicatorState.ERROR, message)
  }

  override fun onDestroy() {
    editorGeneration += 1
    currentEditorInfo = null
    if (activeService?.get() === this) activeService = null
    transcriptionPending = false
    recorder.shutdown()
    stopRecordingForeground()
    cloudTranscriber.shutdown()
    runtimeStateStore.reset()
    persistenceExecutor.shutdown()
    mainHandler.removeCallbacksAndMessages(null)
    keyboardView = null
    super.onDestroy()
  }

  private fun externalEditorIdentity(): VoiceEditorIdentity? {
    if (!VoiceOverlayVisibility.isDeviceAvailable(this)) return null
    val editor = currentEditorInfo ?: return null
    val packageName = editor.packageName?.takeIf { it.isNotBlank() } ?: return null
    if (isSensitiveField() || currentInputConnection == null ||
      recordingGeneration != null || transcriptionPending
    ) return null
    return VoiceEditorIdentity(packageName, editorGeneration)
  }

  override fun onTaskRemoved(rootIntent: Intent?) {
    cloudTranscriber.cancel()
    recorder.cancel()
    stopRecordingForeground()
    transcriptionPending = false
    recordingGeneration = null
    keyboardView?.setState(MicIndicatorState.IDLE)
    super.onTaskRemoved(rootIntent)
  }

  private fun persistTranscript(text: String, durationMs: Long) {
    runCatching {
      persistenceExecutor.execute {
        runCatching { historyStore.append(text) }
          .onFailure { Log.w(TAG, "unable to persist transcription history", it) }
        runCatching { metricsStore.record(text, durationMs) }
          .onFailure { Log.w(TAG, "unable to persist transcription metrics", it) }
      }
    }.onFailure {
      Log.w(TAG, "unable to schedule transcription persistence", it)
    }
  }

  private fun commitIfEditorStillCurrent(text: String) {
    val targetGeneration = recordingGeneration
    if (!VoiceOverlayVisibility.isDeviceAvailable(this) || isSensitiveField()) {
      recordingGeneration = null
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Campo protetto · testo salvato in Cronologia",
      )
      return
    }

    if (targetGeneration == null || targetGeneration != editorGeneration) {
      recordingGeneration = null
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Campo cambiato · copia testo",
        recoverableText = text,
      )
      return
    }

    val sinkText = VoiceInputSafety.textForEditor(text, currentEditorInfo?.inputType ?: 0)
    val committed = currentInputConnection?.commitText(sinkText, 1) == true
    recordingGeneration = null
    keyboardView?.setState(
      if (committed) MicIndicatorState.SUCCESS else MicIndicatorState.ERROR,
      if (committed) "Testo inserito" else "Inserimento non riuscito · copia testo",
      recoverableText = if (committed) null else text,
    )
  }

  fun copyRecoverableText(text: String) {
    if (!VoiceOverlayVisibility.isDeviceAvailable(this) || isSensitiveField()) {
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Campo protetto · testo salvato in Cronologia",
      )
      return
    }

    runCatching {
      getSystemService(ClipboardManager::class.java)
        .setPrimaryClip(ClipData.newPlainText("Traflix Voice", text))
      keyboardView?.setState(MicIndicatorState.SUCCESS, "Testo copiato")
    }.onFailure {
      Log.w(TAG, "unable to copy recoverable transcript", it)
      keyboardView?.setState(
        MicIndicatorState.ERROR,
        "Impossibile copiare il testo",
        recoverableText = text,
      )
    }
  }

  private fun isSensitiveField(): Boolean {
    val inputType = currentEditorInfo?.inputType ?: return false
    return VoiceInputSafety.isSensitive(inputType)
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
      removeRecordingNotification()
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

      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
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
      removeRecordingNotification()
      false
    }
  }

  @Suppress("DEPRECATION")
  private fun stopRecordingForeground() {
    runCatching {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
        stopForeground(android.app.Service.STOP_FOREGROUND_REMOVE)
      } else {
        stopForeground(true)
      }
    }
    recordingForegroundActive = false
    removeRecordingNotification()
  }

  private fun removeRecordingNotification() {
    runCatching {
      getSystemService(NotificationManager::class.java).cancel(RECORDING_NOTIFICATION_ID)
    }
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

  companion object {
    private var activeService: WeakReference<VoiceInputMethodService>? = null

    internal fun captureTranscriptTarget(expectedPackage: String?): VoiceTranscriptTarget? {
      if (Looper.myLooper() != Looper.getMainLooper()) return null
      val reference = activeService ?: return null
      val service = reference.get() ?: return null
      val identity = service.externalEditorIdentity() ?: return null
      val inputType = service.currentEditorInfo?.inputType ?: 0
      if (expectedPackage != null && identity.packageName != expectedPackage) return null
      return VoiceTranscriptTarget(
        identity,
        { reference.get()?.externalEditorIdentity() },
        { text ->
          val sinkText = VoiceInputSafety.textForEditor(text, inputType)
          reference.get()?.currentInputConnection?.commitText(sinkText, 1) == true
        },
      )
    }

    private const val TAG = "VoiceInputMethodService"
    private const val RECORDING_CHANNEL_ID = "traflix_voice_recording"
    private const val RECORDING_NOTIFICATION_ID = 7101
  }
}
