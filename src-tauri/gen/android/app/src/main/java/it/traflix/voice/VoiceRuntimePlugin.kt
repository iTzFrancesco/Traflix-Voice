package it.traflix.voice

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import android.provider.Settings
import android.util.Log
import androidx.activity.result.ActivityResult
import androidx.appcompat.app.AppCompatActivity
import app.tauri.annotation.ActivityCallback
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.Plugin
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

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

@InvokeArg
class HistoryEntryArgs {
  var index: Int = 0
  var text: String? = null
  var timestamp: String? = null
  var wordCount: Int = 0
}

@InvokeArg
class LocalAudioFileArgs {
  var uri: String? = null
  var name: String? = null
  var mimeType: String? = null
}

@TauriPlugin
class VoiceRuntimePlugin(private val activity: Activity) : Plugin(activity) {
  private val audioScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
  private var audioTranscriptionJob: Job? = null
  private var groqAudioEndpoint: GroqAudioTranscriptionEndpoint? = null

  override fun onDestroy(activity: AppCompatActivity) {
    audioScope.cancel()
    groqAudioEndpoint?.shutdown()
    groqAudioEndpoint = null
    super.onDestroy(activity)
  }

  @Command
  fun pickLocalAudioFile(invoke: Invoke) {
    val picker = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
      addCategory(Intent.CATEGORY_OPENABLE)
      type = "audio/*"
      addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
    }
    try {
      startActivityForResult(invoke, picker, "onLocalAudioPicked")
    } catch (error: Exception) {
      Log.e(TAG, "open local audio picker failed", error)
      invoke.reject(error.message ?: "Impossibile aprire il selettore audio")
    }
  }

  @ActivityCallback
  fun onLocalAudioPicked(invoke: Invoke, result: ActivityResult) {
    if (result.resultCode != Activity.RESULT_OK) {
      invoke.resolveObject(mapOf("cancelled" to true))
      return
    }

    val uri = result.data?.data
    if (uri == null) {
      invoke.reject("Il selettore non ha restituito un file audio")
      return
    }

    val readGrant = result.data?.flags?.and(Intent.FLAG_GRANT_READ_URI_PERMISSION) ?: 0
    if (readGrant != 0) {
      runCatching { activity.contentResolver.takePersistableUriPermission(uri, readGrant) }
    }
    val name = runCatching {
      activity.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
        val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
        if (cursor.moveToFirst() && column >= 0) cursor.getString(column) else null
      }
    }.getOrNull()?.takeIf { it.isNotBlank() }?.take(120)
      ?: uri.lastPathSegment?.take(120)
      ?: "Audio selezionato"
    val mimeType = runCatching { activity.contentResolver.getType(uri) }.getOrNull().orEmpty()
    invoke.resolveObject(
      mapOf(
        "cancelled" to false,
        "uri" to uri.toString(),
        "name" to name,
        "mimeType" to mimeType,
      ),
    )
  }

  @Command
  fun transcribeAudioFile(invoke: Invoke) {
    val args = invoke.parseArgs(LocalAudioFileArgs::class.java)
    val uri = runCatching { Uri.parse(args.uri?.trim().orEmpty()) }.getOrNull()
    if (uri == null || uri.scheme != "content") {
      invoke.reject("Seleziona un file audio valido dal dispositivo")
      return
    }
    if (audioTranscriptionJob?.isActive == true) {
      invoke.reject("È già in corso una trascrizione audio")
      return
    }

    audioTranscriptionJob = audioScope.launch {
      try {
        val transcript = (groqAudioEndpoint ?: GroqAudioTranscriptionEndpoint(activity.applicationContext)
          .also { groqAudioEndpoint = it }).transcribe(
          uri = uri,
          displayName = args.name?.takeIf { it.isNotBlank() } ?: "Audio selezionato",
          mimeType = args.mimeType.orEmpty(),
          language = VoiceSettingsStore(activity.applicationContext).transcriptionLanguage(),
        )
        val savedInHistory = try {
          withContext(Dispatchers.IO) {
            VoiceHistoryStore(activity.applicationContext).append(transcript.text)
          }
          true
        } catch (error: Exception) {
          Log.e(TAG, "save Groq audio transcript failed", error)
          false
        }
        invoke.resolveObject(
          mapOf(
            "text" to transcript.text,
            "language" to languageName(transcript.language),
            "savedInHistory" to savedInHistory,
          ),
        )
      } catch (error: CancellationException) {
        throw error
      } catch (error: Exception) {
        Log.e(TAG, "Groq audio transcription failed", error)
        invoke.reject(error.message ?: "Trascrizione Groq Cloud non riuscita")
      } finally {
        audioTranscriptionJob = null
      }
    }
  }

  private fun languageName(language: String): String = when (language) {
    "it" -> "Italiano"
    "en" -> "English"
    "fr" -> "Français"
    "de" -> "Deutsch"
    "es" -> "Español"
    "pt" -> "Português"
    "auto" -> "Rilevamento automatico"
    else -> language.uppercase()
  }

  @Command
  fun releaseLocalAudioFile(invoke: Invoke) {
    val args = invoke.parseArgs(LocalAudioFileArgs::class.java)
    val uri = runCatching { Uri.parse(args.uri?.trim().orEmpty()) }.getOrNull()
    if (uri?.scheme == "content") {
      runCatching {
        activity.contentResolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
      }
    }
    invoke.resolve()
  }

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
  fun getRuntimeState(invoke: Invoke) {
    invoke.resolveObject(VoiceRuntimeStateStore(activity).snapshot())
  }

  @Command
  fun clearHistoryAndStats(invoke: Invoke) {
    try {
      VoiceDataResetStore(activity).clearHistoryAndStats()
      invoke.resolve()
    } catch (error: Exception) {
      Log.e(TAG, "clear history and stats failed", error)
      invoke.reject(error.message ?: "Impossibile cancellare la cronologia")
    }
  }

  @Command
  fun deleteHistoryEntry(invoke: Invoke) {
    try {
      val args = invoke.parseArgs(HistoryEntryArgs::class.java)
      val deleted = VoiceHistoryStore(activity).delete(
        args.index,
        args.text.orEmpty(),
        args.timestamp.orEmpty(),
        args.wordCount,
      )
      invoke.resolveObject(mapOf("deleted" to deleted))
    } catch (error: Exception) {
      Log.e(TAG, "delete history entry failed", error)
      invoke.reject(error.message ?: "Impossibile cancellare la trascrizione")
    }
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
