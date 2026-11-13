package it.traflix.voice

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
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
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Receives one shared audio file and transcribes it without uploading the recording. */
class SharedAudioTranscriptionActivity : AppCompatActivity() {
  private var activeRecognizer: SpeechRecognizer? = null
  private var transcriptionJob: Job? = null
  private var sharedUri: Uri? = null
  private var sharedName = "Audio condiviso"
  private var finalTranscript = ""
  private var activeOperationId: UUID? = null

  private lateinit var fileNameView: TextView
  private lateinit var statusMark: TextView
  private lateinit var statusTitle: TextView
  private lateinit var statusDescription: TextView
  private lateinit var progressBar: ProgressBar
  private lateinit var transcriptCard: MaterialCardView
  private lateinit var transcriptText: TextView
  private lateinit var transcriptMeta: TextView
  private lateinit var errorCard: MaterialCardView
  private lateinit var errorDescription: TextView
  private lateinit var retryButton: MaterialButton
  private lateinit var actions: LinearLayout

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    configureSystemBars()
    setContentView(createScreen())
    handleSharedIntent(intent)
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    setIntent(intent)
    activeOperationId = UUID.randomUUID()
    transcriptionJob?.cancel()
    activeRecognizer?.close()
    activeRecognizer = null
    handleSharedIntent(intent)
  }

  override fun onDestroy() {
    transcriptionJob?.cancel()
    activeRecognizer?.close()
    activeRecognizer = null
    super.onDestroy()
  }

  private fun configureSystemBars() {
    window.statusBarColor = COLOR_CANVAS
    window.navigationBarColor = COLOR_CANVAS
    window.decorView.systemUiVisibility = 0
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      window.isStatusBarContrastEnforced = false
      window.isNavigationBarContrastEnforced = false
    }
    window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
  }

  private fun createScreen(): View {
    val scroll = ScrollView(this).apply {
      setFillViewport(true)
      isVerticalScrollBarEnabled = false
      setBackgroundColor(COLOR_CANVAS)
    }
    val content = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(22), dp(22), dp(22), dp(28))
    }
    scroll.addView(content, ScrollView.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ))

    content.addView(createBrandHeader())
    content.addView(space(28))
    content.addView(label("AUDIO CONDIVISO", COLOR_ACCENT, 11f, true))
    content.addView(space(7))
    content.addView(text("La tua trascrizione", COLOR_INK, 30f, true))
    content.addView(space(7))
    content.addView(text("Dal vocale al testo, direttamente sul telefono.", COLOR_MUTED, 14f, false))
    content.addView(space(20))
    content.addView(createSourceCard())
    content.addView(space(12))
    content.addView(createStatusCard())
    content.addView(space(12))
    content.addView(createTranscriptCard())
    content.addView(space(12))
    content.addView(createErrorCard())
    content.addView(space(16))
    content.addView(createPrivacyNote())

    return scroll
  }

  private fun createBrandHeader(): View {
    val row = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val mark = MaterialCardView(this).apply {
      radius = dp(14).toFloat()
      cardElevation = 0f
      strokeWidth = dp(1)
      strokeColor = ColorStateList.valueOf(COLOR_ACCENT_STROKE)
      setCardBackgroundColor(COLOR_ACCENT_WASH)
    }
    mark.addView(text("T", COLOR_ACCENT, 22f, true).apply {
      gravity = Gravity.CENTER
    }, android.widget.FrameLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.MATCH_PARENT,
    ))
    row.addView(mark, LinearLayout.LayoutParams(dp(44), dp(44)))
    val title = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(10), 0, 0, 0)
    }
    title.addView(label("TRAFLIX", COLOR_INK, 12f, true))
    title.addView(space(2))
    title.addView(label("VOICE · MOBILE", COLOR_QUIET, 10f, true))
    row.addView(title, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    row.addView(pill("SUL DISPOSITIVO", COLOR_SIGNAL, COLOR_SIGNAL_WASH))
    return row
  }

  private fun createSourceCard(): View {
    val row = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      setPadding(dp(15), dp(14), dp(14), dp(14))
    }
    val icon = MaterialCardView(this).apply {
      radius = dp(13).toFloat()
      cardElevation = 0f
      strokeWidth = 0
      setCardBackgroundColor(COLOR_ACCENT_WASH)
    }
    icon.addView(text("♫", COLOR_ACCENT, 23f, true).apply {
      gravity = Gravity.CENTER
    }, android.widget.FrameLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.MATCH_PARENT,
    ))
    row.addView(icon, LinearLayout.LayoutParams(dp(42), dp(42)))
    val details = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(12), 0, dp(8), 0)
    }
    details.addView(label("FILE AUDIO", COLOR_QUIET, 10f, true))
    details.addView(space(5))
    fileNameView = text(sharedName, COLOR_INK, 14f, true).apply {
      maxLines = 2
      ellipsize = android.text.TextUtils.TruncateAt.END
    }
    details.addView(fileNameView)
    row.addView(details, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    row.addView(AudioWaveformView(this), LinearLayout.LayoutParams(dp(74), dp(34)))
    return card(row, COLOR_SURFACE, COLOR_STROKE)
  }

  private fun createStatusCard(): View {
    val column = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(16), dp(15), dp(16), dp(16))
    }
    val row = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    statusMark = text("…", COLOR_ACCENT, 17f, true).apply {
      gravity = Gravity.CENTER
      background = circleDrawable(COLOR_ACCENT_WASH)
      setPadding(dp(10), dp(7), dp(10), dp(7))
    }
    row.addView(statusMark)
    val copy = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(11), 0, 0, 0)
    }
    statusTitle = text("Audio ricevuto", COLOR_INK, 15f, true)
    statusDescription = text("Preparo il riconoscimento vocale sul telefono…", COLOR_MUTED, 12f, false)
    copy.addView(statusTitle)
    copy.addView(space(4))
    copy.addView(statusDescription)
    row.addView(copy, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    column.addView(row)
    progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
      isIndeterminate = true
      progressTintList = ColorStateList.valueOf(COLOR_ACCENT)
      indeterminateTintList = ColorStateList.valueOf(COLOR_ACCENT)
      progressBackgroundTintList = ColorStateList.valueOf(COLOR_STROKE)
    }
    column.addView(progressBar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3)).apply {
      topMargin = dp(16)
    })
    return card(column, COLOR_SURFACE, COLOR_STROKE)
  }

  private fun createTranscriptCard(): MaterialCardView {
    val column = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(16), dp(16), dp(16), dp(15))
    }
    val header = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val heading = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    heading.addView(label("TESTO RICONOSCIUTO", COLOR_ACCENT, 10f, true))
    heading.addView(space(4))
    transcriptMeta = text("Trascrizione locale", COLOR_QUIET, 11f, false)
    heading.addView(transcriptMeta)
    header.addView(heading, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    header.addView(pill("LOCALE", COLOR_SIGNAL, COLOR_SIGNAL_WASH))
    column.addView(header)
    column.addView(space(14))
    transcriptText = text("", COLOR_INK, 16f, false).apply {
      setTextIsSelectable(true)
      setLineSpacing(dp(3).toFloat(), 1.08f)
      gravity = Gravity.START
    }
    column.addView(transcriptText, LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ))
    column.addView(space(16))
    actions = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val copyButton = actionButton("Copia testo", primary = true).apply {
      setOnClickListener { copyTranscript() }
    }
    val shareButton = actionButton("Condividi", primary = false).apply {
      setOnClickListener { shareTranscript() }
    }
    actions.addView(copyButton, LinearLayout.LayoutParams(0, dp(48), 1f))
    actions.addView(spaceWidth(9))
    actions.addView(shareButton, LinearLayout.LayoutParams(0, dp(48), 1f))
    actions.visibility = View.GONE
    column.addView(actions)
    return card(column, COLOR_SURFACE, COLOR_SIGNAL_STROKE).apply { visibility = View.GONE }
  }

  private fun createErrorCard(): MaterialCardView {
    val column = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(15), dp(14), dp(15), dp(14))
    }
    column.addView(label("NON RIESCO A TRASCRIVERE", COLOR_ERROR, 10f, true))
    column.addView(space(6))
    errorDescription = text("", COLOR_MUTED, 13f, false)
    column.addView(errorDescription)
    retryButton = actionButton("Riprova", primary = false).apply {
      setOnClickListener { sharedUri?.let(::startTranscription) }
    }
    column.addView(retryButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(46)).apply {
      topMargin = dp(12)
    })
    return card(column, COLOR_ERROR_WASH, COLOR_ERROR_STROKE).apply { visibility = View.GONE }
  }

  private fun createPrivacyNote(): View {
    val row = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
      setPadding(dp(4), dp(2), dp(4), dp(2))
    }
    row.addView(text("✓", COLOR_SIGNAL, 15f, true))
    row.addView(text(
      "  Il file viene elaborato sul telefono e non è inviato a Groq.",
      COLOR_QUIET,
      11f,
      false,
    ))
    return row
  }

  private fun card(content: View, background: Int, stroke: Int): MaterialCardView =
    MaterialCardView(this).apply {
      radius = dp(19).toFloat()
      cardElevation = 0f
      strokeWidth = dp(1)
      strokeColor = ColorStateList.valueOf(stroke)
      setCardBackgroundColor(background)
      addView(content, ViewGroup.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
      ))
    }

  private fun text(value: String, color: Int, size: Float, bold: Boolean): TextView =
    TextView(this).apply {
      text = value
      setTextColor(color)
      textSize = size
      if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
      includeFontPadding = false
    }

  private fun label(value: String, color: Int, size: Float, bold: Boolean): TextView =
    text(value, color, size, bold).apply { letterSpacing = 0.12f }

  private fun pill(value: String, foreground: Int, background: Int): TextView =
    text(value, foreground, 9f, true).apply {
      letterSpacing = 0.07f
      setPadding(dp(9), dp(7), dp(9), dp(7))
      this.background = roundedDrawable(background, dp(99).toFloat())
    }

  private fun actionButton(value: String, primary: Boolean): MaterialButton =
    MaterialButton(this).apply {
      text = value
      isAllCaps = false
      textSize = 13f
      setTypeface(typeface, android.graphics.Typeface.BOLD)
      cornerRadius = dp(14)
      insetTop = 0
      insetBottom = 0
      if (primary) {
        backgroundTintList = ColorStateList.valueOf(COLOR_ACCENT)
        setTextColor(COLOR_CANVAS)
      } else {
        backgroundTintList = ColorStateList.valueOf(COLOR_SURFACE_ALT)
        strokeWidth = dp(1)
        strokeColor = ColorStateList.valueOf(COLOR_STROKE)
        setTextColor(COLOR_INK)
      }
    }

  private fun space(heightDp: Int): View = View(this).apply {
    layoutParams = LinearLayout.LayoutParams(1, dp(heightDp))
  }

  private fun spaceWidth(widthDp: Int): View = View(this).apply {
    layoutParams = LinearLayout.LayoutParams(dp(widthDp), 1)
  }

  private fun circleDrawable(color: Int) = android.graphics.drawable.GradientDrawable().apply {
    shape = android.graphics.drawable.GradientDrawable.OVAL
    setColor(color)
  }

  private fun roundedDrawable(color: Int, radius: Float) = android.graphics.drawable.GradientDrawable().apply {
    setColor(color)
    cornerRadius = radius
  }

  private fun handleSharedIntent(intent: Intent?) {
    val uri = intent?.let(::audioUriFromIntent)
    if (uri == null) {
      showFailure("Apri o condividi un singolo file audio con Traflix Voice per iniziare.")
      return
    }
    sharedUri = uri
    sharedName = displayName(uri)
    fileNameView.text = sharedName
    startTranscription(uri)
  }

  private fun audioUriFromIntent(intent: Intent): Uri? {
    val uri = when (intent.action) {
      Intent.ACTION_VIEW -> intent.data
      Intent.ACTION_SEND -> {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
          intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
          @Suppress("DEPRECATION")
          intent.getParcelableExtra(Intent.EXTRA_STREAM) as? Uri
        } ?: intent.clipData?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.uri
      }
      else -> null
    } ?: return null

    val mimeType = runCatching { contentResolver.getType(uri) }.getOrNull() ?: intent.type.orEmpty()
    val extension = displayName(uri).substringAfterLast('.', "").lowercase(Locale.ROOT)
    val recognizedAudio = mimeType.startsWith("audio/") ||
      mimeType == "application/ogg" ||
      extension in setOf("opus", "ogg", "mp3", "m4a", "wav", "flac", "aac", "amr", "3gp")
    return uri.takeIf { recognizedAudio }
  }

  private fun displayName(uri: Uri): String {
    val name = runCatching {
      contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
        if (cursor.moveToFirst()) cursor.getString(0) else null
      }
    }.getOrNull()
    return name?.takeIf { it.isNotBlank() }?.take(88) ?: uri.lastPathSegment?.take(88) ?: "Audio condiviso"
  }

  private fun startTranscription(uri: Uri) {
    val operationId = UUID.randomUUID()
    activeOperationId = operationId
    transcriptionJob?.cancel()
    activeRecognizer?.close()
    activeRecognizer = null
    finalTranscript = ""
    transcriptCard.visibility = View.GONE
    errorCard.visibility = View.GONE
    progressBar.visibility = View.VISIBLE
    setStatus("Preparo la trascrizione", "Controllo il modello vocale disponibile sul telefono…", COLOR_ACCENT, "…")

    transcriptionJob = lifecycleScope.launch {
      var temporaryFile: File? = null
      var ownedRecognizer: SpeechRecognizer? = null
      try {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
          throw IllegalStateException("La trascrizione locale dei file richiede Android 12 o successivo.")
        }
        val locale = selectedLocale()
        val recognizer = createReadyRecognizer(locale)
        ownedRecognizer = recognizer
        currentCoroutineContext().ensureActive()
        if (activeOperationId != operationId) return@launch
        activeRecognizer = recognizer
        val settings = VoiceSettingsStore(this@SharedAudioTranscriptionActivity)
        val languageDetail = if (settings.transcriptionLanguage() == "auto") {
          "Lingua del telefono: ${languageName(locale.language)}."
        } else {
          "Lingua: ${languageName(locale.language)}."
        }
        setStatus("Analizzo l’audio", "Riconoscimento in corso · $languageDetail Il file resta sul dispositivo.", COLOR_ACCENT, "◉")

        val sourceResult = createAudioSource(uri)
        temporaryFile = sourceResult.second
        val source = sourceResult.first
        val responseText = try {
          var partialText = ""
          var completedText = ""
          recognizer.startRecognition(speechRecognizerRequest { audioSource = source }).collect { response ->
            when (response) {
              is SpeechRecognizerResponse.PartialTextResponse -> partialText = response.text
              is SpeechRecognizerResponse.FinalTextResponse -> completedText = response.text
              is SpeechRecognizerResponse.ErrorResponse -> throw response.e
              else -> Unit
            }
            if (partialText.isNotBlank() && completedText.isBlank()) {
              runOnUiThreadSafe {
                if (activeOperationId == operationId && finalTranscript.isBlank()) {
                  transcriptText.text = partialText
                  transcriptMeta.text = "Sto riconoscendo le parole…"
                  actions.visibility = View.GONE
                  transcriptCard.visibility = View.VISIBLE
                }
              }
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
        if (activeOperationId != operationId) return@launch
        finalTranscript = responseText.trim()
        val savedInHistory = try {
          withContext(Dispatchers.IO) {
            VoiceHistoryStore(applicationContext).append(finalTranscript)
          }
          true
        } catch (_: Exception) {
          false
        }
        showTranscript(finalTranscript, locale, savedInHistory)
      } catch (error: CancellationException) {
        throw error
      } catch (error: Exception) {
        if (activeOperationId == operationId) showFailure(friendlyError(error))
      } finally {
        temporaryFile?.delete()
        ownedRecognizer?.close()
        if (activeRecognizer === ownedRecognizer) activeRecognizer = null
      }
    }
  }

  private suspend fun createReadyRecognizer(locale: Locale): SpeechRecognizer {
    var lastFailure: Exception? = null
    val modes = listOf(
      SpeechRecognizerOptions.Mode.MODE_BASIC,
      SpeechRecognizerOptions.Mode.MODE_ADVANCED,
    )

    for (mode in modes) {
      val modeLocale = localeForMode(locale, mode)
      val recognizer = try {
        SpeechRecognition.getClient(
          speechRecognizerOptions {
            this.locale = modeLocale
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
            setStatus(
              "Primo utilizzo",
              "Scarico il modello vocale sul telefono. Potrebbe servire internet solo questa volta.",
              COLOR_ACCENT,
              "↓",
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

  private suspend fun createAudioSource(uri: Uri): Pair<AudioSource, File?> {
    val type = runCatching { contentResolver.getType(uri) }.getOrNull().orEmpty().lowercase(Locale.ROOT)
    val extension = sharedName.substringAfterLast('.', "").lowercase(Locale.ROOT)
    if (extension != "opus" && !type.contains("opus")) {
      return AudioSource.fromUri(this, uri) to null
    }

    // WhatsApp voice notes are Ogg/Opus. Giving the same local container an .ogg
    // suffix lets the on-device decoder select its OGG reader on affected devices.
    val normalized = File(cacheDir, "shared-audio-${UUID.randomUUID()}.ogg")
    try {
      withContext(Dispatchers.IO) {
        val input = contentResolver.openInputStream(uri)
          ?: throw IllegalStateException("WhatsApp non ha reso disponibile il file audio.")
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
    val selected = VoiceSettingsStore(this).transcriptionLanguage()
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

  private fun showTranscript(value: String, locale: Locale, savedInHistory: Boolean) {
    finalTranscript = value
    transcriptText.text = value
    val wordCount = value.split(Regex("\\s+")).count { it.isNotBlank() }
    transcriptMeta.text = "${languageName(locale.language)} · $wordCount parole"
    actions.visibility = View.VISIBLE
    transcriptCard.visibility = View.VISIBLE
    errorCard.visibility = View.GONE
    progressBar.visibility = View.GONE
    val detail = if (savedInHistory) {
      "Testo pronto e salvato nella cronologia locale."
    } else {
      "Testo pronto. Non sono riuscito a salvarlo nella cronologia."
    }
    setStatus("Trascrizione pronta", detail, COLOR_SIGNAL, "✓")
  }

  private fun showFailure(message: String) {
    if (!::errorCard.isInitialized) return
    progressBar.visibility = View.GONE
    transcriptCard.visibility = View.GONE
    errorDescription.text = message
    errorCard.visibility = View.VISIBLE
    setStatus("Non è andata a buon fine", "Nessuna trascrizione cloud è stata avviata.", COLOR_ERROR, "!")
  }

  private fun friendlyError(error: Exception): String {
    val message = error.message.orEmpty().lowercase(Locale.ROOT)
    return when {
      message.contains("android 12") -> error.message.orEmpty()
      message.contains("download") || message.contains("network") || message.contains("connect") ->
        "Non riesco a preparare il modello sul telefono. Connettiti a internet per il primo utilizzo e riprova."
      message.contains("format") || message.contains("codec") || message.contains("audio") ->
        "Il formato del vocale non è leggibile dal modello locale. Prova a condividerlo di nuovo da WhatsApp."
      message.contains("no speech") || message.contains("empty") ->
        "Nel file non ho trovato parole da trascrivere."
      else -> error.message?.takeIf { it.isNotBlank() }
        ?: "Il modello locale non è disponibile per questa lingua su questo telefono."
    }
  }

  private fun languageName(language: String): String = when (language) {
    "it" -> "Italiano"
    "en" -> "English"
    "fr" -> "Français"
    "de" -> "Deutsch"
    "es" -> "Español"
    "pt" -> "Português"
    else -> language.uppercase(Locale.ROOT)
  }

  private fun setStatus(title: String, description: String, accent: Int, mark: String) {
    if (!::statusTitle.isInitialized || isFinishing) return
    statusTitle.text = title
    statusDescription.text = description
    statusMark.text = mark
    statusMark.setTextColor(accent)
    statusMark.background = circleDrawable(if (accent == COLOR_SIGNAL) COLOR_SIGNAL_WASH else if (accent == COLOR_ERROR) COLOR_ERROR_WASH else COLOR_ACCENT_WASH)
  }

  private fun runOnUiThreadSafe(action: () -> Unit) {
    if (!isFinishing && !isDestroyed) runOnUiThread(action)
  }

  private fun copyTranscript() {
    if (finalTranscript.isBlank()) return
    val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("Trascrizione Traflix Voice", finalTranscript))
    Toast.makeText(this, "Trascrizione copiata", Toast.LENGTH_SHORT).show()
  }

  private fun shareTranscript() {
    if (finalTranscript.isBlank()) return
    val intent = Intent(Intent.ACTION_SEND).apply {
      type = "text/plain"
      putExtra(Intent.EXTRA_TEXT, finalTranscript)
    }
    startActivity(Intent.createChooser(intent, "Condividi trascrizione"))
  }

  private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

  private class AudioWaveformView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
      color = COLOR_ACCENT
      style = Paint.Style.FILL
    }
    private val heights = floatArrayOf(.22f, .42f, .7f, .46f, .9f, .56f, .76f, .4f, .64f, .3f, .48f)

    override fun onDraw(canvas: Canvas) {
      super.onDraw(canvas)
      val centerY = height / 2f
      val barWidth = dp(3).toFloat()
      val gap = dp(3).toFloat()
      val totalWidth = heights.size * barWidth + (heights.size - 1) * gap
      var left = (width - totalWidth) / 2f
      heights.forEachIndexed { index, heightFactor ->
        val barHeight = height * heightFactor * if (index % 3 == 0) .82f else .62f
        val rect = RectF(left, centerY - barHeight / 2, left + barWidth, centerY + barHeight / 2)
        canvas.drawRoundRect(rect, barWidth, barWidth, paint)
        left += barWidth + gap
      }
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
  }

  private companion object {
    val COLOR_CANVAS = android.graphics.Color.rgb(17, 18, 17)
    val COLOR_SURFACE = android.graphics.Color.rgb(29, 30, 27)
    val COLOR_SURFACE_ALT = android.graphics.Color.rgb(36, 37, 34)
    val COLOR_STROKE = android.graphics.Color.rgb(57, 58, 53)
    val COLOR_INK = android.graphics.Color.rgb(245, 243, 239)
    val COLOR_MUTED = android.graphics.Color.rgb(190, 188, 181)
    val COLOR_QUIET = android.graphics.Color.rgb(143, 141, 133)
    val COLOR_ACCENT = android.graphics.Color.rgb(255, 157, 36)
    val COLOR_ACCENT_WASH = android.graphics.Color.rgb(57, 42, 24)
    val COLOR_ACCENT_STROKE = android.graphics.Color.rgb(95, 67, 34)
    val COLOR_SIGNAL = android.graphics.Color.rgb(85, 216, 155)
    val COLOR_SIGNAL_WASH = android.graphics.Color.rgb(24, 54, 42)
    val COLOR_SIGNAL_STROKE = android.graphics.Color.rgb(44, 83, 64)
    val COLOR_ERROR = android.graphics.Color.rgb(255, 132, 136)
    val COLOR_ERROR_WASH = android.graphics.Color.rgb(59, 31, 33)
    val COLOR_ERROR_STROKE = android.graphics.Color.rgb(102, 51, 54)
  }
}
