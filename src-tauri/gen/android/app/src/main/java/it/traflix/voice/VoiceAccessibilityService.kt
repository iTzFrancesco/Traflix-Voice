package it.traflix.voice

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.ActivityManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Rect
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.SoundPool
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.Gravity
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import java.io.File

/**
 * Shows the Traflix control while the Traflix Voice task remains open in the
 * background. Gboard stays the active input method; this service only owns
 * the compact accessibility overlay and inserts the approved transcription
 * into the currently focused text target.
 */
class VoiceAccessibilityService : AccessibilityService(), VoiceOverlayView.Listener,
  VoiceAudioRecorder.Listener {
  private val mainHandler = Handler(Looper.getMainLooper())
  private lateinit var settingsStore: VoiceSettingsStore
  private lateinit var recorder: VoiceAudioRecorder
  private lateinit var cloudTranscriber: GroqCloudTranscriber
  private lateinit var historyStore: VoiceHistoryStore
  private lateinit var metricsStore: VoiceMetricsStore
  private lateinit var windowManager: WindowManager

  private var overlay: VoiceOverlayView? = null
  private var overlayParams: WindowManager.LayoutParams? = null
  private var focusedEditor: AccessibilityNodeInfo? = null
  private var focusedPackage: String? = null
  private var recordingEditorKey: String? = null
  private var recordingEditorPackage: String? = null
  private var recordingEditorViewId: String? = null
  private var recordingEditorClassName: String? = null
  private var recordingEditorBounds: Rect? = null
  private var recordingForegroundActive = false
  private var feedbackSoundPool: SoundPool? = null
  private var feedbackFallbackPlayer: MediaPlayer? = null
  private val feedbackSoundLock = Any()
  private val loadedFeedbackSounds = mutableSetOf<Int>()
  private var startSoundId = 0
  private var stopSoundId = 0
  private var stopSoundPlayed = false

  private enum class TranscriptionInsertResult {
    INSERTED,
    COPIED_TO_CLIPBOARD,
    FAILED,
  }

  override fun onServiceConnected() {
    super.onServiceConnected()
    Log.i(TAG, "accessibility service connected")
    settingsStore = VoiceSettingsStore(this)
    recorder = VoiceAudioRecorder(this, this)
    cloudTranscriber = GroqCloudTranscriber(this)
    historyStore = VoiceHistoryStore(this)
    metricsStore = VoiceMetricsStore(this)
    windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
    initializeFeedbackSounds()

    serviceInfo = serviceInfo.apply {
      eventTypes = AccessibilityEvent.TYPE_VIEW_FOCUSED or
        AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
        AccessibilityEvent.TYPE_WINDOWS_CHANGED or
        AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED
      feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
      flags = flags or
        AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
        AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
      notificationTimeout = 100
    }
    scheduleOverlayRefresh()
  }

  override fun onAccessibilityEvent(event: AccessibilityEvent?) {
    if (event == null) return
    val eventPackage = event.packageName?.toString()
    val source = event.source

    if (source != null &&
      eventPackage != null &&
      eventPackage != packageName &&
      eventPackage != GBOARD_PACKAGE &&
      isPotentialInputTarget(source)
    ) {
      replaceFocusedEditor(source, eventPackage)
    } else if (
      event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
      eventPackage != null &&
      eventPackage != packageName &&
      eventPackage != GBOARD_PACKAGE &&
      eventPackage != focusedPackage
    ) {
      clearFocusedEditor()
    }

    scheduleOverlayRefresh()
  }

  override fun onInterrupt() {
    Log.w(TAG, "accessibility service interrupted recording=${recordingEditorKey != null}")
    playStopSoundIfNeeded()
    hideOverlay()
    cancelRecording()
  }

  override fun onDestroy() {
    Log.w(TAG, "accessibility service destroyed recording=${recordingEditorKey != null}")
    playStopSoundIfNeeded()
    hideOverlay()
    cancelRecording()
    if (::recorder.isInitialized) recorder.shutdown()
    if (::cloudTranscriber.isInitialized) cloudTranscriber.shutdown()
    releaseFeedbackSounds()
    mainHandler.removeCallbacksAndMessages(null)
    clearFocusedEditor()
    super.onDestroy()
  }

  override fun onRecordingStartRequested() {
    Log.d(TAG, "recording start requested")
    if (!::settingsStore.isInitialized) return
    val editor = findFocusedInputTarget() ?: run {
      setOverlayState(MicIndicatorState.ERROR, "Apri un campo di testo o un terminale")
      return
    }
    if (isSensitiveField(editor)) {
      editor.recycle()
      setOverlayState(MicIndicatorState.ERROR, "Campo protetto")
      return
    }
    if (!hasMicrophonePermission()) {
      editor.recycle()
      setOverlayState(MicIndicatorState.ERROR, "Abilita il microfono nel Mobile Hub")
      openAppSettings()
      return
    }

    recordingEditorKey = editorKey(editor)
    recordingEditorPackage = editor.packageName?.toString() ?: focusedPackage
    recordingEditorViewId = editor.viewIdResourceName
    recordingEditorClassName = editor.className?.toString()
    recordingEditorBounds = Rect().also { editor.getBoundsInScreen(it) }
    Log.i(
      TAG,
      "recording target package=${recordingEditorPackage} " +
        "class=${recordingEditorClassName} viewId=${recordingEditorViewId} " +
        "editable=${editor.isEditable} " +
        "actions=${editor.actionList.joinToString(",") { it.id.toString() }}",
    )
    editor.recycle()
    if (!startRecordingForeground()) {
      recordingEditorKey = null
      setOverlayState(MicIndicatorState.ERROR, "Impossibile avviare il microfono")
      return
    }

    setOverlayState(MicIndicatorState.STARTING)
    if (!recorder.start()) {
      stopRecordingForeground()
      recordingEditorKey = null
    } else {
      stopSoundPlayed = false
      setOverlayState(MicIndicatorState.RECORDING)
      playStartSound()
      Log.i(TAG, "recording started for focused editor")
    }
  }

  override fun onRecordingStopRequested() {
    if (recordingEditorKey == null) return
    Log.d(TAG, "recording stop requested")
    playStopSoundIfNeeded()
    setOverlayState(MicIndicatorState.PROCESSING)
    recorder.stop()
  }

  override fun onMeter(value: Float) {
    overlay?.setVolume(value)
  }

  override fun onRecordingFinished(file: File, durationMs: Long) {
    Log.i(TAG, "recording finished durationMs=$durationMs")
    playStopSoundIfNeeded()
    stopRecordingForeground()
    setOverlayState(MicIndicatorState.PROCESSING, "Trascrizione Groq Cloud")
    cloudTranscriber.transcribe(
      file,
      settingsStore.transcriptionLanguage(),
      object : GroqCloudTranscriber.Listener {
        override fun onSuccess(text: String) {
          Log.i(TAG, "Groq transcription succeeded textChars=${text.length}")
          file.delete()
          val insertionResult = insertIntoFocusedEditor(text)
          Log.i(TAG, "transcription insert result=$insertionResult")
          if (insertionResult != TranscriptionInsertResult.FAILED) {
            historyStore.append(text)
            metricsStore.record(text, durationMs)
            recordingEditorKey = null
            val detail = if (insertionResult == TranscriptionInsertResult.INSERTED) {
              "Testo inserito"
            } else {
              "Copiato negli appunti"
            }
            setOverlayState(MicIndicatorState.SUCCESS, detail)
            mainHandler.postDelayed({ setOverlayState(MicIndicatorState.IDLE) }, 1_200L)
          } else {
            recordingEditorKey = null
            setOverlayState(MicIndicatorState.ERROR, "Impossibile inserire il testo")
          }
        }

        override fun onFailure(message: String) {
          Log.e(TAG, "Groq transcription failed: $message")
          file.delete()
          recordingEditorKey = null
          setOverlayState(MicIndicatorState.ERROR, message)
        }
      },
    )
  }

  override fun onRecordingError(message: String) {
    Log.e(TAG, "recording error: $message")
    playStopSoundIfNeeded()
    stopRecordingForeground()
    recordingEditorKey = null
    setOverlayState(MicIndicatorState.ERROR, message)
  }

  private fun replaceFocusedEditor(source: AccessibilityNodeInfo, packageName: String?) {
    clearFocusedEditor()
    focusedEditor = AccessibilityNodeInfo.obtain(source)
    focusedPackage = packageName
  }

  private fun clearFocusedEditor() {
    focusedEditor?.recycle()
    focusedEditor = null
    focusedPackage = null
  }

  private fun scheduleOverlayRefresh() {
    mainHandler.removeCallbacks(::refreshOverlay)
    mainHandler.postDelayed(::refreshOverlay, OVERLAY_REFRESH_DELAY_MS)
  }

  private fun refreshOverlay() {
    if (!::windowManager.isInitialized || !::settingsStore.isInitialized) {
      hideOverlay()
      return
    }

    if (!isTraflixTaskOpen() && recordingEditorKey == null) {
      hideOverlay()
      return
    }

    if (recordingEditorKey == null && isTraflixActivityForeground()) {
      hideOverlay()
      return
    }

    val view = overlay ?: VoiceOverlayView(this, this).also {
      overlay = it
      it.setRecordingMode(settingsStore.recordingMode())
    }
    val width = dp(40)
    val height = dp(40)
    val params = overlayParams ?: WindowManager.LayoutParams(
      width,
      height,
      WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
      WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
        WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
      android.graphics.PixelFormat.TRANSLUCENT,
    ).also {
      it.gravity = Gravity.TOP or Gravity.START
      overlayParams = it
    }

    val displayBounds = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
      windowManager.maximumWindowMetrics.bounds
    } else {
      Rect(0, 0, resources.displayMetrics.widthPixels, resources.displayMetrics.heightPixels)
    }
    params.x = (displayBounds.right - width - dp(12)).coerceAtLeast(displayBounds.left)
    params.y = (displayBounds.top + (displayBounds.height() - height) / 2)
      .coerceAtLeast(displayBounds.top + dp(4))
    try {
      if (view.parent == null) windowManager.addView(view, params)
      else windowManager.updateViewLayout(view, params)
    } catch (_: Exception) {
      hideOverlay()
    }
  }

  private fun hideOverlay() {
    val view = overlay ?: return
    runCatching { windowManager.removeView(view) }
    overlay = null
    overlayParams = null
  }

  private fun isTraflixTaskOpen(): Boolean = runCatching {
    getSystemService(ActivityManager::class.java).appTasks.any { task ->
      val taskInfo = task.taskInfo
      taskInfo.baseActivity?.packageName == packageName ||
        taskInfo.baseIntent?.component?.packageName == packageName
    }
  }.getOrDefault(false)

  private fun isTraflixActivityForeground(): Boolean = runCatching {
    val activePackage = rootInActiveWindow?.packageName?.toString()
    activePackage == packageName || windows.asSequence()
      .filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION && it.isFocused }
      .mapNotNull { it.root?.packageName?.toString() }
      .any { it == packageName }
  }.getOrDefault(false)

  private fun findFocusedInputTarget(): AccessibilityNodeInfo? = runCatching {
    val current = windows.asSequence()
      .filter { it.type != AccessibilityWindowInfo.TYPE_INPUT_METHOD }
      .sortedByDescending { it.isFocused || it.isActive }
      .mapNotNull { it.root?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) }
      .firstOrNull { isPotentialInputTarget(it) }
    if (current != null) return@runCatching current

    val cached = focusedEditor?.let { AccessibilityNodeInfo.obtain(it) }
    if (cached != null) {
      if (isPotentialInputTarget(cached)) return@runCatching cached
      cached.recycle()
    }
    null
  }.getOrNull()

  private fun isPotentialInputTarget(node: AccessibilityNodeInfo): Boolean {
    val nodePackage = node.packageName?.toString()
    if (nodePackage.isNullOrBlank() || nodePackage == packageName || !node.isVisibleToUser) {
      return false
    }
    if (node.isEditable) return true
    if (!node.isFocused || !node.isFocusable) return false

    val supportsTextAction = node.actionList.any { action ->
      action.id == AccessibilityNodeInfo.ACTION_PASTE ||
        action.id == AccessibilityNodeInfo.ACTION_SET_TEXT
    }
    return supportsTextAction || isTerminalSurface(node)
  }

  private fun isTerminalSurface(node: AccessibilityNodeInfo): Boolean {
    val className = node.className?.toString().orEmpty()
    val viewId = node.viewIdResourceName.orEmpty()
    return className.endsWith("TerminalView") || viewId.endsWith(":id/terminalView")
  }

  private fun insertIntoFocusedEditor(text: String): TranscriptionInsertResult {
    val editor = findFocusedInputTarget() ?: run {
      Log.w(TAG, "transcription insert skipped: no focused input target")
      return TranscriptionInsertResult.FAILED
    }
    val key = editorKey(editor)
    val currentBounds = Rect().also { editor.getBoundsInScreen(it) }
    val currentPackage = editor.packageName?.toString()
    val packageMatches = currentPackage == recordingEditorPackage
    val viewIdMatches = !recordingEditorViewId.isNullOrBlank() &&
      editor.viewIdResourceName == recordingEditorViewId
    val classAndBoundsMatch = recordingEditorViewId.isNullOrBlank() &&
      editor.className?.toString() == recordingEditorClassName &&
      recordingEditorBounds == currentBounds
    if (!packageMatches ||
      (key != recordingEditorKey && !viewIdMatches && !classAndBoundsMatch)
    ) {
      Log.w(
        TAG,
        "transcription insert skipped: focused editor changed " +
          "expectedPackage=$recordingEditorPackage currentPackage=$currentPackage " +
          "packageMatches=$packageMatches viewIdMatches=$viewIdMatches " +
          "classAndBoundsMatch=$classAndBoundsMatch",
      )
      editor.recycle()
      return TranscriptionInsertResult.FAILED
    }

    val clipboard = getSystemService(ClipboardManager::class.java)
    val previous = clipboard.primaryClip
    clipboard.setPrimaryClip(ClipData.newPlainText("Traflix Voice", text))
    val exposesPasteAction = editor.actionList.any { action ->
      action.id == AccessibilityNodeInfo.ACTION_PASTE
    }
    val pasted = editor.performAction(AccessibilityNodeInfo.ACTION_PASTE)
    val terminalSurface = isTerminalSurface(editor)
    Log.d(
      TAG,
      "clipboard paste action result=$pasted exposesPasteAction=$exposesPasteAction " +
        "terminalSurface=$terminalSurface",
    )
    editor.recycle()
    if (pasted) {
      restoreClipboardLater(clipboard, previous)
      return TranscriptionInsertResult.INSERTED
    }
    if (terminalSurface) {
      Log.i(TAG, "terminal target does not accept accessibility paste; transcription left in clipboard")
      return TranscriptionInsertResult.COPIED_TO_CLIPBOARD
    }
    restoreClipboardLater(clipboard, previous)
    return TranscriptionInsertResult.FAILED
  }

  private fun restoreClipboardLater(clipboard: ClipboardManager, previous: ClipData?) {
    mainHandler.postDelayed({
      runCatching {
        if (previous != null) clipboard.setPrimaryClip(previous) else clipboard.clearPrimaryClip()
      }
    }, CLIPBOARD_RESTORE_DELAY_MS)
  }

  private fun editorKey(editor: AccessibilityNodeInfo): String {
    val uniqueId = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) editor.uniqueId else null
    return uniqueId?.takeIf { it.isNotBlank() }
      ?: listOf(editor.packageName, editor.viewIdResourceName, editor.className).joinToString("|")
  }

  private fun isSensitiveField(editor: AccessibilityNodeInfo): Boolean {
    val className = editor.className?.toString().orEmpty()
    val viewId = editor.viewIdResourceName.orEmpty()
    return editor.isPassword ||
      className.contains("password", ignoreCase = true) ||
      viewId.contains("password", ignoreCase = true)
  }

  private fun playStopSoundIfNeeded() {
    if (recordingEditorKey == null || stopSoundPlayed) return
    stopSoundPlayed = true
    playFeedbackSound(stopSoundId)
  }

  private fun initializeFeedbackSounds() {
    releaseFeedbackSounds()
    runCatching {
      val pool = SoundPool.Builder()
        .setMaxStreams(1)
        .setAudioAttributes(feedbackAudioAttributes())
        .build()
      pool.setOnLoadCompleteListener { _, sampleId, status ->
        if (status == 0) {
          synchronized(feedbackSoundLock) { loadedFeedbackSounds.add(sampleId) }
          Log.i(TAG, "feedback sound loaded sampleId=$sampleId")
        } else {
          Log.w(TAG, "feedback sound load failed status=$status")
        }
      }
      feedbackSoundPool = pool
      startSoundId = pool.load(this, R.raw.start, 1)
      stopSoundId = pool.load(this, R.raw.stop, 1)
      val audioManager = getSystemService(AudioManager::class.java)
      Log.i(
        TAG,
        "feedback audio configured stream=accessibility volume=" +
          "${audioManager.getStreamVolume(AudioManager.STREAM_ACCESSIBILITY)}/" +
          "${audioManager.getStreamMaxVolume(AudioManager.STREAM_ACCESSIBILITY)} " +
          "muted=${audioManager.isStreamMute(AudioManager.STREAM_ACCESSIBILITY)}",
      )
    }.onFailure {
      Log.w(TAG, "unable to initialize feedback sounds", it)
      releaseFeedbackSounds()
    }
  }

  private fun releaseFeedbackSounds() {
    feedbackSoundPool?.release()
    feedbackSoundPool = null
    feedbackFallbackPlayer?.release()
    feedbackFallbackPlayer = null
    startSoundId = 0
    stopSoundId = 0
    synchronized(feedbackSoundLock) { loadedFeedbackSounds.clear() }
  }

  private fun playStartSound() {
    playFeedbackSound(startSoundId)
  }

  private fun playFeedbackSound(soundId: Int) {
    if (soundId == 0) {
      Log.w(TAG, "feedback sound skipped: sample id is not initialized")
      return
    }
    val pool = feedbackSoundPool
    val isLoaded = synchronized(feedbackSoundLock) { loadedFeedbackSounds.contains(soundId) }
    if (pool == null || !isLoaded) {
      Log.w(TAG, "feedback sound not ready sampleId=$soundId loaded=$isLoaded")
      playFeedbackSoundWithMediaPlayer(soundId)
      return
    }
    val streamId = pool.play(soundId, FEEDBACK_VOLUME, FEEDBACK_VOLUME, 1, 0, 1f)
    Log.i(TAG, "feedback sound played sampleId=$soundId streamId=$streamId volume=$FEEDBACK_VOLUME")
    if (streamId == 0) playFeedbackSoundWithMediaPlayer(soundId)
  }

  private fun playFeedbackSoundWithMediaPlayer(soundId: Int) {
    val resourceId = when (soundId) {
      startSoundId -> R.raw.start
      stopSoundId -> R.raw.stop
      else -> return
    }
    runCatching {
      feedbackFallbackPlayer?.release()
      val player = MediaPlayer().apply {
        setAudioAttributes(feedbackAudioAttributes())
        setDataSource(this@VoiceAccessibilityService, Uri.parse(
          "android.resource://$packageName/$resourceId",
        ))
        prepare()
      }
      feedbackFallbackPlayer = player
      player.setVolume(FEEDBACK_VOLUME, FEEDBACK_VOLUME)
      player.setOnCompletionListener {
        if (feedbackFallbackPlayer === it) feedbackFallbackPlayer = null
        it.release()
      }
      player.setOnErrorListener { failedPlayer, _, _ ->
        if (feedbackFallbackPlayer === failedPlayer) feedbackFallbackPlayer = null
        failedPlayer.release()
        true
      }
      player.start()
      Log.i(TAG, "feedback sound fallback played resource=$resourceId volume=$FEEDBACK_VOLUME")
    }.onFailure {
      Log.w(TAG, "feedback sound fallback failed resource=$resourceId", it)
    }
  }

  private fun feedbackAudioAttributes(): AudioAttributes = AudioAttributes.Builder()
    .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
    .build()

  private fun hasMicrophonePermission(): Boolean =
    checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
      android.content.pm.PackageManager.PERMISSION_GRANTED

  private fun openAppSettings() {
    startActivity(
      Intent(
        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
        android.net.Uri.parse("package:$packageName"),
      ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
    )
  }

  private fun setOverlayState(state: MicIndicatorState, detail: String? = null) {
    mainHandler.post { overlay?.setState(state, detail) }
  }

  private fun cancelRecording() {
    if (!::recorder.isInitialized) return
    recorder.cancel()
    stopRecordingForeground()
    recordingEditorKey = null
  }

  @Suppress("DEPRECATION")
  private fun startRecordingForeground(): Boolean = runCatching {
    if (recordingForegroundActive) return true
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
  }.getOrElse { false }

  @Suppress("DEPRECATION")
  private fun stopRecordingForeground() {
    if (!recordingForegroundActive) return
    runCatching { stopForeground(true) }
    recordingForegroundActive = false
  }

  private fun createRecordingNotificationChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    getSystemService(NotificationManager::class.java).createNotificationChannel(
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
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0

  private fun dp(value: Int): Int =
    (value * resources.displayMetrics.density).toInt().coerceAtLeast(1)

  private companion object {
    const val TAG = "VoiceAccessibilityService"
    const val GBOARD_PACKAGE = "com.google.android.inputmethod.latin"
    const val RECORDING_CHANNEL_ID = "traflix_voice_recording"
    const val RECORDING_NOTIFICATION_ID = 7102
    const val OVERLAY_REFRESH_DELAY_MS = 180L
    const val CLIPBOARD_RESTORE_DELAY_MS = 800L
    const val FEEDBACK_VOLUME = 0.52f
  }
}
