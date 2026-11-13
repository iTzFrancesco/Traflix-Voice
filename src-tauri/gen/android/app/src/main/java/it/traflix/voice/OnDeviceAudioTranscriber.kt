package it.traflix.voice

import android.content.Context
import android.net.Uri
import android.os.Build
import com.google.mlkit.genai.common.DownloadStatus
import com.google.mlkit.genai.common.FeatureStatus
import com.google.mlkit.genai.common.audio.AudioSource
import com.google.mlkit.genai.speechrecognition.SpeechRecognition
import com.google.mlkit.genai.speechrecognition.SpeechRecognizer
import com.google.mlkit.genai.speechrecognition.SpeechRecognizerOptions
import com.google.mlkit.genai.speechrecognition.SpeechRecognizerResponse
import com.google.mlkit.genai.speechrecognition.speechRecognizerOptions
import com.google.mlkit.genai.speechrecognition.speechRecognizerRequest
import java.io.File
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext

data class OnDeviceAudioTranscript(val text: String, val locale: Locale)

/** Shared local recognizer for Android share intents and the in-app audio picker. */
class OnDeviceAudioTranscriber(context: Context) {
  private val appContext = context.applicationContext

  suspend fun transcribe(
    uri: Uri,
    displayName: String,
    onStatus: (title: String, description: String) -> Unit = { _, _ -> },
    onPartialText: (String) -> Unit = {},
  ): OnDeviceAudioTranscript {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
      throw IllegalStateException("La trascrizione locale dei file richiede Android 12 o successivo.")
    }

