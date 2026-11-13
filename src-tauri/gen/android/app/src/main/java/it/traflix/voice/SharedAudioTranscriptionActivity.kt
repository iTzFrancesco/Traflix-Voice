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
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Receives one shared audio file and displays its Groq transcript in a floating panel. */
class SharedAudioTranscriptionActivity : AppCompatActivity() {
  private var transcriptionJob: Job? = null
  private var groqAudioEndpoint: GroqAudioTranscriptionEndpoint? = null
  private var sharedUri: Uri? = null
  private var sharedName = "Audio condiviso"
  private var sharedMimeType = ""
  private var finalTranscript = ""
  private var activeOperationId: UUID? = null

  private lateinit var fileNameView: TextView
  private lateinit var progressRow: LinearLayout
  private lateinit var progressBar: ProgressBar
  private lateinit var transcriptContainer: LinearLayout
  private lateinit var transcriptText: TextView
  private lateinit var errorContainer: LinearLayout
  private lateinit var errorDescription: TextView

  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    configureSystemBars()
    setContentView(createScreen())
    configureFloatingWindow()
    handleSharedIntent(intent)
  }

  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    setIntent(intent)
    activeOperationId = UUID.randomUUID()
    transcriptionJob?.cancel()
    handleSharedIntent(intent)
  }

  override fun onDestroy() {
    transcriptionJob?.cancel()
    groqAudioEndpoint?.shutdown()
    groqAudioEndpoint = null
    super.onDestroy()
  }

  private fun configureSystemBars() {
    window.statusBarColor = android.graphics.Color.TRANSPARENT
    window.navigationBarColor = android.graphics.Color.TRANSPARENT
    window.decorView.systemUiVisibility = 0
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      window.isStatusBarContrastEnforced = false
      window.isNavigationBarContrastEnforced = false
    }
    window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
  }

  private fun configureFloatingWindow() {
    val width = (resources.displayMetrics.widthPixels - dp(48)).coerceAtMost(dp(500))
    window.setLayout(width, WindowManager.LayoutParams.WRAP_CONTENT)
    window.setGravity(Gravity.CENTER)
    window.addFlags(
      WindowManager.LayoutParams.FLAG_DIM_BEHIND or
        WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
    )
    window.attributes = window.attributes.apply { dimAmount = 0.2f }
    window.setBackgroundDrawableResource(android.R.color.transparent)
    setFinishOnTouchOutside(false)
  }

  private fun createScreen(): View {
    val panel = MaterialCardView(this).apply {
      radius = dp(23).toFloat()
      cardElevation = dp(12).toFloat()
      strokeWidth = 0
      setCardBackgroundColor(COLOR_CANVAS)
    }
    val content = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(18), dp(16), dp(18), dp(16))
    }
    panel.addView(content, android.widget.FrameLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ))
    content.addView(createBrandHeader())
    content.addView(createSourceCard(), LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(12) })
    content.addView(createProgressRow(), LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(12) })
    content.addView(createTranscriptContent(), LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(12) })
    content.addView(createErrorContent(), LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(12) })

    return panel
  }

  private fun createBrandHeader(): View {
    val row = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val logo = ImageView(this).apply {
      setImageResource(R.mipmap.ic_launcher_round)
      scaleType = ImageView.ScaleType.FIT_CENTER
      contentDescription = null
    }
    row.addView(logo, LinearLayout.LayoutParams(dp(40), dp(40)))
    row.addView(text("Traflix Voice", COLOR_INK, 17f, true), LinearLayout.LayoutParams(
      0,
      ViewGroup.LayoutParams.WRAP_CONTENT,
      1f,
    ).apply { marginStart = dp(10) })
    val closeButton = CloseIconView(this).apply {
      contentDescription = "Chiudi trascrizione"
      isClickable = true
      isFocusable = true
      background = roundedDrawable(COLOR_SURFACE_ALT, dp(99).toFloat())
      setOnClickListener { finish() }
    }
    row.addView(closeButton, LinearLayout.LayoutParams(dp(48), dp(48)).apply {
      marginStart = dp(8)
    })
    return row
  }

  private fun createSourceCard(): View {
    val row = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    val details = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
    }
    details.addView(label("File audio", COLOR_ACCENT, 10f, true))
    details.addView(space(5))
    fileNameView = text(sharedName, COLOR_INK, 14f, true).apply {
      maxLines = 2
      ellipsize = android.text.TextUtils.TruncateAt.END
    }
    details.addView(fileNameView)
    row.addView(details, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
    row.addView(AudioWaveformView(this), LinearLayout.LayoutParams(dp(58), dp(28)))
    return row
  }

  private fun createProgressRow(): View {
    progressRow = LinearLayout(this).apply {
      orientation = LinearLayout.HORIZONTAL
      gravity = Gravity.CENTER_VERTICAL
    }
    progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleSmall).apply {
      isIndeterminate = true
      indeterminateTintList = ColorStateList.valueOf(COLOR_ACCENT)
    }
    progressRow.addView(progressBar, LinearLayout.LayoutParams(dp(18), dp(18)))
    progressRow.addView(text("Trascrivo audio…", COLOR_MUTED, 13f, false), LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.WRAP_CONTENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { marginStart = dp(9) })
    return progressRow
  }

  private fun createTranscriptContent(): View {
    val column = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
    }
    column.addView(View(this).apply { setBackgroundColor(COLOR_STROKE) }, LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      dp(1),
    ))
    val transcriptScroll = BoundedScrollView(this, dp(220)).apply {
      isFillViewport = false
      isVerticalScrollBarEnabled = true
      overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
    }
    transcriptText = text("", COLOR_INK, 16f, false).apply {
      setLineSpacing(dp(3).toFloat(), 1.08f)
      gravity = Gravity.START
      setPadding(0, dp(12), dp(6), dp(8))
    }
    transcriptScroll.addView(transcriptText, android.widget.FrameLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ))
    val copyButton = actionButton("Copia testo", primary = true).apply {
      setOnClickListener { copyTranscript() }
    }
    column.addView(transcriptScroll, LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ))
    column.addView(copyButton, LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      dp(48),
    ).apply { topMargin = dp(10) })
    transcriptContainer = column.apply { visibility = View.GONE }
    return transcriptContainer
  }

  private fun createErrorContent(): View {
    val column = LinearLayout(this).apply {
      orientation = LinearLayout.VERTICAL
    }
    column.addView(label("Trascrizione non riuscita", COLOR_ERROR, 13f, true))
    errorDescription = text("", COLOR_MUTED, 13f, false)
    column.addView(errorDescription, LinearLayout.LayoutParams(
      ViewGroup.LayoutParams.MATCH_PARENT,
      ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = dp(5) })
    val retryButton = actionButton("Riprova", primary = false).apply {
      setOnClickListener { sharedUri?.let(::startTranscription) }
    }
    column.addView(retryButton, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(46)).apply {
      topMargin = dp(9)
    })
    errorContainer = column.apply { visibility = View.GONE }
    return errorContainer
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
    sharedMimeType = runCatching { contentResolver.getType(uri) }.getOrNull().orEmpty()
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
      extension in setOf("opus", "ogg", "mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "flac", "webm")
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
    finalTranscript = ""
    transcriptContainer.visibility = View.GONE
    errorContainer.visibility = View.GONE
    progressRow.visibility = View.VISIBLE

    transcriptionJob = lifecycleScope.launch {
      try {
        val transcript = (groqAudioEndpoint ?: GroqAudioTranscriptionEndpoint(applicationContext)
          .also { groqAudioEndpoint = it }).transcribe(
          uri = uri,
          displayName = sharedName,
          mimeType = sharedMimeType,
          language = VoiceSettingsStore(applicationContext).transcriptionLanguage(),
        )
        if (activeOperationId != operationId) return@launch
        finalTranscript = transcript.text
        try {
          withContext(Dispatchers.IO) {
            VoiceHistoryStore(applicationContext).append(finalTranscript)
          }
        } catch (_: Exception) {
        }
        showTranscript(finalTranscript)
      } catch (error: CancellationException) {
        throw error
      } catch (error: Exception) {
        if (activeOperationId == operationId) showFailure(error.message ?: "Trascrizione Groq Cloud non riuscita")
      }
    }
  }
  private fun showTranscript(value: String) {
    finalTranscript = value
    transcriptText.text = value
    progressRow.visibility = View.GONE
    errorContainer.visibility = View.GONE
    transcriptContainer.visibility = View.VISIBLE
  }

  private fun showFailure(message: String) {
    if (!::errorContainer.isInitialized) return
    progressRow.visibility = View.GONE
    transcriptContainer.visibility = View.GONE
    errorDescription.text = message
    errorContainer.visibility = View.VISIBLE
  }

  private fun copyTranscript() {
    if (finalTranscript.isBlank()) return
    val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("Trascrizione Traflix Voice", finalTranscript))
    Toast.makeText(this, "Trascrizione copiata", Toast.LENGTH_SHORT).show()
  }

  private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

  private class BoundedScrollView(context: Context, private val maxHeight: Int) : ScrollView(context) {
    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
      super.onMeasure(widthMeasureSpec, heightMeasureSpec)
      if (measuredHeight > maxHeight) {
        super.onMeasure(
          widthMeasureSpec,
          MeasureSpec.makeMeasureSpec(maxHeight, MeasureSpec.EXACTLY),
        )
      }
    }
  }

  private class CloseIconView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
      color = COLOR_MUTED
      strokeWidth = context.resources.displayMetrics.density * 1.8f
      strokeCap = Paint.Cap.ROUND
      style = Paint.Style.STROKE
    }

    override fun onDraw(canvas: Canvas) {
      super.onDraw(canvas)
      val half = dp(5).toFloat()
      val centerX = width / 2f
      val centerY = height / 2f
      canvas.drawLine(centerX - half, centerY - half, centerX + half, centerY + half, paint)
      canvas.drawLine(centerX + half, centerY - half, centerX - half, centerY + half, paint)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
  }

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
    val COLOR_SURFACE_ALT = android.graphics.Color.rgb(36, 37, 34)
    val COLOR_STROKE = android.graphics.Color.rgb(57, 58, 53)
    val COLOR_INK = android.graphics.Color.rgb(245, 243, 239)
    val COLOR_MUTED = android.graphics.Color.rgb(190, 188, 181)
    val COLOR_ACCENT = android.graphics.Color.rgb(255, 157, 36)
    val COLOR_ERROR = android.graphics.Color.rgb(255, 132, 136)
    val COLOR_ERROR_WASH = android.graphics.Color.rgb(59, 31, 33)
    val COLOR_ERROR_STROKE = android.graphics.Color.rgb(102, 51, 54)
  }
}
