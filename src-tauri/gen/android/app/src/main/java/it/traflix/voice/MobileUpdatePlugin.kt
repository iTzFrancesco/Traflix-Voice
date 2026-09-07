package it.traflix.voice

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import androidx.appcompat.app.AppCompatActivity
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.Plugin
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.Executors
import java.util.zip.ZipFile
import org.json.JSONArray
import org.json.JSONObject

@InvokeArg
class MobileUpdateInstallArgs {
  var tag: String? = null
}

@TauriPlugin
class MobileUpdatePlugin(private val activity: Activity) : Plugin(activity) {
  private val executor = Executors.newSingleThreadExecutor { runnable ->
    Thread(runnable, "traflix-mobile-updater").apply { isDaemon = true }
  }

  override fun onDestroy(activity: AppCompatActivity) {
    executor.shutdownNow()
    super.onDestroy(activity)
  }

  @Command
  fun checkMobileUpdate(invoke: Invoke) {
    executor.execute {
      try {
        val installedVersion = currentVersion()
        val update = findLatestUpdate()
        resolve(
          invoke,
          update?.toMap(installedVersion) ?: mapOf(
            "available" to false,
            "currentVersion" to installedVersion.toString(),
          ),
        )
      } catch (error: Exception) {
        reject(invoke, error.message ?: "Controllo aggiornamenti non riuscito")
      }
    }
  }

