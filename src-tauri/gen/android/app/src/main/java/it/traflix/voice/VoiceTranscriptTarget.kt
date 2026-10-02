package it.traflix.voice

import java.util.concurrent.atomic.AtomicBoolean

internal data class VoiceEditorIdentity(val packageName: String, val generation: Long)

/** A one-shot IME destination, invalidated whenever Android changes editors. */
internal class VoiceTranscriptTarget(
  private val identity: VoiceEditorIdentity,
  private val currentIdentity: () -> VoiceEditorIdentity?,
  private val commitText: (String) -> Boolean,
) {
  private val consumed = AtomicBoolean(false)

  fun commit(text: String): Boolean {
    return runCatching {
      if (text.isBlank() || currentIdentity() != identity || !consumed.compareAndSet(false, true)) {
        false
      } else {
        commitText(text)
      }
    }.getOrDefault(false)
  }
}
