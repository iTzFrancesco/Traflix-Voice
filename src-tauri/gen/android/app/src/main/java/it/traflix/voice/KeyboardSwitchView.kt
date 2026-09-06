package it.traflix.voice

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.view.View
import kotlin.math.roundToInt

/** Small authored keyboard glyph used instead of a font/emoji symbol. */
class KeyboardSwitchView(context: Context) : View(context) {
  private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG)
  private val outlinePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.STROKE
    strokeWidth = dp(1.5f)
  }
  private val keyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
    style = Paint.Style.FILL
  }

  init {
    isClickable = true
    contentDescription = "Torna alla tastiera precedente"
    minimumWidth = dp(56f).roundToInt()
    minimumHeight = dp(56f).roundToInt()
  }

  override fun onDraw(canvas: Canvas) {
    super.onDraw(canvas)
    val centerX = width / 2f
    val centerY = height / 2f
    val box = RectF(
      centerX - dp(22f),
      centerY - dp(17f),
      centerX + dp(22f),
      centerY + dp(17f),
    )
    backgroundPaint.color = if (isPressed) Color.rgb(56, 56, 67) else Color.rgb(43, 43, 53)
    canvas.drawRoundRect(box, dp(9f), dp(9f), backgroundPaint)

    outlinePaint.color = if (isPressed) Color.rgb(255, 157, 36) else Color.rgb(116, 116, 130)
    canvas.drawRoundRect(box, dp(9f), dp(9f), outlinePaint)

    keyPaint.color = if (isPressed) Color.rgb(255, 193, 105) else Color.rgb(206, 206, 218)
    val rows = listOf(4, 4)
    rows.forEachIndexed { row, count ->
      val y = centerY - dp(7f) + row * dp(7f)
      for (index in 0 until count) {
        val x = centerX - dp(13.5f) + index * dp(9f)
        canvas.drawCircle(x, y, dp(1.35f), keyPaint)
      }
    }
    canvas.drawRoundRect(
      RectF(centerX - dp(12f), centerY + dp(8f), centerX + dp(12f), centerY + dp(10.5f)),
      dp(1.5f),
      dp(1.5f),
      keyPaint,
    )
  }

  override fun performClick(): Boolean {
    super.performClick()
    return true
  }

  private fun dp(value: Float): Float = (value * resources.displayMetrics.density).roundToInt().toFloat()
}
