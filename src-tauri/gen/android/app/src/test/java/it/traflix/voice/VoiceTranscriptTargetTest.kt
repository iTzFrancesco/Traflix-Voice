package it.traflix.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceTranscriptTargetTest {
  @Test
  fun commitsOnceToTheCapturedEditorWithoutAddingEnter() {
    val identity = VoiceEditorIdentity("test.terminal", 1L)
    val inserted = mutableListOf<String>()
    val target = VoiceTranscriptTarget(identity, { identity }) { inserted.add(it) }
    assertTrue(target.commit("test transcript"))
    assertFalse(target.commit("test transcript"))
    assertEquals(listOf("test transcript"), inserted)
  }

  @Test
  fun refusesAnotherAppAnotherEditorAndUnavailableConnections() {
    val identity = VoiceEditorIdentity("test.terminal", 1L)
    for (current in listOf(
      VoiceEditorIdentity("test.other", 1L),
      VoiceEditorIdentity("test.terminal", 2L),
      null,
    )) {
      var called = false
      val target = VoiceTranscriptTarget(identity, { current }) { called = true; true }
      assertFalse(target.commit("test transcript"))
      assertFalse(called)
    }
  }

  @Test
  fun connectionFailuresReturnFalseForRecovery() {
    val identity = VoiceEditorIdentity("test.terminal", 1L)
    val target = VoiceTranscriptTarget(identity, { identity }) { error("connection closed") }
    assertFalse(target.commit("test transcript"))
  }

  @Test
  fun disappearingEditorReturnsFalseForRecovery() {
    val identity = VoiceEditorIdentity("test.terminal", 1L)
    var called = false
    val target = VoiceTranscriptTarget(identity, { error("editor closed") }) { called = true; true }
    assertFalse(target.commit("test transcript"))
    assertFalse(called)
  }
}
