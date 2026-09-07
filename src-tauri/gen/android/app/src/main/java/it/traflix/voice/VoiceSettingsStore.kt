package it.traflix.voice

import android.content.Context

data class VoiceOverlayPosition(
  val x: Int,
  val y: Int,
)

class VoiceSettingsStore(context: Context) {
  private val preferences = context.applicationContext.getSharedPreferences(
    PREFERENCES_NAME,
    Context.MODE_PRIVATE,
  )

  fun recordingMode(): RecordingMode =
    RecordingMode.fromStoredValue(preferences.getString(RECORDING_MODE_KEY, null))

  fun setRecordingMode(mode: RecordingMode) {
    preferences.edit().putString(RECORDING_MODE_KEY, mode.name).apply()
  }

  fun transcriptionLanguage(): String =
    preferences.getString(LANGUAGE_KEY, "it") ?: "it"

  fun setTranscriptionLanguage(language: String) {
    preferences.edit().putString(LANGUAGE_KEY, language).apply()
  }

  fun overlayPosition(): VoiceOverlayPosition? {
    if (!preferences.contains(OVERLAY_X_KEY) || !preferences.contains(OVERLAY_Y_KEY)) {
      return null
    }
    return VoiceOverlayPosition(
      x = preferences.getInt(OVERLAY_X_KEY, 0),
      y = preferences.getInt(OVERLAY_Y_KEY, 0),
    )
  }

  fun setOverlayPosition(position: VoiceOverlayPosition) {
    preferences.edit()
      .putInt(OVERLAY_X_KEY, position.x)
      .putInt(OVERLAY_Y_KEY, position.y)
      .apply()
  }

  private companion object {
    const val PREFERENCES_NAME = "voice_runtime"
    const val RECORDING_MODE_KEY = "recording_mode"
    const val LANGUAGE_KEY = "transcription_language"
    const val OVERLAY_X_KEY = "overlay_x"
    const val OVERLAY_Y_KEY = "overlay_y"
  }
}
