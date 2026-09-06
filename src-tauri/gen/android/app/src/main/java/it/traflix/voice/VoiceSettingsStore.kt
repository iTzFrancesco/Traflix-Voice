package it.traflix.voice

import android.content.Context

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

  private companion object {
    const val PREFERENCES_NAME = "voice_runtime"
    const val RECORDING_MODE_KEY = "recording_mode"
    const val LANGUAGE_KEY = "transcription_language"
  }
}