  @Command
  fun installMobileUpdate(invoke: Invoke) {
    val args = invoke.parseArgs(MobileUpdateInstallArgs::class.java)
    val requestedTag = args.tag?.trim().orEmpty()

    executor.execute {
      try {
        val update = findUpdateByTag(requestedTag)
          ?: throw IOException("Release mobile non trovata")
        if (update.version <= currentVersion()) {
          throw IOException("La release mobile installata è già aggiornata")
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
          !activity.packageManager.canRequestPackageInstalls()
        ) {
          activity.runOnUiThread {
            try {
              activity.startActivity(
                Intent(
                  Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                  Uri.parse("package:${activity.packageName}"),
                ),
              )
              invoke.resolveObject(mapOf("status" to "permission_required"))
            } catch (error: Exception) {
              invoke.reject(error.message ?: "Impossibile aprire le impostazioni di installazione")
            }
          }
          return@execute
        }

        val apk = download(update)
        val uri = FileProvider.getUriForFile(
          activity,
          "${activity.packageName}.fileprovider",
          apk,
        )
        activity.runOnUiThread {
          try {
            val intent = Intent(Intent.ACTION_VIEW).apply {
              setDataAndType(uri, APK_MIME_TYPE)
              addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
              addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            activity.startActivity(intent)
            invoke.resolveObject(
              mapOf(
                "status" to "installer_opened",
                "version" to update.version.toString(),
              ),
            )
          } catch (error: ActivityNotFoundException) {
            invoke.reject("Package installer Android non disponibile")
          } catch (error: Exception) {
            invoke.reject(error.message ?: "Impossibile avviare l'installazione")
          }
        }
      } catch (error: Exception) {
        reject(invoke, error.message ?: "Download aggiornamento non riuscito")
      }
    }
  }

  private fun currentVersion(): MobileVersion =
    parseVersion(BuildConfig.VERSION_NAME) ?: MobileVersion(0, 0, 0)

  private fun findLatestUpdate(): MobileRelease? {
    val releases = fetchReleases()
    return releases
      .filter { it.version > currentVersion() }
      .maxByOrNull { it.version }
  }

  private fun findUpdateByTag(tag: String): MobileRelease? {
    if (!TAG_PATTERN.matches(tag)) return null
    return fetchReleases().firstOrNull { it.tag == tag }
  }

  private fun fetchReleases(): List<MobileRelease> {
    val connection = (URL(RELEASES_URL).openConnection() as HttpURLConnection).apply {
      requestMethod = "GET"
      connectTimeout = NETWORK_TIMEOUT_MS
      readTimeout = NETWORK_TIMEOUT_MS
      instanceFollowRedirects = true
      useCaches = false
      setRequestProperty("Accept", "application/vnd.github+json")
      setRequestProperty("Cache-Control", "no-cache")
      setRequestProperty("Pragma", "no-cache")
      setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
      setRequestProperty("User-Agent", "Traflix-Voice-Android")
    }

    return try {
      val responseCode = connection.responseCode
      if (responseCode !in 200..299) {
        throw IOException("GitHub ha restituito HTTP $responseCode")
      }
      val body = connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
      val releases = JSONArray(body)
      buildList {
        for (index in 0 until releases.length()) {
          parseRelease(releases.optJSONObject(index))?.let(::add)
        }
      }
    } finally {
      connection.disconnect()
    }
  }

  private fun parseRelease(release: JSONObject?): MobileRelease? {
    if (release == null || release.optBoolean("draft", true)) return null

    val tag = release.optString("tag_name").trim()
    if (!TAG_PATTERN.matches(tag)) return null
    val version = parseVersion(tag) ?: return null
    val assets = release.optJSONArray("assets") ?: return null
    val apk = (0 until assets.length())
      .asSequence()
      .mapNotNull { assets.optJSONObject(it) }
      .firstOrNull { it.optString("name") == APK_ASSET_NAME }
      ?: return null
    val downloadUrl = apk.optString("browser_download_url").trim()
    if (!isAllowedDownloadUrl(downloadUrl)) return null
    val rawDigest = apk.optString("digest").trim().removePrefix("sha256:").lowercase(Locale.US)
    if (rawDigest.isNotEmpty() && !SHA256_PATTERN.matches(rawDigest)) return null

    return MobileRelease(
      tag = tag,
      version = version,
      name = release.optString("name", tag).trim().ifEmpty { tag },
      notes = release.optString("body").trim(),
      publishedAt = release.optString("published_at").trim(),
      assetName = APK_ASSET_NAME,
      size = apk.optLong("size", 0L),
      downloadUrl = downloadUrl,
      sha256 = rawDigest.ifEmpty { null },
    )
  }

  private fun download(update: MobileRelease): java.io.File {
    val connection = (URL(update.downloadUrl).openConnection() as HttpURLConnection).apply {
      requestMethod = "GET"
      connectTimeout = NETWORK_TIMEOUT_MS
      readTimeout = DOWNLOAD_TIMEOUT_MS
      instanceFollowRedirects = true
      useCaches = false
      setRequestProperty("Accept", "application/octet-stream")
      setRequestProperty("User-Agent", "Traflix-Voice-Android")
    }
    val temporaryFile = java.io.File(activity.cacheDir, "$APK_ASSET_NAME.part")
    val apkFile = java.io.File(activity.cacheDir, APK_ASSET_NAME)
    temporaryFile.delete()
    apkFile.delete()

    return try {
      val responseCode = connection.responseCode
      if (responseCode !in 200..299) {
        throw IOException("Download APK fallito (HTTP $responseCode)")
      }
      val contentLength = connection.contentLengthLong
      if (contentLength > MAX_APK_BYTES) {
        throw IOException("APK troppo grande")
      }

      var totalBytes = 0L
      val digest = MessageDigest.getInstance("SHA-256")
      connection.inputStream.use { input ->
        temporaryFile.outputStream().use { output ->
          val buffer = ByteArray(BUFFER_SIZE)
          while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            totalBytes += read
            if (totalBytes > MAX_APK_BYTES) throw IOException("APK troppo grande")
            digest.update(buffer, 0, read)
            output.write(buffer, 0, read)
          }
        }
      }
      if (totalBytes == 0L || (update.size > 0L && totalBytes != update.size)) {
        throw IOException("APK incompleto")
      }
      val actualSha256 = digest.digest().joinToString("") { byte ->
        "%02x".format(Locale.US, byte.toInt() and 0xff)
      }
      if (update.sha256 != null && !update.sha256.equals(actualSha256, ignoreCase = true)) {
        throw IOException("Hash SHA-256 dell'APK non corrispondente")
      }
      validateCompatibleApk(temporaryFile)
      if (!temporaryFile.renameTo(apkFile)) {
        throw IOException("Impossibile preparare l'APK")
      }
      apkFile
    } catch (error: Exception) {
      temporaryFile.delete()
      apkFile.delete()
      throw error
    } finally {
      connection.disconnect()
    }
  }

