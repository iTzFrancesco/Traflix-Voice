package it.traflix.voice

import android.graphics.Color
import android.view.Gravity
import android.view.MotionEvent
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.math.roundToInt

class VoiceKeyboardView(
  private val listener: Listener,
  private val settingsStore: VoiceSettingsStore,
) : LinearLayout(listener.context) {
  interface Listener {
    val context: android.content.Context
    fun onRecordingStartRequested()
    fun onRecordingStopRequested()
    fun onSwitchKeyboardRequested()
  }

  private val indicator = MicIndicatorView(context)
  private val status = TextView(context)
  private var indicatorState = MicIndicatorState.IDLE
  private val transientStateReset = Runnable {
    if (indicatorState == MicIndicatorState.SUCCESS || indicatorState == MicIndicatorState.ERROR) {
      setState(MicIndicatorState.IDLE)
    }
  }

  init {
    orientation = VERTICAL
    gravity = Gravity.CENTER_VERTICAL
    setPadding(dp(12), dp(8), dp(12), dp(8))
    setBackgroundColor(Color.rgb(28, 28, 34))

    status.text = "Traflix Voice · Groq Cloud"
    status.setTextColor(Color.rgb(205, 205, 215))
    status.textSize = 12f
    status.gravity = Gravity.CENTER_VERTICAL
    addView(
      status,
      LayoutParams(LayoutParams.MATCH_PARENT, dp(24)),
    )

    val controls = LinearLayout(context).apply {
      orientation = HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    addView(
      controls,
      LayoutParams(LayoutParams.MATCH_PARENT, dp(64)),
    )

    indicator.setIndicatorState(indicatorState)
    indicator.setOnTouchListener { _, event -> handleMicTouch(event) }
    controls.addView(
      indicator,
      LayoutParams(0, dp(56), 1f).apply {
        marginEnd = dp(8)
      },
    )

    val switchButton = KeyboardSwitchView(context).apply {
      setOnClickListener { listener.onSwitchKeyboardRequested() }
    }
    controls.addView(switchButton, LayoutParams(dp(64), dp(56)))

    refreshMode()
  }

  fun refreshMode() {
    status.text = when (settingsStore.recordingMode()) {
      RecordingMode.HOLD_TO_SPEAK -> "Hold to Speak · Groq Cloud"
      RecordingMode.TOGGLE -> "Tocca per parlare · Groq Cloud"
    }
  }

  fun setState(state: MicIndicatorState, detail: String? = null) {
    removeCallbacks(transientStateReset)
    indicatorState = state
    indicator.setIndicatorState(state)
    if (detail != null) {
      status.text = detail
    } else {
      refreshMode()
    }
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

  private fun handleMicTouch(event: MotionEvent): Boolean {
    val mode = settingsStore.recordingMode()
    when (mode) {
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

  private fun dp(value: Int): Int =
    (value * resources.displayMetrics.density).roundToInt()

  private companion object {
    const val TRANSIENT_STATE_DURATION_MS = 1_800L
  }
}
