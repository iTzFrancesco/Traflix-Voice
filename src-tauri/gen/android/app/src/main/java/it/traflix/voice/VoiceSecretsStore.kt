package it.traflix.voice

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Stores the optional prototype BYOK credential encrypted with Android Keystore. */
class VoiceSecretsStore(context: Context) {
  private val preferences = context.applicationContext.getSharedPreferences(
    PREFERENCES_NAME,
    Context.MODE_PRIVATE,
  )

  fun setGroqApiKey(value: String) {
    val normalized = value.trim()
    if (normalized.isEmpty()) {
      preferences.edit().remove(GROQ_KEY).apply()
      return
    }

    val cipher = Cipher.getInstance(TRANSFORMATION)
    cipher.init(Cipher.ENCRYPT_MODE, key())
    val encrypted = Base64.encodeToString(cipher.doFinal(normalized.toByteArray(StandardCharsets.UTF_8)), Base64.NO_WRAP)
    val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
    preferences.edit().putString(GROQ_KEY, "$iv:$encrypted").apply()
  }

  fun groqApiKey(): String? {
    val stored = preferences.getString(GROQ_KEY, null) ?: return null
    val pieces = stored.split(":", limit = 2)
    if (pieces.size != 2) return null

    return runCatching {
      val cipher = Cipher.getInstance(TRANSFORMATION)
      cipher.init(
        Cipher.DECRYPT_MODE,
        key(),
        GCMParameterSpec(GCM_TAG_LENGTH, Base64.decode(pieces[0], Base64.NO_WRAP)),
      )
      String(cipher.doFinal(Base64.decode(pieces[1], Base64.NO_WRAP)), StandardCharsets.UTF_8)
    }.getOrNull()
  }

  private fun key(): SecretKey {
    val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
    val existing = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
    if (existing != null) return existing

    val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
    generator.init(
      KeyGenParameterSpec.Builder(
        KEY_ALIAS,
        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
      )
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
        .build(),
    )
    return generator.generateKey()
  }

  private companion object {
    const val ANDROID_KEYSTORE = "AndroidKeyStore"
    const val KEY_ALIAS = "traflix_voice_groq_api_key"
    const val PREFERENCES_NAME = "voice_secrets"
    const val GROQ_KEY = "groq_api_key"
    const val TRANSFORMATION = "AES/GCM/NoPadding"
    const val GCM_TAG_LENGTH = 128
  }
}
