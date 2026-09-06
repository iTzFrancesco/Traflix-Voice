package it.traflix.voice

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.provider.Settings
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
    val args = invoke.parseArgs(AndroidSettingsArgs::class.java)
    val intent = settingsIntent(args.screen)

    try {
      activity.startActivity(intent)
      invoke.resolve()
    } catch (_: ActivityNotFoundException) {
      try {
        activity.startActivity(appDetailsIntent())
        invoke.resolve()
      } catch (error: Exception) {
        invoke.reject(error.message)
      }
    } catch (error: Exception) {
      invoke.reject(error.message)
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

  private fun settingsIntent(screen: String?): Intent = when (screen) {
    "input_method" -> Intent(Settings.ACTION_INPUT_METHOD_SETTINGS)
    "notifications" -> Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
      putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName)
    }
    "microphone", "battery", "app" -> appDetailsIntent()
    else -> appDetailsIntent()
  }

  private fun appDetailsIntent(): Intent = Intent(
    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
    Uri.parse("package:${activity.packageName}"),
  )
}
