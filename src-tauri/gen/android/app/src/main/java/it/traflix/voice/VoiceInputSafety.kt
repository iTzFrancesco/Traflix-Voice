package it.traflix.voice

import android.text.InputType

internal object VoiceInputSafety {
  fun textForEditor(text: String, inputType: Int): String =
    if (inputType == InputType.TYPE_NULL) text.replace('\r', ' ').replace('\n', ' ') else text

  fun isSensitive(inputType: Int): Boolean {
    val variation = inputType and InputType.TYPE_MASK_VARIATION
    return when (inputType and InputType.TYPE_MASK_CLASS) {
      InputType.TYPE_CLASS_TEXT -> variation == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
        variation == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD ||
        variation == InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
      InputType.TYPE_CLASS_NUMBER -> variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD
      InputType.TYPE_CLASS_PHONE -> true
      else -> false
    }
  }
}
