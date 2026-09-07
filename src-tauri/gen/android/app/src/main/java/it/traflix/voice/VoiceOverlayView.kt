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
    indicatorState = state
    indicator.setIndicatorState(state)
    if (detail != null) indicator.contentDescription = detail
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
}
