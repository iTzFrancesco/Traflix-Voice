package it.traflix.voice

import android.view.MotionEvent
import android.widget.FrameLayout

/** Compact microphone control rendered above the user's existing keyboard. */
class VoiceOverlayView(
  context: android.content.Context,
  private val listener: Listener,
) : FrameLayout(context) {
  interface Listener {
    fun onRecordingStartRequested()
    fun onRecordingStopRequested()
  }

  private val indicator = MicIndicatorView(context)
  private var recordingMode = RecordingMode.TOGGLE
  private var indicatorState = MicIndicatorState.IDLE
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
          if (canStart()) listener.onRecordingStartRequested()
          return true
        }
        MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
          if (canStop()) listener.onRecordingStopRequested()
          return true
        }
      }
      RecordingMode.TOGGLE -> if (event.actionMasked == MotionEvent.ACTION_UP) {
        if (canStop()) listener.onRecordingStopRequested()
        else if (canStart()) listener.onRecordingStartRequested()
        return true
      }
    }
    return true
  }

  private fun canStart(): Boolean = indicatorState == MicIndicatorState.IDLE ||
    indicatorState == MicIndicatorState.SUCCESS ||
    indicatorState == MicIndicatorState.ERROR

  private fun canStop(): Boolean = indicatorState == MicIndicatorState.STARTING ||
    indicatorState == MicIndicatorState.RECORDING

  private companion object {
    const val TRANSIENT_STATE_DURATION_MS = 1_800L
  }
}