    val locale = selectedLocale()
    val recognizer = createReadyRecognizer(locale, onStatus)
    var temporaryFile: File? = null
    try {
      currentCoroutineContext().ensureActive()
      val selectedLanguage = VoiceSettingsStore(appContext).transcriptionLanguage()
      val languageDetail = if (selectedLanguage == "auto") {
        "Lingua del telefono: ${languageName(locale.language)}."
      } else {
        "Lingua: ${languageName(locale.language)}."
      }
      onStatus("Analizzo l’audio", "Riconoscimento in corso · $languageDetail Il file resta sul dispositivo.")

      val sourceResult = createAudioSource(uri, displayName)
      temporaryFile = sourceResult.second
      val source = sourceResult.first
      val responseText = try {
        var partialText = ""
        var completedText = ""
        recognizer.startRecognition(speechRecognizerRequest { audioSource = source }).collect { response ->
          when (response) {
            is SpeechRecognizerResponse.PartialTextResponse -> {
              partialText = response.text
              if (partialText.isNotBlank() && completedText.isBlank()) onPartialText(partialText)
            }
            is SpeechRecognizerResponse.FinalTextResponse -> completedText = response.text
            is SpeechRecognizerResponse.ErrorResponse -> throw response.e
            else -> Unit
          }
        }
        completedText.ifBlank { partialText }
      } finally {
        source.close()
      }

      if (responseText.isBlank()) {
        throw IllegalStateException("Nel file non ho trovato parole da trascrivere.")
      }
      currentCoroutineContext().ensureActive()
      return OnDeviceAudioTranscript(responseText.trim(), locale)
    } finally {
      temporaryFile?.delete()
      recognizer.close()
    }
  }

  private suspend fun createReadyRecognizer(
    locale: Locale,
    onStatus: (title: String, description: String) -> Unit,
  ): SpeechRecognizer {
    var lastFailure: Exception? = null
    val modes = listOf(
      SpeechRecognizerOptions.Mode.MODE_BASIC,
      SpeechRecognizerOptions.Mode.MODE_ADVANCED,
    )

    for (mode in modes) {
      val recognizer = try {
        SpeechRecognition.getClient(
          speechRecognizerOptions {
            this.locale = localeForMode(locale, mode)
            preferredMode = mode
          },
        )
      } catch (error: Exception) {
        lastFailure = error
        continue
      }

      try {
        when (recognizer.checkStatus()) {
          FeatureStatus.AVAILABLE -> return recognizer
          FeatureStatus.DOWNLOADABLE, FeatureStatus.DOWNLOADING -> {
            onStatus(
              "Primo utilizzo",
              "Preparo il modello vocale sul telefono. Potrebbe servire internet solo questa volta.",
            )
            when (val download = recognizer.download().first {
              it is DownloadStatus.DownloadCompleted || it is DownloadStatus.DownloadFailed
            }) {
              is DownloadStatus.DownloadCompleted -> return recognizer
              is DownloadStatus.DownloadFailed -> throw download.e
              else -> Unit
            }
          }
          else -> Unit
        }
      } catch (error: CancellationException) {
        recognizer.close()
        throw error
      } catch (error: Exception) {
        lastFailure = error
      }

      recognizer.close()
    }

    throw lastFailure ?: IllegalStateException(
      "Su questo telefono non è disponibile un modello vocale locale per la lingua selezionata.",
    )
  }

  private suspend fun createAudioSource(uri: Uri, displayName: String): Pair<AudioSource, File?> {
    val type = runCatching { appContext.contentResolver.getType(uri) }
      .getOrNull()
      .orEmpty()
      .lowercase(Locale.ROOT)
    val extension = displayName.substringAfterLast('.', "").lowercase(Locale.ROOT)
    if (extension != "opus" && !type.contains("opus")) {
      return AudioSource.fromUri(appContext, uri) to null
    }

    // Some Android decoders select the OGG reader from the suffix for Opus files.
    val normalized = File(appContext.cacheDir, "local-audio-${UUID.randomUUID()}.ogg")
    try {
      withContext(Dispatchers.IO) {
        val input = appContext.contentResolver.openInputStream(uri)
          ?: throw IllegalStateException("Non riesco ad aprire il file audio selezionato.")
        input.use { source ->
          normalized.outputStream().use { output -> source.copyTo(output) }
        }
      }
      return AudioSource.fromFile(normalized) to normalized
    } catch (error: Exception) {
      normalized.delete()
      throw error
    }
  }

  private fun selectedLocale(): Locale {
    val selected = VoiceSettingsStore(appContext).transcriptionLanguage()
    val tag = when (selected) {
      "it" -> "it-IT"
      "en" -> "en-US"
      "fr" -> "fr-FR"
      "de" -> "de-DE"
      "es" -> "es-ES"
      "pt" -> "pt-PT"
      "auto" -> localeTagForLanguage(Locale.getDefault().language) ?: "it-IT"
      else -> "it-IT"
    }
    return Locale.forLanguageTag(tag)
  }

  private fun localeForMode(locale: Locale, mode: Int): Locale {
    if (locale.language == "pt" && mode == SpeechRecognizerOptions.Mode.MODE_BASIC) {
      return Locale.forLanguageTag("pt-BR")
    }
    return locale
  }

  private fun localeTagForLanguage(language: String): String? = when (language.lowercase(Locale.ROOT)) {
    "it" -> "it-IT"
    "en" -> "en-US"
    "fr" -> "fr-FR"
    "de" -> "de-DE"
    "es" -> "es-ES"
    "pt" -> "pt-PT"
    else -> null
  }

  companion object {
    fun friendlyError(error: Exception): String {
      val message = error.message.orEmpty().lowercase(Locale.ROOT)
      return when {
        message.contains("android 12") -> error.message.orEmpty()
        message.contains("download") || message.contains("network") || message.contains("connect") ->
          "Non riesco a preparare il modello sul telefono. Connettiti a internet per il primo utilizzo e riprova."
        message.contains("format") || message.contains("codec") || message.contains("audio") ->
          "Il formato del file audio non è leggibile dal modello locale. Prova con un altro file."
        message.contains("no speech") || message.contains("empty") || message.contains("parole") ->
          "Nel file non ho trovato parole da trascrivere."
        else -> error.message?.takeIf { it.isNotBlank() }
          ?: "Il modello locale non è disponibile per questa lingua su questo telefono."
      }
    }

    fun languageName(language: String): String = when (language) {
      "it" -> "Italiano"
      "en" -> "English"
      "fr" -> "Français"
      "de" -> "Deutsch"
      "es" -> "Español"
      "pt" -> "Português"
      else -> language.uppercase(Locale.ROOT)
    }
  }
}
