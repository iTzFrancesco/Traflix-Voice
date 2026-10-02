package it.traflix.voice

import android.text.InputType
import org.junit.Assert.assertFalse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceInputSafetyTest {
  @Test
  fun rejectsPasswordAndPhoneEditors() {
    for (variation in listOf(
      InputType.TYPE_TEXT_VARIATION_PASSWORD,
      InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD,
      InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD,
    )) {
      assertTrue(VoiceInputSafety.isSensitive(InputType.TYPE_CLASS_TEXT or variation))
    }
    assertTrue(VoiceInputSafety.isSensitive(
      InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD,
    ))
    assertTrue(VoiceInputSafety.isSensitive(InputType.TYPE_CLASS_PHONE))
  }

  @Test
  fun acceptsNormalTextAndTerminalConnections() {
    assertFalse(VoiceInputSafety.isSensitive(InputType.TYPE_CLASS_TEXT))
    assertFalse(VoiceInputSafety.isSensitive(InputType.TYPE_NULL))
  }

  @Test
  fun rawTerminalConnectionsNeverReceiveLineBreaks() {
    val transcript = "test transcript\r\nsecond line"
    assertEquals("test transcript  second line", VoiceInputSafety.textForEditor(transcript, InputType.TYPE_NULL))
    assertEquals(transcript, VoiceInputSafety.textForEditor(transcript, InputType.TYPE_CLASS_TEXT))
  }
}