  private fun validateCompatibleApk(apkFile: java.io.File) {
    val deviceAbis = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
      Build.SUPPORTED_ABIS.toList()
    } else {
      listOf(Build.CPU_ABI, Build.CPU_ABI2).filter(String::isNotEmpty)
    }
    val packagedAbis = ZipFile(apkFile).use { zip ->
      zip.entries().asSequence()
        .mapNotNull { entry -> NATIVE_LIB_PATTERN.matchEntire(entry.name)?.groupValues?.get(1) }
        .toSet()
    }
    if (packagedAbis.isNotEmpty() && deviceAbis.none { it in packagedAbis }) {
      throw IOException(
        "APK non compatibile con l'ABI del dispositivo (${deviceAbis.joinToString()})",
      )
    }
  }

  private fun isAllowedDownloadUrl(value: String): Boolean {
    val uri = Uri.parse(value)
    return uri.scheme == "https" &&
      uri.host == "github.com" &&
      uri.path?.startsWith("/$GITHUB_OWNER/$GITHUB_REPOSITORY/releases/download/") == true
  }

  private fun resolve(invoke: Invoke, value: Map<String, Any?>) {
    activity.runOnUiThread { invoke.resolveObject(value) }
  }

  private fun reject(invoke: Invoke, message: String) {
    activity.runOnUiThread { invoke.reject(message) }
  }

  private data class MobileRelease(
    val tag: String,
    val version: MobileVersion,
    val name: String,
    val notes: String,
    val publishedAt: String,
    val assetName: String,
    val size: Long,
    val downloadUrl: String,
    val sha256: String?,
  ) {
    fun toMap(currentVersion: MobileVersion): Map<String, Any?> = mapOf(
      "available" to true,
      "tag" to tag,
      "version" to version.toString(),
      "currentVersion" to currentVersion.toString(),
      "name" to name,
      "notes" to notes.take(MAX_NOTES_LENGTH),
      "publishedAt" to publishedAt,
      "assetName" to assetName,
      "size" to size,
    )
  }

  private data class MobileVersion(
    val major: Int,
    val minor: Int,
    val patch: Int,
  ) : Comparable<MobileVersion> {
    override fun compareTo(other: MobileVersion): Int =
      compareValuesBy(this, other, MobileVersion::major, MobileVersion::minor, MobileVersion::patch)

    override fun toString(): String = "$major.$minor.$patch"
  }

  private fun parseVersion(tagOrVersion: String): MobileVersion? {
    val match = VERSION_PATTERN.matchEntire(tagOrVersion.trim()) ?: return null
    return MobileVersion(
      major = match.groupValues[1].toIntOrNull() ?: return null,
      minor = match.groupValues[2].toIntOrNull() ?: return null,
      patch = match.groupValues[3].toIntOrNull() ?: return null,
    )
  }

  companion object {
    private const val GITHUB_OWNER = "iTzFrancesco"
    private const val GITHUB_REPOSITORY = "Traflix-Voice"
    private const val RELEASES_URL =
      "https://api.github.com/repos/$GITHUB_OWNER/$GITHUB_REPOSITORY/releases?per_page=100"
    private const val APK_ASSET_NAME = "app-universal-release.apk"
    private const val APK_MIME_TYPE = "application/vnd.android.package-archive"
    private const val NETWORK_TIMEOUT_MS = 10_000
    private const val DOWNLOAD_TIMEOUT_MS = 120_000
    private const val MAX_APK_BYTES = 150L * 1024L * 1024L
    private const val BUFFER_SIZE = 32 * 1024
    private const val MAX_NOTES_LENGTH = 2_000
    private val TAG_PATTERN = Regex("android-v\\d+\\.\\d+\\.\\d+(?:[-+].*)?")
    private val VERSION_PATTERN = Regex("(?:android-v)?(\\d+)\\.(\\d+)\\.(\\d+)(?:[-+].*)?")
    private val SHA256_PATTERN = Regex("[0-9a-f]{64}")
    private val NATIVE_LIB_PATTERN = Regex("^lib/([^/]+)/.+\\.so$")
  }
}
