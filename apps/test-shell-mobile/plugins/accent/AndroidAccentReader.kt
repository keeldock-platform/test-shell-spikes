package org.example.shellspikes.accent

import android.app.WallpaperManager
import android.content.ComponentCallbacks
import android.content.Context
import android.content.res.Configuration
import android.graphics.Color
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock

/** Android 12+ wallpaper-derived system accent reader for the disposable shell. */
class AndroidAccentReader(
    context: Context,
    private val publish: (AccentUpdate) -> Unit,
    private val readSystemAccent: (Context) -> Int = { it.getColor(android.R.color.system_accent1_500) },
) : ComponentCallbacks, AutoCloseable {
    private val appContext = context.applicationContext
    private val wallpaperManager = WallpaperManager.getInstance(appContext)
    private val mainHandler = Handler(Looper.getMainLooper())
    private var sequence = 0L
    private var activityGeneration = 0
    private var closed = false
    private var lastPublishedFingerprint: String? = null

    private val wallpaperListener = WallpaperManager.OnColorsChangedListener { _, which ->
        if (which and WallpaperManager.FLAG_SYSTEM != 0) {
            refresh("wallpaper-callback", nativeEvent = true)
        }
    }

    init {
        appContext.registerComponentCallbacks(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            wallpaperManager.addOnColorsChangedListener(wallpaperListener, mainHandler)
        }
        refresh("initial-read", nativeEvent = false)
    }

    /** The wrapper calls this after an Activity is recreated; it is a read-back, not a fake event. */
    fun onActivityRecreated() {
        mainHandler.post {
            if (!closed) {
                activityGeneration += 1
                refresh("activity-recreated-read", nativeEvent = false)
            }
        }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        // A configuration callback is a real platform callback. Treat it as an accent event only
        // when the system resource or wallpaper ID has actually changed; orientation-only updates
        // must not create duplicate token updates.
        refresh("configuration-changed", nativeEvent = true)
    }

    override fun onLowMemory() = Unit

    private fun refresh(cause: String, nativeEvent: Boolean) {
        if (closed) {
            return
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            publish(unavailable("api-below-31", cause))
            return
        }

        val resourceColour = try {
            readSystemAccent(appContext)
        } catch (_: RuntimeException) {
            publish(unavailable("dynamic-colour-resource-unavailable", cause))
            return
        }

        val wallpaperId = try {
            wallpaperManager.getWallpaperId(WallpaperManager.FLAG_SYSTEM)
        } catch (_: RuntimeException) {
            -1
        }
        val red = Color.red(resourceColour)
        val green = Color.green(resourceColour)
        val blue = Color.blue(resourceColour)
        val fingerprint = "$wallpaperId:$resourceColour"

        // The wallpaper listener and ComponentCallbacks can both report one palette change. Keep
        // one native update for the changed resource/wallpaper fingerprint. Recreation reads stay
        // non-native and are retained for lifecycle evidence.
        if (nativeEvent && fingerprint == lastPublishedFingerprint) {
            return
        }
        lastPublishedFingerprint = fingerprint

        sequence += 1
        publish(
            AccentUpdate(
                available = true,
                reason = null,
                rgb = listOf(red / 255.0, green / 255.0, blue / 255.0),
                wallpaperId = wallpaperId,
                resourceArgb = String.format("#%08X", resourceColour),
                sourceSequence = sequence,
                nativeEvent = nativeEvent,
                cause = cause,
                activityGeneration = activityGeneration,
                monotonicNanos = SystemClock.elapsedRealtimeNanos(),
                permissionPrompt = false,
            ),
        )
    }

    private fun unavailable(reason: String, cause: String) = AccentUpdate(
        available = false,
        reason = reason,
        rgb = null,
        wallpaperId = null,
        resourceArgb = null,
        sourceSequence = ++sequence,
        nativeEvent = false,
        cause = cause,
        activityGeneration = activityGeneration,
        monotonicNanos = SystemClock.elapsedRealtimeNanos(),
        permissionPrompt = false,
    )

    override fun close() {
        if (closed) return
        closed = true
        appContext.unregisterComponentCallbacks(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            wallpaperManager.removeOnColorsChangedListener(wallpaperListener)
        }
    }
}

data class AccentUpdate(
    val available: Boolean,
    val reason: String?,
    val rgb: List<Double>?,
    val wallpaperId: Int?,
    val resourceArgb: String?,
    val sourceSequence: Long,
    val nativeEvent: Boolean,
    val cause: String,
    val activityGeneration: Int,
    val monotonicNanos: Long,
    val permissionPrompt: Boolean,
)
