package it.traflix.voice

import android.view.MotionEvent
import android.view.ViewConfiguration
import android.widget.FrameLayout
import kotlin.math.hypot
import kotlin.math.roundToInt

/** Compact microphone control rendered above the user's existing keyboard. */
class VoiceOverlayView(
  context: android.content.Context,
  private val listener: Listener,
) : FrameLayout(context) {
  interface Listener {
    fun onRecordingStartRequested()
    fun onRecordingStopRequested()
    fun onOverlayMoved(deltaX: Int, deltaY: Int)
    fun onOverlayDragFinished()
  }

  private val indicator = MicIndicatorView(context)
  private var recordingMode = RecordingMode.TOGGLE
  private var indicatorState = MicIndicatorState.IDLE
  private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop
  private var lastRawX = 0f
  private var lastRawY = 0f
  private var dragging = false
  private val transientStateReset = Runnable {
    if (indicatorState == MicIndicatorState.SUCCESS || indicatorState == MicIndicatorState.ERROR) {
      setState(MicIndicatorState.IDLE)
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
  }

  fun setRecordingMode(mode: RecordingMode) {
    recordingMode = mode
  }

  fun setState(state: MicIndicatorState, detail: String? = null) {
    removeCallbacks(transientStateReset)
    indicatorState = state
    indicator.setIndicatorState(state)
    if (detail != null) indicator.contentDescription = detail
    if (state == MicIndicatorState.SUCCESS || state == MicIndicatorState.ERROR) {
      postDelayed(transientStateReset, TRANSIENT_STATE_DURATION_MS)
    }
  }

  override fun onDetachedFromWindow() {
    removeCallbacks(transientStateReset)
    super.onDetachedFromWindow()
  }

  fun setVolume(value: Float) {
    indicator.setVolume(value)
  }

  private fun handleTouch(event: MotionEvent): Boolean {
    when (recordingMode) {
      RecordingMode.HOLD_TO_SPEAK -> when (event.actionMasked) {
        MotionEvent.ACTION_DOWN -> {
          dragging = false
          if (isDismissibleState()) {
            setState(MicIndicatorState.IDLE)
          } else if (canStart()) {
            listener.onRecordingStartRequested()
          }
          return true
        }
        MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
          if (canStop()) listener.onRecordingStopRequested()
          dragging = false
          return true
        }
      }
      RecordingMode.TOGGLE -> when (event.actionMasked) {
        MotionEvent.ACTION_DOWN -> {
          lastRawX = event.rawX
          lastRawY = event.rawY
          dragging = false
          return true
        }
        MotionEvent.ACTION_MOVE -> {
          if (!dragging && hypot(
              event.rawX - lastRawX,
              event.rawY - lastRawY,
            ) >= touchSlop
          ) {
            dragging = true
          }
          if (dragging) {
            val deltaX = (event.rawX - lastRawX).roundToInt()
            val deltaY = (event.rawY - lastRawY).roundToInt()
            if (deltaX != 0 || deltaY != 0) listener.onOverlayMoved(deltaX, deltaY)
            lastRawX = event.rawX
            lastRawY = event.rawY
          }
          return true
        }
        MotionEvent.ACTION_UP -> {
          if (dragging) {
            listener.onOverlayDragFinished()
          } else if (canStop()) {
            listener.onRecordingStopRequested()
          } else if (isDismissibleState()) {
            setState(MicIndicatorState.IDLE)
          } else if (canStart()) {
            listener.onRecordingStartRequested()
          }
          dragging = false
          return true
        }
        MotionEvent.ACTION_CANCEL -> {
          if (dragging) listener.onOverlayDragFinished()
          dragging = false
          return true
        }
      }
    }
    return true
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
