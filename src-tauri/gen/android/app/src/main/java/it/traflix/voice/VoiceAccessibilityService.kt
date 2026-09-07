package it.traflix.voice

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.ActivityManager
import android.app.KeyguardManager
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
import android.os.Bundle
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.Choreographer
import android.view.Gravity
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Shows the Traflix control while the Traflix Voice task remains open in the
 * background. Gboard stays the active input method; this service only owns
 * the compact accessibility overlay and inserts the approved transcription
 * into the currently focused text target.
 */
class VoiceAccessibilityService : AccessibilityService(), VoiceOverlayView.Listener,
  VoiceAudioRecorder.Listener {
  private val mainHandler = Handler(Looper.getMainLooper())
  private val persistenceExecutor: ExecutorService = Executors.newSingleThreadExecutor {
    Thread(it, "traflix-voice-persistence").apply { isDaemon = true }
  }
  private val overlayRefreshRunnable = Runnable { refreshOverlay() }
  private lateinit var settingsStore: VoiceSettingsStore
  private lateinit var recorder: VoiceAudioRecorder
  private lateinit var cloudTranscriber: GroqCloudTranscriber
  private lateinit var historyStore: VoiceHistoryStore
  private lateinit var metricsStore: VoiceMetricsStore
  private lateinit var runtimeStateStore: VoiceRuntimeStateStore
  private lateinit var windowManager: WindowManager

  private var overlay: VoiceOverlayView? = null
  private var overlayParams: WindowManager.LayoutParams? = null
  private var overlayMoveFramePosted = false
  private var pendingOverlayX: Int? = null
  private var pendingOverlayY: Int? = null
  private var overlayDragDisplayBounds: Rect? = null
  private val overlayMoveFrameCallback = Choreographer.FrameCallback {
    overlayMoveFramePosted = false
    applyPendingOverlayMove()
  }
  private var focusedEditor: AccessibilityNodeInfo? = null
  private var focusedPackage: String? = null
  private var focusedEditorViewId: String? = null
  private var focusedEditorClassName: String? = null
  private var focusedEditorBounds: Rect? = null
  private var focusedEditorSensitive = false
  private var lastApplicationPackage: String? = null
  private var recordingEditor: AccessibilityNodeInfo? = null
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
    runtimeStateStore = VoiceRuntimeStateStore(this)
    runtimeStateStore.reset()
    windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
    removeRecordingNotification()
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
    try {
      if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED &&
        eventPackage != null &&
        eventPackage != GBOARD_PACKAGE
      ) {
        lastApplicationPackage = eventPackage
      }

      if (source != null &&
        eventPackage != null &&
        eventPackage != packageName &&
        eventPackage != GBOARD_PACKAGE &&
        isPotentialInputTarget(source)
      ) {
        lastApplicationPackage = eventPackage
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
    } finally {
      source?.recycle()
    }
  }

  override fun onInterrupt() {
    Log.w(TAG, "accessibility service interrupted recording=${recordingEditorKey != null}")
    playStopSoundIfNeeded()
    hideOverlay()
    cancelRecording()
  }

  override fun onTaskRemoved(rootIntent: Intent?) {
    Log.i(TAG, "Traflix task removed; cancelling accessibility recording")
    playStopSoundIfNeeded()
    hideOverlay()
    cancelRecording()
    super.onTaskRemoved(rootIntent)
  }

  override fun onDestroy() {
    Log.w(TAG, "accessibility service destroyed recording=${recordingEditorKey != null}")
    playStopSoundIfNeeded()
    hideOverlay()
    cancelRecording()
    if (::recorder.isInitialized) recorder.shutdown()
    if (::cloudTranscriber.isInitialized) cloudTranscriber.shutdown()
    if (::runtimeStateStore.isInitialized) runtimeStateStore.reset()
    persistenceExecutor.shutdown()
    releaseFeedbackSounds()
    mainHandler.removeCallbacksAndMessages(null)
    clearFocusedEditor()
    super.onDestroy()
  }

  override fun onRecordingStartRequested() {
    Log.d(TAG, "recording start requested")
    if (!::settingsStore.isInitialized) return
    if (!hasFocusedInputTarget() && !refreshFocusedInputTargetFromActiveWindow()) {
      setOverlayState(MicIndicatorState.ERROR, "Apri un campo di testo o un terminale")
      return
    }
    if (focusedEditorSensitive) {
      clearFocusedEditor()
      setOverlayState(MicIndicatorState.ERROR, "Campo protetto")
      return
    }
    if (!hasMicrophonePermission()) {
      clearFocusedEditor()
      setOverlayState(MicIndicatorState.ERROR, "Abilita il microfono nel Mobile Hub")
      openAppSettings()
      return
    }

    recordingEditorKey = listOf(focusedPackage, focusedEditorViewId, focusedEditorClassName)
      .joinToString("|")
    recordingEditorPackage = focusedPackage
    recordingEditorViewId = focusedEditorViewId
    recordingEditorClassName = focusedEditorClassName
    recordingEditorBounds = focusedEditorBounds?.let(::Rect)
    clearRecordingEditor()
    recordingEditor = focusedEditor?.let { AccessibilityNodeInfo.obtain(it) }
    Log.i(
      TAG,
      "recording target package=${recordingEditorPackage} " +
        "class=${recordingEditorClassName} viewId=${recordingEditorViewId} " +
        "bounds=${recordingEditorBounds}",
    )
    if (!startRecordingForeground()) {
      clearRecordingEditor()
      recordingEditorKey = null
      setOverlayState(MicIndicatorState.ERROR, "Impossibile avviare il microfono")
      return
    }

    setOverlayState(MicIndicatorState.STARTING)
    if (!recorder.start()) {
      stopRecordingForeground()
      clearRecordingEditor()
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

  override fun onOverlayMoved(deltaX: Int, deltaY: Int) {
    val params = overlayParams ?: return
    val displayBounds = overlayDragDisplayBounds
      ?: currentDisplayBounds().also { overlayDragDisplayBounds = it }
    val width = params.width.coerceAtLeast(1)
    val height = params.height.coerceAtLeast(1)
    val minX = displayBounds.left
    val maxX = (displayBounds.right - width).coerceAtLeast(minX)
    val minY = displayBounds.top
    val maxY = (displayBounds.bottom - height).coerceAtLeast(minY)
    val baseX = pendingOverlayX ?: params.x
    val baseY = pendingOverlayY ?: params.y
    pendingOverlayX = (baseX + deltaX).coerceIn(minX, maxX)
    pendingOverlayY = (baseY + deltaY).coerceIn(minY, maxY)
    if (!overlayMoveFramePosted) {
      overlayMoveFramePosted = true
      Choreographer.getInstance().postFrameCallback(overlayMoveFrameCallback)
    }
  }

  override fun onOverlayDragFinished() {
    flushPendingOverlayMove()
    overlayDragDisplayBounds = null
    val params = overlayParams ?: return
    settingsStore.setOverlayPosition(VoiceOverlayPosition(params.x, params.y))
    Log.d(TAG, "voice overlay position saved x=${params.x} y=${params.y}")
  }

  override fun onMeter(value: Float) {
    overlay?.setVolume(value)
  }

  override fun onRecordingFinished(file: File, durationMs: Long) {
    Log.i(TAG, "recording finished durationMs=$durationMs")
    playStopSoundIfNeeded()
    stopRecordingForeground()
    if (!isTraflixTaskOpen()) {
      Log.i(TAG, "Traflix task closed before transcription; discarding recording")
      file.delete()
      cancelRecording()
      hideOverlay()
      return
    }
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
            persistTranscript(text, durationMs)
            recordingEditorKey = null
            val detail = if (insertionResult == TranscriptionInsertResult.INSERTED) {
              "Testo inserito"
            } else {
              "Copiato negli appunti"
            }
            setOverlayState(MicIndicatorState.SUCCESS, detail)
          } else {
            clearRecordingEditor()
            recordingEditorKey = null
            setOverlayState(MicIndicatorState.ERROR, "Impossibile inserire il testo")
          }
        }

        override fun onFailure(message: String) {
          Log.e(TAG, "Groq transcription failed: $message")
          file.delete()
          clearRecordingEditor()
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
    clearRecordingEditor()
    recordingEditorKey = null
    setOverlayState(MicIndicatorState.ERROR, message)
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

  private fun replaceFocusedEditor(source: AccessibilityNodeInfo, packageName: String?) {
    clearFocusedEditor()
    focusedEditor = AccessibilityNodeInfo.obtain(source)
    focusedPackage = packageName
    focusedEditorViewId = source.viewIdResourceName
    focusedEditorClassName = source.className?.toString()
    focusedEditorBounds = Rect().also { source.getBoundsInScreen(it) }
    focusedEditorSensitive = isSensitiveField(source)
  }

  private fun clearFocusedEditor() {
    focusedEditor?.recycle()
    focusedEditor = null
    focusedPackage = null
    focusedEditorViewId = null
    focusedEditorClassName = null
    focusedEditorBounds = null
    focusedEditorSensitive = false
  }

  private fun scheduleOverlayRefresh(delayMs: Long = OVERLAY_REFRESH_DELAY_MS) {
    mainHandler.removeCallbacks(overlayRefreshRunnable)
    mainHandler.postDelayed(overlayRefreshRunnable, delayMs)
  }

  @Suppress("DEPRECATION")
  private fun refreshOverlay() {
    if (!::windowManager.isInitialized || !::settingsStore.isInitialized) {
      hideOverlay()
      return
    }

    if (!isTraflixTaskOpen()) {
      if (recordingEditorKey != null || recordingForegroundActive) {
        Log.i(TAG, "Traflix task is closed; cancelling recording and foreground notification")
        cancelRecording()
      }
      hideOverlay()
      return
    }

    if (!shouldShowOverlay()) {
      hideOverlay()
      scheduleOverlayRefresh(OVERLAY_REFRESH_HIDDEN_INTERVAL_MS)
      return
    }

    val view = overlay ?: VoiceOverlayView(this, this).also {
      overlay = it
      it.setRecordingMode(settingsStore.recordingMode())
    }
    val width = dp(40)
    val height = dp(40)
    val displayBounds = currentDisplayBounds()
    val savedPosition = settingsStore.overlayPosition()
    val params = overlayParams ?: WindowManager.LayoutParams(
      width,
      height,
      WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
      WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
        WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
        WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED,
      android.graphics.PixelFormat.TRANSLUCENT,
    ).also {
      it.gravity = Gravity.TOP or Gravity.START
      it.x = savedPosition?.x ?: defaultOverlayX(displayBounds, width)
      it.y = savedPosition?.y ?: defaultOverlayY(displayBounds, height)
      overlayParams = it
    }
    val minX = displayBounds.left
    val maxX = (displayBounds.right - width).coerceAtLeast(minX)
    val minY = displayBounds.top
    val maxY = (displayBounds.bottom - height).coerceAtLeast(minY)
    val clampedX = params.x.coerceIn(minX, maxX)
    val clampedY = params.y.coerceIn(minY, maxY)
    val boundsChanged = params.x != clampedX || params.y != clampedY
    if (boundsChanged) {
      params.x = clampedX
      params.y = clampedY
      if (savedPosition != null) {
        settingsStore.setOverlayPosition(VoiceOverlayPosition(clampedX, clampedY))
      }
    }
    try {
      if (view.parent == null) windowManager.addView(view, params)
      else if (boundsChanged) {
        windowManager.updateViewLayout(view, params)
      }
    } catch (_: Exception) {
      hideOverlay()
      scheduleOverlayRefresh()
      return
    }
    mainHandler.removeCallbacks(overlayRefreshRunnable)
    mainHandler.postDelayed(overlayRefreshRunnable, OVERLAY_REFRESH_INTERVAL_MS)
  }

  private fun hideOverlay() {
    if (overlayMoveFramePosted) {
      Choreographer.getInstance().removeFrameCallback(overlayMoveFrameCallback)
    }
    overlayMoveFramePosted = false
    pendingOverlayX = null
    pendingOverlayY = null
    overlayDragDisplayBounds = null
    val view = overlay ?: return
    runCatching { windowManager.removeView(view) }
    overlay = null
    overlayParams = null
  }

  private fun flushPendingOverlayMove() {
    if (overlayMoveFramePosted) {
      Choreographer.getInstance().removeFrameCallback(overlayMoveFrameCallback)
      overlayMoveFramePosted = false
    }
    applyPendingOverlayMove()
  }

  private fun applyPendingOverlayMove() {
    val view = overlay ?: run {
      pendingOverlayX = null
      pendingOverlayY = null
      return
    }
    val params = overlayParams ?: run {
      pendingOverlayX = null
      pendingOverlayY = null
      return
    }
    val nextX = pendingOverlayX ?: return
    val nextY = pendingOverlayY ?: return
    pendingOverlayX = null
    pendingOverlayY = null
    if (params.x == nextX && params.y == nextY) return
    params.x = nextX
    params.y = nextY
    runCatching { windowManager.updateViewLayout(view, params) }
      .onFailure { Log.w(TAG, "unable to move voice overlay", it) }
  }

  @Suppress("DEPRECATION")
  private fun currentDisplayBounds(): Rect = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
    windowManager.maximumWindowMetrics.bounds
  } else {
    Rect(0, 0, resources.displayMetrics.widthPixels, resources.displayMetrics.heightPixels)
  }

  private fun defaultOverlayX(displayBounds: Rect, width: Int): Int =
    (displayBounds.right - width - dp(12)).coerceAtLeast(displayBounds.left)

  private fun defaultOverlayY(displayBounds: Rect, height: Int): Int =
    (displayBounds.top + (displayBounds.height() - height) / 2)
      .coerceAtLeast(displayBounds.top + dp(4))

  private fun isTraflixTaskOpen(): Boolean = runCatching {
    getSystemService(ActivityManager::class.java).appTasks.any { task ->
      val taskInfo = task.taskInfo
      taskInfo.baseActivity?.packageName == packageName ||
        taskInfo.baseIntent?.component?.packageName == packageName
    }
  }.getOrDefault(false)

  private fun isTraflixActivityForeground(): Boolean = runCatching {
    val root = rootInActiveWindow
    try {
      val activePackage = root?.packageName?.toString()
      when {
        activePackage == packageName -> true
        activePackage == GBOARD_PACKAGE -> lastApplicationPackage == packageName
        activePackage.isNullOrBlank() -> lastApplicationPackage == packageName
        else -> false
      }
    } finally {
      root?.recycle()
    }
  }.getOrDefault(lastApplicationPackage == packageName)

  private fun shouldShowOverlay(): Boolean {
    if (isDeviceLocked()) return true
    return !isTraflixActivityForeground()
  }

  private fun isDeviceLocked(): Boolean = runCatching {
    getSystemService(KeyguardManager::class.java).isKeyguardLocked
  }.getOrDefault(false)

  private fun findFocusedInputTarget(): AccessibilityNodeInfo? {
    val cached = focusedEditor ?: return null
    val cachedPackage = focusedPackage ?: return null
    return cached.takeIf { lastApplicationPackage == cachedPackage }
  }

  private fun hasFocusedInputTarget(): Boolean =
    focusedEditor != null &&
      focusedPackage != null &&
      lastApplicationPackage == focusedPackage

  /**
   * Accessibility focus events are not delivered consistently by every
   * editor (Keep can expose a focused EditText without sending a usable
   * source node). Resolve the active input once, at tap time, instead of
   * walking all windows on every accessibility event.
   */
  private fun refreshFocusedInputTargetFromActiveWindow(): Boolean {
    val root = runCatching { rootInActiveWindow }.getOrNull() ?: return false
    var candidate: AccessibilityNodeInfo? = null
    return try {
      val focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return false
      candidate = focused
      val candidatePackage = focused.packageName?.toString()
      if (
        !candidatePackage.isNullOrBlank() &&
        candidatePackage != packageName &&
        candidatePackage != GBOARD_PACKAGE &&
        isPotentialInputTarget(focused)
      ) {
        lastApplicationPackage = candidatePackage
        replaceFocusedEditor(focused, candidatePackage)
        true
      } else {
        false
      }
    } finally {
      candidate?.recycle()
      root.recycle()
    }
  }

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
    val editor = recordingEditor ?: findFocusedInputTarget() ?: run {
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
      clearFocusedEditor()
      return TranscriptionInsertResult.FAILED
    }

    val clipboard = getSystemService(ClipboardManager::class.java)
    val previous = clipboard.primaryClip
    clipboard.setPrimaryClip(ClipData.newPlainText("Traflix Voice", text))
    val terminalSurface = isTerminalSurface(editor)
    val exposesPasteAction = editor.actionList.any { action ->
      action.id == AccessibilityNodeInfo.ACTION_PASTE
    }
    val pasted = editor.performAction(AccessibilityNodeInfo.ACTION_PASTE)
    val exposesSetTextAction = editor.actionList.any { action ->
      action.id == AccessibilityNodeInfo.ACTION_SET_TEXT
    }
    val setText = if (!pasted && terminalSurface && exposesSetTextAction) {
      Bundle().apply {
        putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
      }.let { arguments ->
        editor.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
      }
    } else {
      false
    }
    Log.d(
      TAG,
      "clipboard paste action result=$pasted exposesPasteAction=$exposesPasteAction " +
        "setTextActionResult=$setText exposesSetTextAction=$exposesSetTextAction " +
        "terminalSurface=$terminalSurface",
    )
    clearFocusedEditor()
    clearRecordingEditor()
    if (pasted || setText) {
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
    if (::runtimeStateStore.isInitialized) runtimeStateStore.set(state, detail)
    val update = Runnable { overlay?.setState(state, detail) }
    if (Looper.myLooper() == Looper.getMainLooper()) update.run() else mainHandler.post(update)
  }

  private fun cancelRecording() {
    if (::recorder.isInitialized) recorder.cancel()
    if (::cloudTranscriber.isInitialized) cloudTranscriber.cancel()
    stopRecordingForeground()
    clearRecordingEditor()
    recordingEditorKey = null
    recordingEditorPackage = null
    recordingEditorViewId = null
    recordingEditorClassName = null
    recordingEditorBounds = null
  }

  private fun clearRecordingEditor() {
    recordingEditor?.recycle()
    recordingEditor = null
  }

  @Suppress("DEPRECATION")
  private fun startRecordingForeground(): Boolean = runCatching {
    if (recordingForegroundActive) return true
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
    removeRecordingNotification()
    false
  }

  @Suppress("DEPRECATION")
  private fun stopRecordingForeground() {
    runCatching {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
        stopForeground(android.app.Service.STOP_FOREGROUND_REMOVE)
      } else {
        stopForeground(true)
      }
    }.onFailure {
      Log.w(TAG, "unable to stop recording foreground service", it)
    }
    recordingForegroundActive = false
    removeRecordingNotification()
  }

  private fun removeRecordingNotification() {
    runCatching {
      getSystemService(NotificationManager::class.java).cancel(RECORDING_NOTIFICATION_ID)
    }.onFailure {
      Log.w(TAG, "unable to clear recording notification", it)
    }
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
    const val OVERLAY_REFRESH_HIDDEN_INTERVAL_MS = 2_500L
    const val OVERLAY_REFRESH_INTERVAL_MS = 750L
    const val CLIPBOARD_RESTORE_DELAY_MS = 800L
    const val FEEDBACK_VOLUME = 0.52f
  }
}
