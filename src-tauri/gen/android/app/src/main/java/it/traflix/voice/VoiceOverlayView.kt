package it.traflix.voice

import android.view.MotionEvent
import android.view.ViewConfiguration
import android.widget.FrameLayout
import android.widget.Button
import kotlin.math.roundToInt

/** Compact microphone control rendered above the user's existing keyboard. */
class VoiceOverlayView(
  context: android.content.Context,
  private val listener: Listener,
) : FrameLayout(context) {
  private fun dp(value: Int): Int =
    (value * resources.displayMetrics.density).roundToInt()

  interface Listener {
    fun onRecordingStartRequested()
    fun onRecordingStopRequested()
    fun onOverlayMoved(deltaX: Int, deltaY: Int)
    fun onOverlayDragFinished()
    fun onCopyRecoverableText(text: String)
    fun onResetRequested()
  }

  private val indicator = MicIndicatorView(context)
  private val copyButton = Button(context)
  private val runtimeStateStore = VoiceRuntimeStateStore(context)
  private var recordingMode = RecordingMode.TOGGLE
  private var indicatorState = MicIndicatorState.IDLE
  private var recoverableText: String? = null
  private val gesture = VoiceOverlayGesture(ViewConfiguration.get(context).scaledTouchSlop)
  private var activePointerId = MotionEvent.INVALID_POINTER_ID
  private var holdStarted = false
  private val transientStateReset = Runnable {
    if (recoverableText == null &&
      (indicatorState == MicIndicatorState.SUCCESS || indicatorState == MicIndicatorState.ERROR)
    ) {
      listener.onResetRequested()
    }
  }

  init {
    isClickable = true
    isFocusable = false
    indicator.setCompact(true)
    addView(
      indicator,
      LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT),
    )
    indicator.setOnTouchListener { _, event -> handleTouch(event) }
    indicator.setOnClickListener { activateControl() }
    copyButton.text = "Copia"
    copyButton.contentDescription = "Copia la trascrizione non inserita"
    copyButton.textSize = 12f
    copyButton.setPadding(0, 0, 0, 0)
    copyButton.setOnClickListener {
      recoverableText?.let(listener::onCopyRecoverableText)
    }
    addView(
      copyButton,
      LayoutParams(dp(48), dp(48)).apply {
        gravity = android.view.Gravity.TOP or android.view.Gravity.START
      },
    )
    copyButton.visibility = android.view.View.GONE
  }

  fun setRecordingMode(mode: RecordingMode) {
    if (indicatorState == MicIndicatorState.IDLE) recordingMode = mode
  }

  fun setState(state: MicIndicatorState, detail: String? = null) {
    setState(state, detail, null)
  }

  fun setState(
    state: MicIndicatorState,
    detail: String? = null,
    recoverableText: String? = null,
    showRecovery: Boolean = false,
  ) {
    removeCallbacks(transientStateReset)
    indicatorState = state
    this.recoverableText = recoverableText
    if (showRecovery && !recoverableText.isNullOrEmpty()) {
      indicator.visibility = android.view.View.GONE
      copyButton.visibility = android.view.View.VISIBLE
    } else {
      copyButton.visibility = android.view.View.GONE
      indicator.visibility = android.view.View.VISIBLE
      indicator.setIndicatorState(state)
    }
    runtimeStateStore.set(state, detail)
    indicator.contentDescription = when (state) {
      MicIndicatorState.IDLE -> "Avvia dettatura. Trascina per spostare il widget."
      MicIndicatorState.RECORDING -> "Interrompi dettatura"
      else -> detail ?: when (state) {
        MicIndicatorState.STARTING -> "Avvio del microfono"
        MicIndicatorState.PROCESSING -> "Trascrizione in corso"
        MicIndicatorState.SUCCESS -> "Trascrizione inviata"
        MicIndicatorState.ERROR -> "Errore di trascrizione. Tocca per riprovare."
        else -> "Avvia dettatura"
      }
    }
    if (state == MicIndicatorState.SUCCESS || state == MicIndicatorState.ERROR) {
      postDelayed(transientStateReset, TRANSIENT_STATE_DURATION_MS)
    }
  }

  override fun onDetachedFromWindow() {
    removeCallbacks(transientStateReset)
    gesture.cancel()
    activePointerId = MotionEvent.INVALID_POINTER_ID
    if (holdStarted && canStop()) listener.onRecordingStopRequested()
    holdStarted = false
    super.onDetachedFromWindow()
  }

  fun setVolume(value: Float) {
    indicator.setVolume(value)
  }

  private fun handleTouch(event: MotionEvent): Boolean {
    when (event.actionMasked) {
      MotionEvent.ACTION_DOWN -> {
        activePointerId = event.getPointerId(0)
        gesture.begin(event.rawX, event.rawY,
          recordingMode == RecordingMode.TOGGLE && (canStart() || isDismissibleState()))
        holdStarted = recordingMode == RecordingMode.HOLD_TO_SPEAK && canStart()
        if (holdStarted) listener.onRecordingStartRequested()
      }
      MotionEvent.ACTION_MOVE -> {
        if (activePointerId == MotionEvent.INVALID_POINTER_ID) return true
        val delta = gesture.move(event.rawX, event.rawY)
        if (delta != null && !canStop() && indicatorState != MicIndicatorState.PROCESSING) {
          listener.onOverlayMoved(delta.first, delta.second)
        }
      }
      MotionEvent.ACTION_UP -> {
        if (event.getPointerId(event.actionIndex) != activePointerId) return true
        val tapped = gesture.finish()
        if (gesture.dragged) listener.onOverlayDragFinished()
        if (holdStarted) {
          if (canStop()) listener.onRecordingStopRequested()
        } else if (tapped) {
          indicator.performClick()
        }
        holdStarted = false
        activePointerId = MotionEvent.INVALID_POINTER_ID
      }
      MotionEvent.ACTION_CANCEL, MotionEvent.ACTION_POINTER_DOWN -> {
        gesture.cancel()
        if (gesture.dragged) listener.onOverlayDragFinished()
        if (holdStarted && canStop()) listener.onRecordingStopRequested()
        holdStarted = false
        activePointerId = MotionEvent.INVALID_POINTER_ID
      }
    }
    return true
  }

  private fun activateControl() {
    if (canStop()) listener.onRecordingStopRequested()
    else if (isDismissibleState()) listener.onResetRequested()
    else if (canStart()) listener.onRecordingStartRequested()
  }

  private fun canStart(): Boolean = indicatorState == MicIndicatorState.IDLE

  private fun isDismissibleState(): Boolean = indicatorState == MicIndicatorState.SUCCESS ||
    indicatorState == MicIndicatorState.ERROR

  private fun canStop(): Boolean = indicatorState == MicIndicatorState.STARTING ||
    indicatorState == MicIndicatorState.RECORDING

  private companion object {
    const val TRANSIENT_STATE_DURATION_MS = 1_800L
  }
}
