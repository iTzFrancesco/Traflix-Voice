package it.traflix.voice

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceOverlayVisibilityTest {
  @Test
  fun requiresAnInteractiveUnlockedDevice() {
    for (interactive in listOf(false, true)) {
      for (keyguardLocked in listOf(false, true)) {
        for (deviceLocked in listOf(false, true)) {
          val available = VoiceOverlayVisibility.isDeviceAvailable(
            interactive, keyguardLocked, deviceLocked,
          )
          if (interactive && !keyguardLocked && !deviceLocked) {
            assertTrue(available)
          } else {
            assertFalse(available)
          }
        }
      }
    }
  }
}
