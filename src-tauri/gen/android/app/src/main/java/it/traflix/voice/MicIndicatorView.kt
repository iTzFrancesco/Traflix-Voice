package it.traflix.voice

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.View
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.sin

class MicIndicatorView @JvmOverloads constructor(
  context: Context,
  attrs: AttributeSet? = null,
) : View(context, attrs) {
  private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val foregroundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
  }
  private val waveformPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    strokeCap = Paint.Cap.ROUND
    strokeWidth = dp(3f)
  }
  private val arcRect = RectF()
  private var indicatorState = MicIndicatorState.IDLE
  private var volume = 0f
  private var animationPhase = 0f
  private var compact = false

  private val animationTick = object : Runnable {
    override fun run() {
      animationPhase += 0.22f
      invalidate()
      if (indicatorState == MicIndicatorState.RECORDING ||
        indicatorState == MicIndicatorState.STARTING ||
        indicatorState == MicIndicatorState.PROCESSING
      ) {
        postDelayed(this, 50L)
      }
    }
  }

  init {
    isClickable = true
    contentDescription = "Microfono Traflix Voice"
  }

  fun setCompact(value: Boolean) {
    if (compact == value) return
    compact = value
    invalidate()
  }

  fun setIndicatorState(state: MicIndicatorState) {
    if (indicatorState == state) return
    indicatorState = state
    if (state != MicIndicatorState.RECORDING) volume = 0f
    contentDescription = when (state) {
      MicIndicatorState.IDLE -> "Avvia dettatura"
      MicIndicatorState.STARTING -> "Avvio dettatura"
      MicIndicatorState.RECORDING -> "Registrazione in corso, indicatore voce in tempo reale"
      MicIndicatorState.PROCESSING -> "Trascrizione in corso"
      MicIndicatorState.SUCCESS -> "Trascrizione completata"
      MicIndicatorState.ERROR -> "Errore trascrizione"
    }
    removeCallbacks(animationTick)
    if (state == MicIndicatorState.RECORDING ||
      state == MicIndicatorState.STARTING ||
      state == MicIndicatorState.PROCESSING
    ) {
      post(animationTick)
    }
    invalidate()
  }

  fun setVolume(value: Float) {
    volume = value.coerceIn(0f, 1f)
    if (indicatorState == MicIndicatorState.RECORDING) invalidate()
  }

  override fun onDraw(canvas: Canvas) {
    super.onDraw(canvas)
    val width = width.toFloat()
    val height = height.toFloat()
    val radius = height / 2f

    backgroundPaint.color = backgroundColor()
    canvas.drawRoundRect(RectF(0f, 0f, width, height), radius, radius, backgroundPaint)

    val centerY = height / 2f

    if (compact) {
      when (indicatorState) {
        MicIndicatorState.STARTING,
        MicIndicatorState.PROCESSING -> drawProgress(canvas, width / 2f, centerY)
        MicIndicatorState.SUCCESS -> drawCheck(canvas, width / 2f, centerY)
        MicIndicatorState.ERROR -> drawError(canvas, width / 2f, centerY)
        MicIndicatorState.IDLE -> drawMicrophone(canvas, width / 2f, centerY)
        MicIndicatorState.RECORDING -> drawWaveform(canvas, width / 2f, centerY)
      }
      return
    }

    val iconCenterX = height * 0.55f
    drawMicrophone(canvas, iconCenterX, centerY)

    foregroundPaint.color = Color.WHITE
    foregroundPaint.textSize = dp(14f)
    foregroundPaint.textAlign = Paint.Align.LEFT
    canvas.drawText(label(), height * 0.95f, centerY + dp(5f), foregroundPaint)

    if (indicatorState == MicIndicatorState.RECORDING) {
      drawWaveform(canvas, width - dp(48f), centerY)
    } else if (indicatorState == MicIndicatorState.PROCESSING ||
      indicatorState == MicIndicatorState.STARTING
    ) {
      drawProgress(canvas, width - dp(28f), centerY)
    } else if (indicatorState == MicIndicatorState.SUCCESS) {
      drawCheck(canvas, width - dp(28f), centerY)
    } else if (indicatorState == MicIndicatorState.ERROR) {
      drawError(canvas, width - dp(28f), centerY)
    }
  }

  override fun onDetachedFromWindow() {
    removeCallbacks(animationTick)
    super.onDetachedFromWindow()
  }

  private fun drawMicrophone(canvas: Canvas, centerX: Float, centerY: Float) {
    foregroundPaint.color = Color.WHITE
    foregroundPaint.style = Paint.Style.FILL
    val capsule = RectF(
      centerX - dp(7f),
      centerY - dp(12f),
      centerX + dp(7f),
      centerY + dp(4f),
    )
    canvas.drawRoundRect(capsule, dp(7f), dp(7f), foregroundPaint)
    foregroundPaint.style = Paint.Style.STROKE
    foregroundPaint.strokeWidth = dp(2f)
    canvas.drawArc(
      RectF(centerX - dp(11f), centerY - dp(8f), centerX + dp(11f), centerY + dp(10f)),
      0f,
      180f,
      false,
      foregroundPaint,
    )
    canvas.drawLine(centerX, centerY + dp(10f), centerX, centerY + dp(15f), foregroundPaint)
    canvas.drawLine(centerX - dp(5f), centerY + dp(15f), centerX + dp(5f), centerY + dp(15f), foregroundPaint)
    foregroundPaint.style = Paint.Style.FILL
  }

  private fun drawWaveform(canvas: Canvas, centerX: Float, centerY: Float) {
    waveformPaint.color = Color.WHITE
    val heights = floatArrayOf(0.35f, 0.65f, 1f, 0.55f, 0.8f)
    heights.forEachIndexed { index, baseHeight ->
      val pulse = 0.65f + 0.35f * abs(sin(animationPhase + index * 0.8f))
      val barHeight = dp(18f) * max(0.18f, volume * 1.4f + 0.15f) * baseHeight * pulse
      val x = centerX + (index - 2) * dp(6f)
      canvas.drawLine(x, centerY - barHeight, x, centerY + barHeight, waveformPaint)
    }
  }

  private fun drawProgress(canvas: Canvas, centerX: Float, centerY: Float) {
    foregroundPaint.style = Paint.Style.STROKE
    foregroundPaint.strokeWidth = dp(2f)
    arcRect.set(
      centerX - dp(9f),
      centerY - dp(9f),
      centerX + dp(9f),
      centerY + dp(9f),
    )
    foregroundPaint.color = Color.argb(90, 255, 255, 255)
    canvas.drawArc(arcRect, 0f, 360f, false, foregroundPaint)
    foregroundPaint.color = Color.WHITE
    foregroundPaint.strokeWidth = dp(3f)
    canvas.drawArc(arcRect, animationPhase * 70f, 105f, false, foregroundPaint)
    foregroundPaint.style = Paint.Style.FILL
  }

  private fun drawCheck(canvas: Canvas, centerX: Float, centerY: Float) {
    foregroundPaint.color = Color.WHITE
    foregroundPaint.style = Paint.Style.STROKE
    foregroundPaint.strokeWidth = dp(3f)
    foregroundPaint.strokeCap = Paint.Cap.ROUND
    canvas.drawLine(centerX - dp(8f), centerY, centerX - dp(2f), centerY + dp(6f), foregroundPaint)
    canvas.drawLine(centerX - dp(2f), centerY + dp(6f), centerX + dp(9f), centerY - dp(7f), foregroundPaint)
    foregroundPaint.style = Paint.Style.FILL
  }

  private fun drawError(canvas: Canvas, centerX: Float, centerY: Float) {
    foregroundPaint.color = Color.WHITE
    foregroundPaint.style = Paint.Style.STROKE
    foregroundPaint.strokeWidth = dp(3f)
    foregroundPaint.strokeCap = Paint.Cap.ROUND
    canvas.drawLine(centerX - dp(7f), centerY - dp(7f), centerX + dp(7f), centerY + dp(7f), foregroundPaint)
    canvas.drawLine(centerX + dp(7f), centerY - dp(7f), centerX - dp(7f), centerY + dp(7f), foregroundPaint)
    foregroundPaint.style = Paint.Style.FILL
  }

  private fun backgroundColor(): Int = when (indicatorState) {
    MicIndicatorState.IDLE -> Color.rgb(24, 24, 30)
    MicIndicatorState.STARTING -> Color.rgb(54, 93, 140)
    MicIndicatorState.RECORDING -> Color.rgb(154, 54, 70)
    MicIndicatorState.PROCESSING -> Color.rgb(80, 70, 142)
    MicIndicatorState.SUCCESS -> Color.rgb(45, 126, 87)
    MicIndicatorState.ERROR -> Color.rgb(150, 73, 52)
  }

  private fun label(): String = when (indicatorState) {
    MicIndicatorState.IDLE -> "Parla"
    MicIndicatorState.STARTING -> "Avvio"
    MicIndicatorState.RECORDING -> "Registrazione"
    MicIndicatorState.PROCESSING -> "Trascrizione"
    MicIndicatorState.SUCCESS -> "Inserito"
    MicIndicatorState.ERROR -> "Riprova"
  }

  private fun dp(value: Float): Float = value * resources.displayMetrics.density
}
