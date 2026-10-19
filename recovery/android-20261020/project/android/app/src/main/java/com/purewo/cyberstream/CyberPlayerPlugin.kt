package com.purewo.cyberstream

import android.app.Activity
import android.content.Intent
import android.net.Uri
import androidx.activity.result.ActivityResult
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin

/**
 * Capacitor bridge for the Android Media3 player.
 *
 * The WebView owns login cookies and therefore prepares ticketed URLs before
 * calling this plugin. The native side only receives an opaque playback
 * session and never persists or inspects the user's authenticated cookie.
 */
@CapacitorPlugin(name = "CyberPlayer")
class CyberPlayerPlugin : Plugin() {
    @Volatile
    private var activePlayerSessionId: String? = null

    companion object {
        @Volatile
        private var activePlugin: CyberPlayerPlugin? = null

        fun emitProgress(
            sessionId: String,
            resourceId: String,
            positionMs: Long,
            durationMs: Long,
            state: String,
        ) {
            activePlugin?.publishProgress(sessionId, resourceId, positionMs, durationMs, state)
        }
    }

    override fun load() {
        super.load()
        activePlugin = this
    }

    override fun handleOnDestroy() {
        synchronized(this) {
            activePlayerSessionId?.let { PlayerActivity.discardStoredSession(it) }
            activePlayerSessionId = null
        }
        if (activePlugin === this) activePlugin = null
        super.handleOnDestroy()
    }

    @PluginMethod
    fun open(call: PluginCall) {
        val session = call.getObject("session")
        if (session == null) {
            call.reject("Missing playback session")
            return
        }

        val sessionId = session.optString("sessionId")
        if (sessionId.isBlank()) {
            call.reject("Missing playback session id")
            return
        }
        synchronized(this) {
            if (activePlayerSessionId != null) {
                call.reject("A native player is already open")
                return
            }
            if (!PlayerActivity.storeSession(sessionId, session.toString())) {
                call.reject("Unable to prepare playback session")
                return
            }
            activePlayerSessionId = sessionId
        }

        try {
            val intent = Intent(activity, PlayerActivity::class.java)
                .putExtra(PlayerActivity.EXTRA_SESSION_ID, sessionId)
            startActivityForResult(call, intent, "handlePlayerResult")
        } catch (error: Exception) {
            synchronized(this) {
                if (activePlayerSessionId == sessionId) activePlayerSessionId = null
            }
            PlayerActivity.discardStoredSession(sessionId)
            call.reject("Unable to launch native player", error)
        }
    }

    @ActivityCallback
    private fun handlePlayerResult(call: PluginCall, result: ActivityResult) {
        synchronized(this) {
            activePlayerSessionId = null
        }
        val data = result.data
        if (result.resultCode != Activity.RESULT_OK || data == null) {
            call.reject("Native player closed before it returned playback state")
            return
        }
        val sessionId = data.getStringExtra(PlayerActivity.RESULT_SESSION_ID)
        if (sessionId.isNullOrBlank()) {
            call.reject("Native player returned an invalid playback result")
            return
        }
        val payload = JSObject()
        payload.put("sessionId", sessionId)
        payload.put("resourceId", data.getStringExtra(PlayerActivity.RESULT_RESOURCE_ID))
        payload.put("positionMs", data.getLongExtra(PlayerActivity.RESULT_POSITION_MS, 0L))
        payload.put("durationMs", data.getLongExtra(PlayerActivity.RESULT_DURATION_MS, 0L))
        payload.put("ended", data.getBooleanExtra(PlayerActivity.RESULT_ENDED, false))
        payload.put("authExpired", data.getBooleanExtra(PlayerActivity.RESULT_AUTH_EXPIRED, false))
        payload.put("error", data.getStringExtra(PlayerActivity.RESULT_ERROR))
        call.resolve(payload)
    }

    @PluginMethod
    fun openExternalUrl(call: PluginCall) {
        val rawUrl = call.getString("url")
        if (rawUrl.isNullOrBlank()) {
            call.reject("Missing URL")
            return
        }

        try {
            val intent = if (rawUrl.startsWith("intent:")) {
                Intent.parseUri(rawUrl, Intent.URI_INTENT_SCHEME)
            } else {
                Intent(Intent.ACTION_VIEW, Uri.parse(rawUrl))
            }
            intent.component = null
            if (intent.resolveActivity(activity.packageManager) == null) {
                call.reject("No Android application can handle this URL")
                return
            }
            activity.startActivity(intent)
            call.resolve()
        } catch (error: Exception) {
            call.reject("Unable to open external URL", error)
        }
    }

    private fun publishProgress(
        sessionId: String,
        resourceId: String,
        positionMs: Long,
        durationMs: Long,
        state: String,
    ) {
        notifyListeners(
            "progress",
            JSObject().apply {
                put("sessionId", sessionId)
                put("resourceId", resourceId)
                put("positionMs", positionMs)
                put("durationMs", durationMs)
                put("state", state)
            },
            true,
        )
    }
}
