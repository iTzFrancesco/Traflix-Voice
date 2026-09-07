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
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.roundToInt

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
  private val backgroundRect = RectF()
  private val microphoneCapsuleRect = RectF()
  private val microphoneArcRect = RectF()
  private val arcRect = RectF()
  private val waveformHeights = floatArrayOf(0.35f, 0.65f, 1f, 0.55f, 0.8f)
  private var indicatorState = MicIndicatorState.IDLE
  private var targetVolume = 0f
  private var smoothedVolume = 0f
  private var animationPhase = 0f
  private var compact = false
  private var transitionProgress = 1f
  private var transitionFromColor = Color.rgb(24, 24, 30)
  private var transitionToColor = Color.rgb(24, 24, 30)
  private var visualScale = 1f

  private val animationTick = object : Runnable {
    override fun run() {
      val animatedState = isAnimatedState(indicatorState)
      if (animatedState) animationPhase += 0.11f

      val volumeDelta = targetVolume - smoothedVolume
      if (indicatorState == MicIndicatorState.RECORDING) {
        val smoothing = if (volumeDelta >= 0f) 0.28f else 0.16f
        smoothedVolume += volumeDelta * smoothing
        if (abs(volumeDelta) < 0.003f) smoothedVolume = targetVolume
      } else {
        smoothedVolume *= 0.82f
        if (smoothedVolume < 0.003f) smoothedVolume = 0f
      }

      if (transitionProgress < 1f) {
        transitionProgress = (transitionProgress + 0.16f).coerceAtMost(1f)
      }
      if (visualScale < 1f) {
        visualScale = (visualScale + 0.16f).coerceAtMost(1f)
      }
      invalidate()
      if (animatedState || transitionProgress < 1f || visualScale < 1f ||
        abs(targetVolume - smoothedVolume) >= 0.003f
      ) {
        postOnAnimation(this)
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
    transitionFromColor = currentBackgroundColor()
    indicatorState = state
    transitionToColor = backgroundColorFor(state)
    transitionProgress = 0f
    visualScale = 0.92f
    if (state != MicIndicatorState.RECORDING) targetVolume = 0f
    contentDescription = when (state) {
      MicIndicatorState.IDLE -> "Avvia dettatura"
      MicIndicatorState.STARTING -> "Avvio dettatura"
      MicIndicatorState.RECORDING -> "Registrazione in corso, indicatore voce in tempo reale"
      MicIndicatorState.PROCESSING -> "Trascrizione in corso"
      MicIndicatorState.SUCCESS -> "Trascrizione completata"
      MicIndicatorState.ERROR -> "Errore trascrizione"
    }
    removeCallbacks(animationTick)
    postOnAnimation(animationTick)
    invalidate()
  }

  fun setVolume(value: Float) {
    targetVolume = if (indicatorState == MicIndicatorState.RECORDING) {
      normalizeVolume(value)
    } else {
      0f
    }
  }

  override fun onDraw(canvas: Canvas) {
    super.onDraw(canvas)
    val width = width.toFloat()
    val height = height.toFloat()
    val radius = height / 2f

    backgroundPaint.color = currentBackgroundColor()
    backgroundRect.set(0f, 0f, width, height)
    canvas.drawRoundRect(backgroundRect, radius, radius, backgroundPaint)

    val centerY = height / 2f

    if (compact) {
      canvas.save()
      canvas.scale(visualScale, visualScale, width / 2f, centerY)
      when (indicatorState) {
        MicIndicatorState.STARTING,
        MicIndicatorState.PROCESSING -> drawProgress(canvas, width / 2f, centerY)
        MicIndicatorState.SUCCESS -> drawCheck(canvas, width / 2f, centerY)
        MicIndicatorState.ERROR -> drawError(canvas, width / 2f, centerY)
        MicIndicatorState.IDLE -> drawMicrophone(canvas, width / 2f, centerY)
        MicIndicatorState.RECORDING -> drawWaveform(canvas, width / 2f, centerY)
      }
      canvas.restore()
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

  override fun onAttachedToWindow() {
    super.onAttachedToWindow()
    if (isAnimatedState(indicatorState) || transitionProgress < 1f || visualScale < 1f) {
      postOnAnimation(animationTick)
    }
  }

  private fun drawMicrophone(canvas: Canvas, centerX: Float, centerY: Float) {
    foregroundPaint.color = Color.WHITE
    foregroundPaint.style = Paint.Style.FILL
    microphoneCapsuleRect.set(
      centerX - dp(7f),
      centerY - dp(12f),
      centerX + dp(7f),
      centerY + dp(4f),
    )
    canvas.drawRoundRect(microphoneCapsuleRect, dp(7f), dp(7f), foregroundPaint)
    foregroundPaint.style = Paint.Style.STROKE
    foregroundPaint.strokeWidth = dp(2f)
    microphoneArcRect.set(
      centerX - dp(11f),
      centerY - dp(8f),
      centerX + dp(11f),
      centerY + dp(10f),
    )
    canvas.drawArc(microphoneArcRect, 0f, 180f, false, foregroundPaint)
    canvas.drawLine(centerX, centerY + dp(10f), centerX, centerY + dp(15f), foregroundPaint)
    canvas.drawLine(centerX - dp(5f), centerY + dp(15f), centerX + dp(5f), centerY + dp(15f), foregroundPaint)
    foregroundPaint.style = Paint.Style.FILL
  }

  private fun drawWaveform(canvas: Canvas, centerX: Float, centerY: Float) {
    waveformPaint.color = Color.WHITE
    waveformHeights.forEachIndexed { index, baseHeight ->
      val pulse = 0.65f + 0.35f * abs(sin(animationPhase + index * 0.8f))
      val level = 0.14f + smoothedVolume * 0.86f
      val barHeight = dp(18f) * max(0.14f, level) * baseHeight * pulse
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

  private fun currentBackgroundColor(): Int = blendColor(
    transitionFromColor,
    transitionToColor,
    smoothStep(transitionProgress),
  )

  private fun backgroundColorFor(state: MicIndicatorState): Int = when (state) {
    MicIndicatorState.IDLE -> Color.rgb(24, 24, 30)
    MicIndicatorState.STARTING -> Color.rgb(54, 93, 140)
    MicIndicatorState.RECORDING -> Color.rgb(154, 54, 70)
    MicIndicatorState.PROCESSING -> Color.rgb(80, 70, 142)
    MicIndicatorState.SUCCESS -> Color.rgb(45, 126, 87)
    MicIndicatorState.ERROR -> Color.rgb(150, 73, 52)
  }

  private fun normalizeVolume(value: Float): Float {
    val rms = value.coerceIn(0f, 1f)
    if (rms <= 0f) return 0f
    val decibels = 20f * log10(rms.coerceAtLeast(MIN_RMS))
    return ((decibels - METER_FLOOR_DB) / (METER_CEILING_DB - METER_FLOOR_DB))
      .coerceIn(0f, 1f)
  }

  private fun isAnimatedState(state: MicIndicatorState): Boolean =
    state == MicIndicatorState.RECORDING ||
      state == MicIndicatorState.STARTING ||
      state == MicIndicatorState.PROCESSING

  private fun smoothStep(value: Float): Float {
    val clamped = value.coerceIn(0f, 1f)
    return clamped * clamped * (3f - 2f * clamped)
  }

  private fun blendColor(from: Int, to: Int, fraction: Float): Int {
    val red = (Color.red(from) + (Color.red(to) - Color.red(from)) * fraction).roundToInt()
    val green = (Color.green(from) + (Color.green(to) - Color.green(from)) * fraction).roundToInt()
    val blue = (Color.blue(from) + (Color.blue(to) - Color.blue(from)) * fraction).roundToInt()
    return Color.rgb(red, green, blue)
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

  private companion object {
    const val METER_FLOOR_DB = -52f
    const val METER_CEILING_DB = -9f
    const val MIN_RMS = 0.0001f
  }
}
