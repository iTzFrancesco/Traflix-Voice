package it.traflix.voice

import java.util.concurrent.atomic.AtomicLong

/** One session's stop deadline, measured with Android's monotonic clock. */
internal class VoiceCaptureTail {
  private val stopAtMs = AtomicLong(Long.MAX_VALUE)

  val stopRequested: Boolean get() = stopAtMs.get() != Long.MAX_VALUE

  fun requestStop(nowMs: Long): Boolean =
    stopAtMs.compareAndSet(Long.MAX_VALUE, nowMs + TAIL_DURATION_MS)

  fun shouldCapture(nowMs: Long): Boolean = nowMs < stopAtMs.get()

  companion object {
    const val TAIL_DURATION_MS = 220L
  }
}
