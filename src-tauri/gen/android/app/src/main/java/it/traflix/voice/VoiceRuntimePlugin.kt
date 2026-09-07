package it.traflix.voice

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.Plugin

@InvokeArg
class AndroidSettingsArgs {
  var screen: String? = null
}

@InvokeArg
class RecordingModeArgs {
  var mode: String? = null
}

@InvokeArg
class GroqApiKeyArgs {
  var apiKey: String? = null
}

@InvokeArg
class LanguageArgs {
  var language: String? = null
}

@TauriPlugin
class VoiceRuntimePlugin(private val activity: Activity) : Plugin(activity) {
  @Command
  fun openAndroidSettings(invoke: Invoke) {
    try {
      val screen = invoke.parseArgs(AndroidSettingsArgs::class.java).screen
        ?.trim()
        .orEmpty()

      activity.runOnUiThread {
        try {
          when (screen) {
            "microphone" -> openPermissionOrSettings(
              Manifest.permission.RECORD_AUDIO,
              MICROPHONE_PERMISSION_REQUEST_CODE,
            )
            "notifications" -> if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
              openPermissionOrSettings(
                Manifest.permission.POST_NOTIFICATIONS,
                NOTIFICATION_PERMISSION_REQUEST_CODE,
              )
            } else {
              openSettings(screen)
            }
            else -> openSettings(screen)
          }
          invoke.resolve()
        } catch (error: Exception) {
          Log.e(TAG, "openAndroidSettings failed on the UI thread", error)
          invoke.reject(error.message ?: error.javaClass.simpleName ?: "Impossibile aprire le impostazioni Android")
        }
      }
    } catch (error: Exception) {
      Log.e(TAG, "openAndroidSettings failed before dispatch", error)
      invoke.reject(error.message ?: error.javaClass.simpleName ?: "Impossibile aprire le impostazioni Android")
    }
  }

  @Command
  fun setRecordingMode(invoke: Invoke) {
    val args = invoke.parseArgs(RecordingModeArgs::class.java)
    val mode = if (args.mode == "hold_to_speak") {
      RecordingMode.HOLD_TO_SPEAK
    } else {
      RecordingMode.TOGGLE
    }
    VoiceSettingsStore(activity).setRecordingMode(mode)
    invoke.resolveObject(mapOf("mode" to mode.name.lowercase()))
  }

  @Command
  fun getRecordingMode(invoke: Invoke) {
    invoke.resolveObject(
      mapOf("mode" to VoiceSettingsStore(activity).recordingMode().name.lowercase()),
    )
  }

  @Command
  fun setGroqApiKey(invoke: Invoke) {
    val args = invoke.parseArgs(GroqApiKeyArgs::class.java)
    VoiceSecretsStore(activity).setGroqApiKey(args.apiKey.orEmpty())
    invoke.resolve()
  }

  @Command
  fun setTranscriptionLanguage(invoke: Invoke) {
    val args = invoke.parseArgs(LanguageArgs::class.java)
    val language = args.language?.trim().takeUnless { it.isNullOrEmpty() } ?: "it"
    VoiceSettingsStore(activity).setTranscriptionLanguage(language)
    invoke.resolve()
  }

  private fun openPermissionOrSettings(permission: String, requestCode: Int) {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
      activity.checkSelfPermission(permission) != PackageManager.PERMISSION_GRANTED
    ) {
      activity.requestPermissions(arrayOf(permission), requestCode)
      return
    }

    openSettings("app")
  }

  private fun openSettings(screen: String?) {
    val intent = settingsIntent(screen).addFlags(SETTINGS_INTENT_FLAGS)

    try {
      if (intent.resolveActivity(activity.packageManager) != null) {
        activity.startActivity(intent)
      } else {
        activity.startActivity(appDetailsIntent().addFlags(SETTINGS_INTENT_FLAGS))
      }
    } catch (_: ActivityNotFoundException) {
      activity.startActivity(appDetailsIntent().addFlags(SETTINGS_INTENT_FLAGS))
    }
  }

  private fun settingsIntent(screen: String?): Intent = when (screen) {
    "input_method" -> Intent(Settings.ACTION_INPUT_METHOD_SETTINGS)
    "accessibility" -> Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
    "notifications" -> Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
      putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName)
    }
    "battery" -> Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
    "microphone", "app" -> appDetailsIntent()
    else -> appDetailsIntent()
  }

  private fun appDetailsIntent(): Intent = Intent(
    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
    Uri.parse("package:${activity.packageName}"),
  )

  private companion object {
    const val TAG = "VoiceRuntimePlugin"
    const val MICROPHONE_PERMISSION_REQUEST_CODE = 4101
    const val NOTIFICATION_PERMISSION_REQUEST_CODE = 4102
    val SETTINGS_INTENT_FLAGS =
      Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
  }
}
