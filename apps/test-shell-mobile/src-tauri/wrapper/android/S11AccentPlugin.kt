package org.example.shellspikes.accent

import android.app.Activity
import android.content.Intent
import android.os.SystemClock
import androidx.appcompat.app.AppCompatActivity
import android.webkit.WebView
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin

/** Coordinator-owned Tauri lifecycle wrapper for the lane-owned AndroidAccentReader. */
@TauriPlugin
class S11AccentPlugin(private val activity: Activity) : Plugin(activity) {
    @Volatile
    private var latest: AccentUpdate? = null

    private var reader: AndroidAccentReader? = null
    private var hasResumed = false

    override fun load(webView: WebView) {
        if (reader == null) {
            reader = AndroidAccentReader(
                context = activity.applicationContext,
                // Synthetic adapter fault fixture; never counted as an OS event.
                readSystemAccent = { context ->
                    if (activity.intent.getBooleanExtra("shellSpikeAccentProviderUnavailable", false)) {
                        throw IllegalStateException("Synthetic dynamic-colour provider unavailable")
                    }
                    context.getColor(android.R.color.system_accent1_500)
                },
                publish = { update ->
                    latest = update
                    trigger("accent-update", update.toPayload())
                },
            )
        }
    }

    @Command
    fun currentAccent(invoke: Invoke) {
        val snapshot = latest
        if (snapshot == null) {
            invoke.resolve(
                JSObject().apply {
                    put("available", false)
                    put("reason", "reader-starting")
                    put("rgb", null)
                    put("sequence", 0)
                    put("source", "system")
                    put("portalInterfaceVersion", null)
                },
            )
            return
        }
        invoke.resolve(snapshot.toPayload())
    }

    override fun onNewIntent(intent: Intent) {
        reader?.onActivityRecreated()
    }

    override fun onResume(activity: AppCompatActivity) {
        if (hasResumed) reader?.onActivityRecreated()
        hasResumed = true
    }

    override fun onDestroy(activity: AppCompatActivity) {
        reader?.close()
        reader = null
        latest = null
    }

    private fun AccentUpdate.toPayload(): JSObject = JSObject().apply {
        put("available", available)
        put("reason", reason)
        put("rgb", rgb)
        put("sequence", sourceSequence)
        put("nativeEventNs", monotonicNanos)
        put("hostUpdateNs", SystemClock.elapsedRealtimeNanos())
        put("nativeEvent", nativeEvent)
        put("cause", cause)
        put("source", "system")
        put("portalInterfaceVersion", null)
        put("wallpaperId", wallpaperId)
        put("resourceArgb", resourceArgb)
        put("activityGeneration", activityGeneration)
        put("permissionPrompt", permissionPrompt)
    }
}
