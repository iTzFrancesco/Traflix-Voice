package it.traflix.voice

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceCaptureTailTest {
  @Test
  fun keepsCapturingFor220MillisecondsAfterStop() {
    val tail = VoiceCaptureTail()
    assertTrue(tail.shouldCapture(1_000L))
    assertTrue(tail.requestStop(1_000L))
    assertTrue(tail.shouldCapture(1_219L))
    assertFalse(tail.shouldCapture(1_220L))
  }

  @Test
  fun duplicateStopDoesNotExtendTheTail() {
    val tail = VoiceCaptureTail()
    tail.requestStop(1_000L)
    assertFalse(tail.requestStop(1_100L))
    assertFalse(tail.shouldCapture(1_220L))
  }

  @Test
  fun sessionsHaveIndependentStopDeadlines() {
    val first = VoiceCaptureTail()
    val second = VoiceCaptureTail()
    first.requestStop(1_000L)
    assertFalse(first.shouldCapture(1_220L))
    assertTrue(second.shouldCapture(1_220L))
  }
}
