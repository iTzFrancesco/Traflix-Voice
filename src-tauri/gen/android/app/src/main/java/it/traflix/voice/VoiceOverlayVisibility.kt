package it.traflix.voice

import android.app.KeyguardManager
import android.content.Context
import android.os.PowerManager

internal object VoiceOverlayVisibility {
  fun isDeviceAvailable(context: Context): Boolean = runCatching {
    val keyguard = context.getSystemService(KeyguardManager::class.java)
    isDeviceAvailable(
      context.getSystemService(PowerManager::class.java).isInteractive,
      keyguard.isKeyguardLocked,
      keyguard.isDeviceLocked,
    )
  }.getOrDefault(false)

  fun isDeviceAvailable(
    screenInteractive: Boolean,
    keyguardLocked: Boolean,
    deviceLocked: Boolean,
  ): Boolean = screenInteractive && !keyguardLocked && !deviceLocked
}
