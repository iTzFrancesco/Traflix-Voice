package it.traflix.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceOverlayGestureTest {
  @Test
  fun smallFingerJitterRemainsATap() {
    val gesture = VoiceOverlayGesture(8)
    gesture.begin(100f, 100f, true)
    assertNull(gesture.move(103f, 102f))
    assertTrue(gesture.finish())
  }

  @Test
  fun gradualMovementIsMeasuredFromTheOriginalPress() {
    val gesture = VoiceOverlayGesture(8)
    gesture.begin(100f, 100f, true)
    assertNull(gesture.move(104f, 100f))
    assertEquals(9 to 0, gesture.move(109f, 100f))
    assertTrue(gesture.dragged)
    assertFalse(gesture.finish())
  }

  @Test
  fun movementDuringDictationNeitherDragsNorBecomesAStopTap() {
    val gesture = VoiceOverlayGesture(8)
    gesture.begin(100f, 100f, false)
    assertNull(gesture.move(130f, 100f))
    assertFalse(gesture.dragged)
    assertFalse(gesture.finish())
  }

  @Test
  fun cancelledGesturesCannotClickOrMove() {
    val gesture = VoiceOverlayGesture(8)
    gesture.begin(100f, 100f, true)
    gesture.cancel()
    assertNull(gesture.move(130f, 100f))
    assertFalse(gesture.finish())
  }
}
