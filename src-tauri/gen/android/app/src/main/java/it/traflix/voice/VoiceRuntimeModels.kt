package it.traflix.voice

enum class RecordingMode {
  HOLD_TO_SPEAK,
  TOGGLE;

  companion object {
    fun fromStoredValue(value: String?): RecordingMode =
      if (value == HOLD_TO_SPEAK.name) HOLD_TO_SPEAK else TOGGLE
  }
}

enum class MicIndicatorState {
  IDLE,
  STARTING,
  RECORDING,
  PROCESSING,
  SUCCESS,
  ERROR,
}
