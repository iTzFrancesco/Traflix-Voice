package it.traflix.voice

import kotlin.math.hypot
import kotlin.math.roundToInt

/** Separates a tap from a drag, even when dragging is disabled during dictation. */
internal class VoiceOverlayGesture(private val touchSlop: Int) {
  private var active = false
  private var canDrag = false
  private var startX = 0f
  private var startY = 0f
  private var lastX = 0f
  private var lastY = 0f
  var moved = false
    private set
  var dragged = false
    private set

  fun begin(x: Float, y: Float, allowDrag: Boolean) {
    active = true
    canDrag = allowDrag
    startX = x
    startY = y
    lastX = x
    lastY = y
    moved = false
    dragged = false
  }

  fun move(x: Float, y: Float): Pair<Int, Int>? {
    if (!active) return null
    if (hypot(x - startX, y - startY) >= touchSlop) moved = true
    if (!moved || !canDrag) return null
    val delta = (x - lastX).roundToInt() to (y - lastY).roundToInt()
    lastX = x
    lastY = y
    dragged = true
    return delta.takeIf { it.first != 0 || it.second != 0 }
  }

  fun finish(): Boolean {
    val tapped = active && !moved
    active = false
    return tapped
  }

  fun cancel() {
    active = false
  }
}
