package it.traflix.voice

import android.content.Context

/** Keeps the last native recording state available to the Mobile Hub. */
class VoiceRuntimeStateStore(context: Context) {
  private val preferences = context.applicationContext.getSharedPreferences(
    PREFERENCES_NAME,
    Context.MODE_PRIVATE,
  )

  fun set(state: MicIndicatorState, detail: String? = null) {
    preferences.edit()
      .putString(STATE_KEY, stateValue(state))
      .putString(DETAIL_KEY, detail.orEmpty())
      .apply()
  }

  fun reset() {
    set(MicIndicatorState.IDLE)
  }

  fun snapshot(): Map<String, String> = mapOf(
    "state" to (preferences.getString(STATE_KEY, "idle") ?: "idle"),
    "detail" to (preferences.getString(DETAIL_KEY, "") ?: ""),
  )

  private fun stateValue(state: MicIndicatorState): String = when (state) {
    MicIndicatorState.IDLE -> "idle"
    MicIndicatorState.STARTING -> "starting"
    MicIndicatorState.RECORDING -> "listening"
    MicIndicatorState.PROCESSING -> "processing"
    MicIndicatorState.SUCCESS -> "result"
    MicIndicatorState.ERROR -> "error"
  }

  private companion object {
    const val PREFERENCES_NAME = "voice_runtime_state"
    const val STATE_KEY = "state"
    const val DETAIL_KEY = "detail"
  }
}
