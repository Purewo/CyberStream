package com.purewo.cyberstream

import android.app.Activity
import android.app.PictureInPictureParams
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.content.pm.ActivityInfo
import android.graphics.BitmapFactory
import android.graphics.Typeface
import android.graphics.Color
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.util.Rational
import android.view.Gravity
import android.view.inputmethod.EditorInfo
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.GridLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.Lifecycle
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.ForwardingPlayer
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.TrackGroup
import androidx.media3.common.TrackSelectionOverride
import androidx.media3.common.Tracks
import androidx.media3.common.text.CueGroup
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.HttpDataSource
import androidx.media3.exoplayer.DecoderReuseEvaluation
import androidx.media3.exoplayer.DefaultRenderersFactory
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.analytics.AnalyticsListener
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.exoplayer.trackselection.DefaultTrackSelector
import androidx.media3.session.MediaSession
import androidx.media3.ui.PlayerView
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.CaptionStyleCompat
import androidx.media3.ui.SubtitleView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.lang.reflect.InvocationTargetException
import java.lang.reflect.Proxy
import java.util.IdentityHashMap
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Full-screen Media3 playback surface for CyberStream Android.
 *
 * The WebView exchanges its authenticated session for short-lived playback
 * tickets, then this Activity plays only the original file. Server/provider
 * transcodes are deliberately excluded from the Android session.
 */
@UnstableApi
class PlayerActivity : AppCompatActivity() {
    companion object {
        const val EXTRA_SESSION_ID = "cyberstream.playback.session_id"
        /** Legacy-only fallback. New launches use the in-process registry below. */
        const val EXTRA_SESSION_JSON = "cyberstream.playback.session"
        const val EXTRA_CELLULAR_NETWORK_FOR_TESTING = "cyberstream.playback.test_cellular_network"

        const val RESULT_SESSION_ID = "sessionId"
        const val RESULT_RESOURCE_ID = "resourceId"
        const val RESULT_POSITION_MS = "positionMs"
        const val RESULT_DURATION_MS = "durationMs"
        const val RESULT_ENDED = "ended"
        const val RESULT_AUTH_EXPIRED = "authExpired"
        const val RESULT_ERROR = "error"

        private const val PROGRESS_INTERVAL_MS = 10_000L
        private const val STORED_SESSION_TTL_MS = 10 * 60 * 1000L
        private const val CONTROLLER_TIMEOUT_MS = 3_000
        private const val MAX_GESTURE_SEEK_RANGE_MS = 5 * 60 * 1000L
        private const val MIN_GESTURE_SEEK_RANGE_MS = 60 * 1000L
        private const val ONLINE_SUBTITLE_PREVIEW_ID = "__online_subtitle_preview__"
        private const val STATE_STORED_SESSION_ID = "cyberstream.state.session_id"
        private const val STATE_RESOURCE_ID = "cyberstream.state.resource_id"
        private const val STATE_POSITION_MS = "cyberstream.state.position_ms"
        private const val STATE_CELLULAR_ALLOWED_FOR_SESSION = "cyberstream.state.cellular_allowed"
        private const val PLAYER_PREFERENCES = "cyber_player_settings"
        private const val PREF_ALLOW_CELLULAR_PLAYBACK = "allow_cellular_playback"
        private const val LOG_TAG = "CyberStreamPlayer"

        private data class StoredSession(
            val rawSession: String,
            val createdAtMs: Long,
        )

        /**
         * Intent extras cross Binder and have a practical ~1 MB ceiling. A
         * long series can contain hundreds of ticketed resources/subtitles, so
         * keep the opaque JSON in-process and hand the Activity only its id.
         */
        private val storedSessions = ConcurrentHashMap<String, StoredSession>()

        fun storeSession(sessionId: String, rawSession: String): Boolean {
            if (sessionId.isBlank() || rawSession.isBlank()) return false
            pruneStoredSessions()
            storedSessions[sessionId] = StoredSession(rawSession, System.currentTimeMillis())
            return true
        }

        fun discardStoredSession(sessionId: String) {
            if (sessionId.isNotBlank()) storedSessions.remove(sessionId)
        }

        private fun takeStoredSession(sessionId: String?): String? {
            if (sessionId.isNullOrBlank()) return null
            pruneStoredSessions()
            return storedSessions.remove(sessionId)?.rawSession
        }

        private fun pruneStoredSessions(nowMs: Long = System.currentTimeMillis()) {
            storedSessions.entries.removeIf { (_, value) -> nowMs - value.createdAtMs > STORED_SESSION_TTL_MS }
        }
    }

    private data class AudioTrackChoice(
        val group: TrackGroup,
        val trackIndex: Int,
        val format: Format,
        val selected: Boolean,
        val supported: Boolean,
    )

    private data class SubtitleTrackChoice(
        val group: TrackGroup,
        val trackIndex: Int,
        val format: Format,
        val selected: Boolean,
        val supported: Boolean,
    )

    private data class PanelItem(
        val title: String,
        val subtitle: String? = null,
        val selected: Boolean = false,
        val enabled: Boolean = true,
        val closeOnAction: Boolean = true,
        val action: () -> Unit,
    )

    private data class EpisodeGroup(
        val key: String,
        val resources: List<JSONObject>,
    )

    private data class CloudQuality(
        val resolution: String,
        val label: String,
        val url: String,
        val rank: Int,
        val format: String?,
        val width: Int?,
        val height: Int?,
        val bitrate: Long?,
        val isDefault: Boolean,
    )

    private data class HttpJsonResult(
        val status: Int,
        val body: JSONObject?,
        val message: String?,
    ) {
        val successful: Boolean get() = status in 200..299 && body != null
    }

    private data class HttpBytesResult(
        val status: Int,
        val bytes: ByteArray?,
        val contentType: String?,
        val message: String?,
    ) {
        val successful: Boolean get() = status in 200..299 && bytes != null && bytes.isNotEmpty()
    }

    private class PlaybackAuthException : Exception()

    private enum class SleepAction {
        PAUSE,
        EXIT,
    }

    private data class SeasonSection(
        val key: String,
        val season: Int?,
        val title: String,
        val resourceIds: Set<String>,
    )

    private enum class PlayerGesture {
        NONE,
        SEEK,
        BRIGHTNESS,
        VOLUME,
    }

    /**
     * MediaSession normally derives next/previous availability from ExoPlayer's
     * one-item timeline. CyberStream keeps the richer episode graph outside
     * that timeline because every resource has its own subtitles, ticket and
     * provider state. This adapter exposes series navigation to Android while
     * forwarding every other command and event unchanged.
     */
    private inner class CyberSessionPlayer(player: Player) : ForwardingPlayer(player) {
        private val listenerWrappers = IdentityHashMap<Player.Listener, Player.Listener>()

        override fun getAvailableCommands(): Player.Commands {
            val commands = super.getAvailableCommands().buildUpon()
            if (contentKind == "series") {
                commands
                    .add(Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM)
                    .add(Player.COMMAND_SEEK_TO_PREVIOUS)
                    .add(Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM)
                    .add(Player.COMMAND_SEEK_TO_NEXT)
            }
            return commands.build()
        }

        override fun isCommandAvailable(command: Int): Boolean =
            if (contentKind == "series" && command in setOf(
                    Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM,
                    Player.COMMAND_SEEK_TO_PREVIOUS,
                    Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM,
                    Player.COMMAND_SEEK_TO_NEXT,
                )) {
                true
            } else {
                super.isCommandAvailable(command)
            }

        /**
         * ForwardingPlayer forwards ExoPlayer's raw available-command callback
         * verbatim. Wrap listeners so that callback carries the same augmented
         * episode commands as getAvailableCommands(). A Java proxy is used
         * here because Player.Listener methods are Java default methods;
         * Kotlin interface delegation would silently inherit their no-op
         * defaults instead of forwarding MediaSession's metadata/state events.
         */
        override fun addListener(listener: Player.Listener) {
            val wrapper = Proxy.newProxyInstance(
                Player.Listener::class.java.classLoader,
                arrayOf(Player.Listener::class.java),
            ) { _, method, arguments ->
                if (method.name == "onAvailableCommandsChanged") {
                    listener.onAvailableCommandsChanged(getAvailableCommands())
                    null
                } else {
                    try {
                        method.invoke(listener, *(arguments ?: emptyArray()))
                    } catch (error: InvocationTargetException) {
                        throw error.targetException
                    }
                }
            } as Player.Listener
            val previous = listenerWrappers.put(listener, wrapper)
            if (previous != null) super.removeListener(previous)
            super.addListener(wrapper)
        }

        override fun removeListener(listener: Player.Listener) {
            val wrapper = listenerWrappers.remove(listener)
            if (wrapper != null) super.removeListener(wrapper) else super.removeListener(listener)
        }

        override fun seekToPreviousMediaItem() {
            if (!switchEpisodeBy(-1)) super.seekToPreviousMediaItem()
        }

        override fun seekToPrevious() {
            if (!switchEpisodeBy(-1)) super.seekToPrevious()
        }

        override fun seekToNextMediaItem() {
            if (!switchEpisodeBy(1)) super.seekToNextMediaItem()
        }

        override fun seekToNext() {
            if (!switchEpisodeBy(1)) super.seekToNext()
        }
    }

    private lateinit var player: ExoPlayer
    private lateinit var mediaSession: MediaSession
    private lateinit var playerHost: FrameLayout
    private var playerSurface: View? = null
    private lateinit var playerView: PlayerView
    private lateinit var gestureSurface: View
    private lateinit var externalSubtitleView: SubtitleView
    private lateinit var trackSelector: DefaultTrackSelector
    private lateinit var sourceButton: Button
    private lateinit var audioButton: Button
    private lateinit var subtitleButton: Button
    private lateinit var qualityButton: Button
    private lateinit var settingsButton: View
    private lateinit var orientationButton: View
    private lateinit var backButton: View
    private lateinit var playerTitle: TextView
    private lateinit var topActions: View
    private lateinit var sidePanelScrim: View
    private lateinit var sidePanel: View
    private lateinit var sidePanelTitle: TextView
    private lateinit var sidePanelItems: LinearLayout
    private lateinit var sidePanelClose: View
    private lateinit var seekGestureOverlay: TextView
    private lateinit var adjustmentGestureOverlay: LinearLayout
    private lateinit var adjustmentGestureIcon: ImageView
    private lateinit var adjustmentGestureLabel: TextView
    private lateinit var adjustmentGestureProgress: ProgressBar
    private lateinit var playerErrorOverlay: View
    private lateinit var playerErrorMessage: TextView
    private lateinit var audioManager: AudioManager
    private lateinit var session: JSONObject
    private lateinit var sessionId: String
    private lateinit var rawSessionJson: String
    private var previousEpisodeButton: View? = null
    private var nextEpisodeButton: View? = null
    private var portraitEpisodeGrid: GridLayout? = null
    private var portraitEpisodeSummary: TextView? = null
    private var portraitSeasonScroll: HorizontalScrollView? = null
    private var portraitSeasonTabs: LinearLayout? = null
    private var portraitEpisodeSection: View? = null
    private var portraitMovieSection: ScrollView? = null
    private var portraitMovieSourcesScroll: HorizontalScrollView? = null
    private var portraitMovieSources: LinearLayout? = null
    private var portraitMovieTechnical: LinearLayout? = null
    private var resources = JSONArray()
    private var seasonSections: List<SeasonSection> = emptyList()
    private var activeSeasonKey: String? = null
    private var currentResource: JSONObject? = null
    private var contentKind = "movie"
    private var currentQuality: CloudQuality? = null
    private var qualityFallbackInProgress = false
    private val qualityCache = mutableMapOf<String, List<CloudQuality>>()
    private val qualityRequests = mutableSetOf<String>()
    private val networkExecutor = Executors.newSingleThreadExecutor()
    private var didFinish = false
    private var hasEnteredPictureInPicture = false
    private var pipExitCheckPending = false
    private var reachedEnd = false
    private var authExpired = false
    private var lastError: String? = null
    private var audioSelectionOverridden = false
    private var subtitleSelectionOverridden = false
    private var subtitlesDisabled = false
    private var sidePanelOpen = false
    private var activePanelKind: String? = null
    private var isPortraitLayout = false
    private var currentOrientation = Configuration.ORIENTATION_UNDEFINED
    private var gestureDownX = 0f
    private var gestureDownY = 0f
    private var gestureStartPositionMs = 0L
    private var gestureSeekTargetMs = 0L
    private var gestureStartBrightness = 0.5f
    private var gestureStartVolume = 0
    private var gestureMaxVolume = 1
    private var gestureMode = PlayerGesture.NONE
    private var lastTapUpTimeMs = 0L
    private var lastTapX = 0f
    private var lastTapY = 0f
    private var pendingSingleTap: Runnable? = null
    private var resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
    private var subtitleScale = 1f
    private var subtitleBottomPadding = 0.10f
    private var subtitleColor = Color.WHITE
    private var overrideAssStyles = false
    private var controllerVisible = false
    private var lastCueGroup = CueGroup.EMPTY_TIME_ZERO
    private var sleepAction = SleepAction.PAUSE
    private var sleepDeadlineMs = 0L
    private var sleepAtEpisodeEnd = false
    private var prepareCount = 0
    private var initialPlaybackStarted = false
    private var cellularAllowedForSession = false
    private var cellularWarningView: View? = null
    private var cellularBackdropRequestId = 0
    private var cellularArtworkUrl: String? = null
    private var onlineSubtitleRequestId = 0
    private var onlineSubtitleSearching = false
    private var onlineSubtitleBinding = false
    private var onlineSubtitlePreviewing = false
    private var previewSubtitleFile: File? = null

    private var audioDecoderName: String? = null
    private var videoDecoderName: String? = null
    private var audioInputFormat: Format? = null
    private var videoInputFormat: Format? = null
    private var audioOutputEncoding: Int? = null
    private var audioOutputSampleRate: Int? = null
    private var audioOutputChannelCount: Int? = null
    private var audioOutputOffload = false

    private val handler = Handler(Looper.getMainLooper())
    private val hideGestureOverlays = Runnable {
        if (::seekGestureOverlay.isInitialized) seekGestureOverlay.visibility = View.GONE
        if (::adjustmentGestureOverlay.isInitialized) adjustmentGestureOverlay.visibility = View.GONE
    }

    private val sleepTimer = Runnable {
        sleepDeadlineMs = 0L
        sleepAtEpisodeEnd = false
        executeSleepAction()
    }

    private val completeDismissedPictureInPicture = Runnable {
        if (!pipExitCheckPending || didFinish || isInPictureInPictureMode) {
            return@Runnable
        }

        // Expanding PiP returns the Activity to STARTED/RESUMED. A system
        // close, by contrast, leaves it STOPPED (Lifecycle.CREATED) without
        // setting isFinishing on Android 16. Waiting for the next main-loop
        // turn lets either lifecycle ordering settle before deciding.
        if (isFinishing || lifecycle.currentState == Lifecycle.State.CREATED) {
            closePlayer()
        } else if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
            pipExitCheckPending = false
            hasEnteredPictureInPicture = false
        }
    }

    private val progressReporter = object : Runnable {
        override fun run() {
            emitProgress(
                when {
                    reachedEnd -> "ended"
                    player.isPlaying -> "playing"
                    else -> "paused"
                },
            )
            handler.postDelayed(this, PROGRESS_INTERVAL_MS)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) {
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        }
        currentOrientation = applicationContext.resources.configuration.orientation
        WindowCompat.setDecorFitsSystemWindows(window, false)
        hideSystemBars()

        val rawSession = takeStoredSession(savedInstanceState?.getString(STATE_STORED_SESSION_ID))
            ?: takeStoredSession(intent.getStringExtra(EXTRA_SESSION_ID))
            ?: intent.getStringExtra(EXTRA_SESSION_JSON)
        if (rawSession.isNullOrBlank()) {
            finish()
            return
        }

        try {
            rawSessionJson = rawSession
            session = JSONObject(rawSession)
            sessionId = session.getString("sessionId")
            resources = session.getJSONArray("resources")
            contentKind = session.optString("contentKind").takeIf { it == "movie" || it == "series" }
                ?: inferLegacyContentKind()
            seasonSections = buildSeasonSections()
        } catch (error: Exception) {
            Toast.makeText(this, "播放会话无效", Toast.LENGTH_LONG).show()
            finish()
            return
        }

        val preferences = getSharedPreferences(PLAYER_PREFERENCES, Context.MODE_PRIVATE)
        resizeMode = preferences.getInt(
            "resize_mode",
            AspectRatioFrameLayout.RESIZE_MODE_FIT,
        ).takeIf {
            it == AspectRatioFrameLayout.RESIZE_MODE_FIT ||
                it == AspectRatioFrameLayout.RESIZE_MODE_ZOOM
        } ?: AspectRatioFrameLayout.RESIZE_MODE_FIT
        subtitleScale = preferences.getFloat("subtitle_scale", 1f).coerceIn(0.75f, 1.5f)
        subtitleBottomPadding = preferences.getFloat("subtitle_position", 0.10f).coerceIn(0.05f, 0.25f)
        subtitleColor = preferences.getInt("subtitle_color", Color.WHITE)
        overrideAssStyles = preferences.getBoolean("subtitle_override_ass", false)
        cellularAllowedForSession = savedInstanceState?.getBoolean(
            STATE_CELLULAR_ALLOWED_FOR_SESSION,
            false,
        ) ?: false

        setContentView(R.layout.activity_player_host)
        playerHost = findViewById(R.id.player_host)

        trackSelector = DefaultTrackSelector(this)
        val renderersFactory = DefaultRenderersFactory(this)
            // Platform MediaCodec remains first. FFmpeg is used only when the
            // device cannot decode an audio format itself.
            .setExtensionRendererMode(DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON)
            // Some vendors expose more than one decoder for the same codec.
            // Let Media3 try the next decoder instead of failing on the first
            // broken implementation.
            .setEnableDecoderFallback(true)
            // Vendor asynchronous MediaCodec implementations are a frequent
            // source of flush/release crashes during errors and rapid source
            // changes. The synchronous adapter is slightly less aggressive
            // but substantially more predictable across phones/tablets.
            .forceDisableMediaCodecAsynchronousQueueing()
            // Preserve high-resolution decoder output as float PCM when the
            // device AudioTrack supports it. There is no loudness processor.
            .setEnableAudioFloatOutput(true)
        val audioAttributes = AudioAttributes.Builder()
            .setUsage(C.USAGE_MEDIA)
            .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
            .build()
        player = ExoPlayer.Builder(this, renderersFactory)
            .setTrackSelector(trackSelector)
            .setAudioAttributes(audioAttributes, true)
            .setHandleAudioBecomingNoisy(true)
            .build()
        // Bind the Activity-scoped player to Android's system media layer.
        // Headsets, Bluetooth controls and system transport controls can now
        // drive the same ExoPlayer instance without a second playback path.
        // Media3 reserves the empty/default session id process-wide. A user
        // can open/close the player repeatedly (and instrumentation does so
        // back-to-back), so always give this Activity its own non-empty id.
        val mediaSessionId = "${sessionId}-${System.nanoTime()}"
        val sessionPlayer = CyberSessionPlayer(player)
        mediaSession = MediaSession.Builder(this, sessionPlayer)
            .setId(mediaSessionId)
            .build()
        audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        volumeControlStream = AudioManager.STREAM_MUSIC
        installPlayerLayout(currentOrientation)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (sidePanelOpen) closeSidePanel() else closePlayer()
            }
        })
        player.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                emitProgress(
                    when {
                        reachedEnd -> "ended"
                        isPlaying -> "playing"
                        else -> "paused"
                    },
                )
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                if (playbackState == Player.STATE_ENDED) {
                    reachedEnd = true
                    emitProgress("ended")
                    if (sleepAtEpisodeEnd) {
                        sleepAtEpisodeEnd = false
                        executeSleepAction()
                    }
                } else if (playbackState == Player.STATE_READY) {
                    qualityFallbackInProgress = false
                }
            }

            override fun onTracksChanged(tracks: Tracks) {
                updateAudioButtonLabel(tracks)
                updateSubtitleButtonLabel(tracks)
                rebuildPortraitMoviePanel()
            }

            override fun onCues(cueGroup: CueGroup) {
                lastCueGroup = cueGroup
                if (::externalSubtitleView.isInitialized) {
                    externalSubtitleView.setCues(cueGroup.cues)
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                // Never return exception messages because they can contain a
                // ticketed media URL. Decoder names and stable error codes are
                // safe and useful for local compatibility diagnostics.
                lastError = buildString {
                    append(error.errorCodeName)
                    audioDecoderName?.let { append("; audioDecoder=").append(it) }
                    videoDecoderName?.let { append("; videoDecoder=").append(it) }
                }
                if (findHttpStatusCode(error) == 401) {
                    authExpired = true
                    closePlayer()
                    return
                }
                val failedQuality = currentQuality
                val resource = currentResource
                if (failedQuality != null && resource != null && !qualityFallbackInProgress) {
                    val positionMs = player.currentPosition.coerceAtLeast(0L)
                    val shouldPlay = player.playWhenReady
                    currentQuality = null
                    qualityFallbackInProgress = true
                    Toast.makeText(
                        this@PlayerActivity,
                        "${failedQuality.label} 播放失败，已回到原文件",
                        Toast.LENGTH_LONG,
                    ).show()
                    loadResource(
                        resource,
                        positionMs,
                        shouldPlay = shouldPlay,
                        selectedQuality = null,
                        resetTrackSelection = false,
                    )
                    return
                }
                Toast.makeText(
                    this@PlayerActivity,
                    "原始文件本机解码失败：${error.errorCodeName}",
                    Toast.LENGTH_LONG,
                ).show()
                showPlayerError(error)
            }
        })
        player.addAnalyticsListener(object : AnalyticsListener {
            override fun onAudioDecoderInitialized(
                eventTime: AnalyticsListener.EventTime,
                decoderName: String,
                initializedTimestampMs: Long,
                initializationDurationMs: Long,
            ) {
                audioDecoderName = decoderName
                Log.i(LOG_TAG, "Audio decoder initialized: $decoderName")
            }

            override fun onVideoDecoderInitialized(
                eventTime: AnalyticsListener.EventTime,
                decoderName: String,
                initializedTimestampMs: Long,
                initializationDurationMs: Long,
            ) {
                videoDecoderName = decoderName
                Log.i(LOG_TAG, "Video decoder initialized: $decoderName")
            }

            override fun onAudioInputFormatChanged(
                eventTime: AnalyticsListener.EventTime,
                format: Format,
                decoderReuseEvaluation: DecoderReuseEvaluation?,
            ) {
                audioInputFormat = format
                updateAudioButtonLabel(player.currentTracks)
                rebuildPortraitMoviePanel()
            }

            override fun onVideoInputFormatChanged(
                eventTime: AnalyticsListener.EventTime,
                format: Format,
                decoderReuseEvaluation: DecoderReuseEvaluation?,
            ) {
                videoInputFormat = format
                rebuildPortraitMoviePanel()
            }

            override fun onAudioTrackInitialized(
                eventTime: AnalyticsListener.EventTime,
                audioTrackConfig: AudioSink.AudioTrackConfig,
            ) {
                audioOutputEncoding = audioTrackConfig.encoding
                audioOutputSampleRate = audioTrackConfig.sampleRate
                audioOutputChannelCount = Integer.bitCount(audioTrackConfig.channelConfig).takeIf { it > 0 }
                audioOutputOffload = audioTrackConfig.offload
                Log.i(
                    LOG_TAG,
                    "AudioTrack initialized: encoding=${audioTrackConfig.encoding}, " +
                        "sampleRate=${audioTrackConfig.sampleRate}, " +
                        "channels=${audioOutputChannelCount ?: 0}, offload=${audioTrackConfig.offload}",
                )
                rebuildPortraitMoviePanel()
            }
        })

        val initialId = savedInstanceState?.getString(STATE_RESOURCE_ID)
            ?: session.optString("initialResourceId")
        val initial = findResource(initialId) ?: findResourceAt(0)
        if (initial == null) {
            Toast.makeText(this, "没有可播放资源", Toast.LENGTH_LONG).show()
            closePlayer()
            return
        }
        val initialPositionMs = if (savedInstanceState?.containsKey(STATE_POSITION_MS) == true) {
            savedInstanceState.getLong(STATE_POSITION_MS, 0L)
        } else {
            session.optLong("startTimeMs", 0L)
        }
        maybeStartInitialPlayback(initial, initialPositionMs)
    }

    private fun inferLegacyContentKind(): String {
        val seasons = session.optJSONObject("movie")?.optJSONArray("seasons")
        if (seasons != null && seasons.length() > 0) return "series"
        for (index in 0 until resources.length()) {
            val resource = resources.optJSONObject(index) ?: continue
            if (resource.has("episode") && resource.optString("episode").isNotBlank()) return "series"
        }
        return "movie"
    }

    private fun maybeStartInitialPlayback(resource: JSONObject, positionMs: Long) {
        if (shouldShowCellularWarning()) {
            showCellularWarning(resource, positionMs)
        } else {
            startInitialPlayback(resource, positionMs)
        }
    }

    private fun shouldShowCellularWarning(): Boolean {
        if (cellularAllowedForSession) return false
        if (
            getSharedPreferences(PLAYER_PREFERENCES, Context.MODE_PRIVATE)
                .getBoolean(PREF_ALLOW_CELLULAR_PLAYBACK, false)
        ) {
            return false
        }
        return isActiveNetworkCellular()
    }

    private fun isActiveNetworkCellular(): Boolean {
        // PlayerActivity is not exported, so this internal override can only
        // be supplied by CyberStream itself or its instrumentation process.
        if (intent.hasExtra(EXTRA_CELLULAR_NETWORK_FOR_TESTING)) {
            return intent.getBooleanExtra(EXTRA_CELLULAR_NETWORK_FOR_TESTING, false)
        }
        val connectivity = getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return false
        val activeNetwork = connectivity.activeNetwork ?: return false
        val capabilities = connectivity.getNetworkCapabilities(activeNetwork) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
    }

    private fun showCellularWarning(resource: JSONObject, positionMs: Long) {
        if (cellularWarningView != null || didFinish) return
        val warning = layoutInflater.inflate(R.layout.player_cellular_warning, playerHost, false)
        val movie = session.optJSONObject("movie")
        val title = movie?.optString("title")?.trim().takeUnless { it.isNullOrBlank() } ?: "CyberStream"
        val titleView = warning.findViewById<TextView>(R.id.cellular_warning_title)
        val messageView = warning.findViewById<TextView>(R.id.cellular_warning_message)
        val posterView = warning.findViewById<ImageView>(R.id.cellular_warning_poster)
        titleView.text = title
        messageView.text = cellularWarningMessage(resource)
        posterView.contentDescription = "$title 主海报"

        warning.findViewById<View>(R.id.cellular_warning_exit).setOnClickListener { closePlayer() }
        warning.findViewById<View>(R.id.cellular_warning_allow_once).setOnClickListener {
            cellularAllowedForSession = true
            startInitialPlayback(resource, positionMs)
        }
        warning.findViewById<View>(R.id.cellular_warning_allow_always).setOnClickListener {
            cellularAllowedForSession = true
            getSharedPreferences(PLAYER_PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putBoolean(PREF_ALLOW_CELLULAR_PLAYBACK, true)
                .apply()
            startInitialPlayback(resource, positionMs)
        }

        cellularWarningView = warning
        playerHost.addView(
            warning,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        warning.bringToFront()
        cellularArtworkUrl = movie?.optString("posterUrl")?.trim().takeUnless { it.isNullOrBlank() }
            ?: movie?.optString("backdropUrl")?.trim().takeUnless { it.isNullOrBlank() }
        loadCellularWarningArtwork(posterView, cellularArtworkUrl)
    }

    private fun cellularWarningMessage(resource: JSONObject): String {
        val sizeBytes = resource.optJSONObject("technical")?.optLong("sizeBytes", 0L) ?: 0L
        val sizeLabel = formatTrafficSize(sizeBytes)
        return if (sizeLabel != null) {
            "当前为移动流量，继续播放最多消耗 $sizeLabel，可能产生额外费用"
        } else {
            "当前为移动流量，继续播放可能消耗大量流量，并产生额外费用"
        }
    }

    private fun formatTrafficSize(sizeBytes: Long): String? {
        if (sizeBytes <= 0L) return null
        val gibibyte = 1024.0 * 1024.0 * 1024.0
        if (sizeBytes >= 1024L * 1024L * 1024L) {
            return String.format(Locale.US, "%.2f GB", sizeBytes / gibibyte)
        }
        val mebibyte = 1024.0 * 1024.0
        return String.format(Locale.US, "%.0f MB", sizeBytes / mebibyte)
    }

    private fun loadCellularWarningArtwork(imageView: ImageView, artworkUrl: String?) {
        if (artworkUrl.isNullOrBlank()) return
        val uri = runCatching { Uri.parse(artworkUrl) }.getOrNull() ?: return
        if (uri.scheme != "https" && uri.scheme != "http") return
        val requestId = ++cellularBackdropRequestId
        networkExecutor.execute {
            var connection: HttpURLConnection? = null
            val bitmap = try {
                connection = URL(artworkUrl).openConnection() as HttpURLConnection
                connection.connectTimeout = 8_000
                connection.readTimeout = 8_000
                connection.instanceFollowRedirects = true
                connection.useCaches = true
                connection.setRequestProperty("Accept", "image/jpeg,image/png,image/webp,image/*;q=0.8")
                connection.setRequestProperty("User-Agent", "CyberStream-Android/1.21.1")
                if (connection.responseCode !in 200..299) {
                    null
                } else {
                    connection.inputStream.use { input ->
                        BitmapFactory.decodeStream(
                            input,
                            null,
                            BitmapFactory.Options().apply { inSampleSize = 2 },
                        )
                    }
                }
            } catch (_: Exception) {
                null
            } finally {
                connection?.disconnect()
            }
            if (bitmap == null) return@execute
            handler.post {
                if (
                    requestId != cellularBackdropRequestId ||
                    cellularWarningView == null ||
                    imageView.parent == null ||
                    isFinishing
                ) {
                    bitmap.recycle()
                    return@post
                }
                imageView.alpha = 0f
                imageView.setImageBitmap(bitmap)
                imageView.animate().alpha(1f).setDuration(220L).start()
            }
        }
    }

    private fun startInitialPlayback(resource: JSONObject, positionMs: Long) {
        if (initialPlaybackStarted || didFinish) return
        initialPlaybackStarted = true
        cellularBackdropRequestId += 1
        cellularWarningView?.let(playerHost::removeView)
        cellularWarningView = null
        loadResource(resource, positionMs, shouldPlay = true)
        handler.removeCallbacks(progressReporter)
        handler.post(progressReporter)
    }

    /**
     * Re-inflates only the orientation-specific chrome. The FrameLayout host
     * and ExoPlayer instance stay alive, so rotation does not call prepare(),
     * replace decoders, lose buffers, or reset track selections.
     */
    private fun installPlayerLayout(orientation: Int) {
        pendingSingleTap?.let(handler::removeCallbacks)
        pendingSingleTap = null
        val oldSurface = playerSurface
        val oldPlayerView = if (::playerView.isInitialized) playerView else null
        dismissSidePanelImmediatelyIfBound()

        val surface = layoutInflater.inflate(R.layout.activity_player, playerHost, false)
        playerHost.addView(
            surface,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        playerSurface = surface
        playerView = surface.findViewById(R.id.media_player_view)
        gestureSurface = surface.findViewById(R.id.player_gesture_surface)
        externalSubtitleView = surface.findViewById(R.id.external_subtitle_view)
        sourceButton = surface.findViewById(R.id.source_button)
        audioButton = surface.findViewById(R.id.audio_button)
        subtitleButton = surface.findViewById(R.id.subtitle_button)
        qualityButton = surface.findViewById(R.id.quality_button)
        settingsButton = surface.findViewById(R.id.settings_button)
        orientationButton = surface.findViewById(R.id.orientation_button)
        backButton = surface.findViewById(R.id.back_button)
        playerTitle = surface.findViewById(R.id.player_title)
        topActions = surface.findViewById(R.id.top_actions)
        sidePanelScrim = surface.findViewById(R.id.side_panel_scrim)
        sidePanel = surface.findViewById(R.id.side_panel)
        sidePanelTitle = surface.findViewById(R.id.side_panel_title)
        sidePanelItems = surface.findViewById(R.id.side_panel_items)
        sidePanelClose = surface.findViewById(R.id.side_panel_close)
        seekGestureOverlay = surface.findViewById(R.id.seek_gesture_overlay)
        adjustmentGestureOverlay = surface.findViewById(R.id.adjustment_gesture_overlay)
        adjustmentGestureIcon = surface.findViewById(R.id.adjustment_gesture_icon)
        adjustmentGestureLabel = surface.findViewById(R.id.adjustment_gesture_label)
        adjustmentGestureProgress = surface.findViewById(R.id.adjustment_gesture_progress)
        playerErrorOverlay = surface.findViewById(R.id.player_error_overlay)
        playerErrorMessage = surface.findViewById(R.id.player_error_message)
        previousEpisodeButton = surface.findViewById(R.id.previous_episode_button)
        nextEpisodeButton = surface.findViewById(R.id.next_episode_button)
        portraitEpisodeGrid = surface.findViewById(R.id.portrait_episode_grid)
        portraitEpisodeSummary = surface.findViewById(R.id.portrait_episode_summary)
        portraitSeasonScroll = surface.findViewById(R.id.portrait_season_scroll)
        portraitSeasonTabs = surface.findViewById(R.id.portrait_season_tabs)
        portraitEpisodeSection = surface.findViewById(R.id.portrait_episode_section)
        portraitMovieSection = surface.findViewById(R.id.portrait_movie_section)
        portraitMovieSourcesScroll = surface.findViewById(R.id.portrait_movie_sources_scroll)
        portraitMovieSources = surface.findViewById(R.id.portrait_movie_sources)
        portraitMovieTechnical = surface.findViewById(R.id.portrait_movie_technical)
        isPortraitLayout = orientation == Configuration.ORIENTATION_PORTRAIT && portraitEpisodeGrid != null
        currentOrientation = orientation
        configurePortraitVideoHeight()

        playerView.findViewById<SubtitleView>(androidx.media3.ui.R.id.exo_subtitles)?.visibility = View.GONE
        playerView.resizeMode = resizeMode
        if (oldPlayerView == null) {
            playerView.player = player
        } else {
            PlayerView.switchTargetView(player, oldPlayerView, playerView)
        }
        oldSurface?.let(playerHost::removeView)

        applySubtitleStyle()
        externalSubtitleView.setCues(lastCueGroup.cues)
        configurePlayerGestures()
        playerView.setControllerVisibilityListener(
            PlayerView.ControllerVisibilityListener { visibility ->
                syncTopActionsVisibility(visibility)
            },
        )

        backButton.setOnClickListener { closePlayer() }
        sourceButton.setOnClickListener { showSourcePanel() }
        audioButton.setOnClickListener { showAudioPanel() }
        subtitleButton.setOnClickListener { showSubtitlePanel() }
        qualityButton.setOnClickListener { showQualityPanel() }
        settingsButton.setOnClickListener { showSettingsPanel() }
        orientationButton.setOnClickListener { toggleOrientation() }
        previousEpisodeButton?.setOnClickListener { switchEpisodeBy(-1) }
        nextEpisodeButton?.setOnClickListener { switchEpisodeBy(1) }
        sidePanelScrim.setOnClickListener { closeSidePanel() }
        sidePanelClose.setOnClickListener { closeSidePanel() }
        surface.findViewById<View>(R.id.player_error_retry).setOnClickListener {
            val resource = currentResource ?: return@setOnClickListener
            val position = player.currentPosition.coerceAtLeast(0L)
            loadResource(
                resource = resource,
                positionMs = position,
                shouldPlay = true,
                selectedQuality = currentQuality,
                resetTrackSelection = false,
            )
        }
        surface.findViewById<View>(R.id.player_error_exit).setOnClickListener { closePlayer() }

        refreshPlayerChrome()
        syncTopActionsVisibility()
        player.playerError?.let(::showPlayerError)
        cellularWarningView?.bringToFront()
    }

    private fun showPlayerError(error: PlaybackException) {
        if (!::playerErrorOverlay.isInitialized || didFinish) return
        player.playWhenReady = false
        playerErrorMessage.text = when {
            error.errorCodeName.contains("DECODING", ignoreCase = true) ->
                "当前设备无法稳定解码这个视频规格。可以重试一次；如果仍失败，请退出并选择兼容的片源。"
            error.errorCodeName.contains("NETWORK", ignoreCase = true) ||
                error.errorCodeName.contains("TIMEOUT", ignoreCase = true) ->
                "媒体连接失败。请检查网络后重试，播放进度会保留。"
            else ->
                "播放器遇到错误（${error.errorCodeName}）。可以重试，或退出后选择其他片源。"
        }
        playerErrorOverlay.visibility = View.VISIBLE
        playerErrorOverlay.bringToFront()
    }

    private fun dismissSidePanelImmediatelyIfBound() {
        if (::sidePanel.isInitialized && ::sidePanelScrim.isInitialized) {
            dismissSidePanelImmediately()
        }
    }

    private fun refreshPlayerChrome() {
        val resource = currentResource
        val isSeries = contentKind == "series"
        sourceButton.visibility = if (!isPortraitLayout && isSeries) View.VISIBLE else View.GONE
        previousEpisodeButton?.visibility = if (isSeries) View.VISIBLE else View.GONE
        nextEpisodeButton?.visibility = if (isSeries) View.VISIBLE else View.GONE
        val hasCloudQuality = resource?.optJSONObject("cloudTranscode")
            ?.optBoolean("supported", false) == true
        qualityButton.visibility = if (hasCloudQuality) View.VISIBLE else View.GONE
        qualityButton.text = currentQuality?.label ?: "画质"
        orientationButton.contentDescription = if (isPortraitLayout) "进入全屏" else "退出全屏"
        portraitEpisodeSection?.visibility = if (isSeries) View.VISIBLE else View.GONE
        portraitMovieSection?.visibility = if (isSeries) View.GONE else View.VISIBLE

        if (resource == null) {
            playerTitle.text = session.optJSONObject("movie")?.optString("title", "CyberStream")
            return
        }
        playerTitle.text = playerDisplayTitle(resource)
        val resourceIndex = currentResourceIndex()
        updateEpisodeNavigation(resourceIndex)
        if (::player.isInitialized) {
            updateAudioButtonLabel(player.currentTracks)
            updateSubtitleButtonLabel(player.currentTracks)
        }
        rebuildPortraitMoviePanel()
    }

    private fun findHttpStatusCode(error: Throwable?): Int? {
        var current = error
        val visited = mutableSetOf<Throwable>()
        while (current != null && visited.add(current)) {
            if (current is HttpDataSource.InvalidResponseCodeException) return current.responseCode
            current = current.cause
        }
        return null
    }

    private fun hideSystemBars() {
        WindowInsetsControllerCompat(window, window.decorView).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
    }

    private fun configurePortraitVideoHeight() {
        val container = findViewById<View>(R.id.portrait_video_container) ?: return
        val screenWidth = applicationContext.resources.displayMetrics.widthPixels
        container.layoutParams = container.layoutParams.apply {
            height = (screenWidth * 9f / 16f).toInt()
        }
    }

    private fun toggleOrientation() {
        dismissSidePanelImmediately()
        requestedOrientation = if (isPortraitLayout) {
            ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        } else {
            ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        hideSystemBars()
        if (
            newConfig.orientation != Configuration.ORIENTATION_UNDEFINED &&
            newConfig.orientation != currentOrientation
        ) {
            installPlayerLayout(newConfig.orientation)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        if (::rawSessionJson.isInitialized && ::sessionId.isInitialized) {
            storeSession(sessionId, rawSessionJson)
            outState.putString(STATE_STORED_SESSION_ID, sessionId)
        }
        if (::player.isInitialized) {
            outState.putString(STATE_RESOURCE_ID, currentResource?.optString("id"))
            outState.putLong(STATE_POSITION_MS, player.currentPosition.coerceAtLeast(0L))
        }
        outState.putBoolean(STATE_CELLULAR_ALLOWED_FOR_SESSION, cellularAllowedForSession)
        super.onSaveInstanceState(outState)
    }

    private fun configurePlayerGestures() {
        val touchSlop = ViewConfiguration.get(this).scaledTouchSlop.toFloat()
        gestureSurface.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    handler.removeCallbacks(hideGestureOverlays)
                    hideGestureOverlays.run()
                    gestureDownX = event.x
                    gestureDownY = event.y
                    gestureStartPositionMs = player.currentPosition.coerceAtLeast(0L)
                    gestureSeekTargetMs = gestureStartPositionMs
                    gestureStartBrightness = currentWindowBrightness()
                    gestureMaxVolume = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1)
                    gestureStartVolume = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
                    gestureMode = PlayerGesture.NONE
                    true
                }

                MotionEvent.ACTION_MOVE -> {
                    val deltaX = event.x - gestureDownX
                    val deltaY = event.y - gestureDownY
                    if (gestureMode == PlayerGesture.NONE) {
                        val horizontalDistance = kotlin.math.abs(deltaX)
                        val verticalDistance = kotlin.math.abs(deltaY)
                        gestureMode = when {
                            horizontalDistance > touchSlop && horizontalDistance > verticalDistance * 1.15f ->
                                PlayerGesture.SEEK
                            verticalDistance > touchSlop && verticalDistance > horizontalDistance * 1.15f ->
                                if (gestureDownX < gestureSurface.width / 2f) {
                                    PlayerGesture.BRIGHTNESS
                                } else {
                                    PlayerGesture.VOLUME
                                }
                            else -> PlayerGesture.NONE
                        }
                        if (gestureMode != PlayerGesture.NONE) playerView.hideController()
                    }
                    when (gestureMode) {
                        PlayerGesture.SEEK -> updateSeekGesture(deltaX)
                        PlayerGesture.BRIGHTNESS -> updateBrightnessGesture(deltaY)
                        PlayerGesture.VOLUME -> updateVolumeGesture(deltaY)
                        PlayerGesture.NONE -> Unit
                    }
                    true
                }

                MotionEvent.ACTION_UP -> {
                    if (gestureMode == PlayerGesture.SEEK) {
                        player.seekTo(gestureSeekTargetMs)
                    }
                    if (gestureMode != PlayerGesture.NONE) {
                        handler.removeCallbacks(hideGestureOverlays)
                        handler.postDelayed(hideGestureOverlays, 700L)
                    } else if (
                        abs(event.x - gestureDownX) <= touchSlop &&
                        abs(event.y - gestureDownY) <= touchSlop
                    ) {
                        handlePlayerTap(event)
                    }
                    gestureMode = PlayerGesture.NONE
                    true
                }

                MotionEvent.ACTION_CANCEL -> {
                    gestureMode = PlayerGesture.NONE
                    hideGestureOverlays.run()
                    true
                }

                else -> true
            }
        }
    }

    private fun handlePlayerTap(event: MotionEvent) {
        val doubleTapTimeout = ViewConfiguration.getDoubleTapTimeout().toLong()
        val isDoubleTap = lastTapUpTimeMs > 0L &&
            event.eventTime - lastTapUpTimeMs <= doubleTapTimeout &&
            abs(event.x - lastTapX) <= dp(72) &&
            abs(event.y - lastTapY) <= dp(72)
        if (isDoubleTap) {
            pendingSingleTap?.let(handler::removeCallbacks)
            pendingSingleTap = null
            lastTapUpTimeMs = 0L
            toggleResizeMode()
            return
        }

        lastTapUpTimeMs = event.eventTime
        lastTapX = event.x
        lastTapY = event.y
        val tappedView = playerView
        val tappedSurface = gestureSurface
        val tapX = event.x
        val tapY = event.y
        val action = Runnable {
            if (
                ::playerView.isInitialized &&
                ::gestureSurface.isInitialized &&
                playerView === tappedView &&
                gestureSurface === tappedSurface
            ) {
                val hitPortraitPlay = isPortraitLayout && controllerVisible &&
                    abs(tapX - tappedSurface.width / 2f) <= dp(48) &&
                    abs(tapY - tappedSurface.height / 2f) <= dp(48)
                if (hitPortraitPlay) {
                    if (player.isPlaying) player.pause() else player.play()
                } else {
                    tappedView.performClick()
                }
            }
            pendingSingleTap = null
        }
        pendingSingleTap = action
        handler.postDelayed(action, doubleTapTimeout)
    }

    private fun toggleResizeMode() {
        resizeMode = if (resizeMode == AspectRatioFrameLayout.RESIZE_MODE_FIT) {
            AspectRatioFrameLayout.RESIZE_MODE_ZOOM
        } else {
            AspectRatioFrameLayout.RESIZE_MODE_FIT
        }
        playerView.resizeMode = resizeMode
        getSharedPreferences("cyber_player_settings", Context.MODE_PRIVATE)
            .edit()
            .putInt("resize_mode", resizeMode)
            .apply()
        showTransientPlayerMessage(displayModeLabel())
    }

    private fun displayModeLabel(): String =
        if (resizeMode == AspectRatioFrameLayout.RESIZE_MODE_ZOOM) "宽度优先填充" else "完整画面"

    private fun showTransientPlayerMessage(message: String) {
        seekGestureOverlay.text = message
        seekGestureOverlay.visibility = View.VISIBLE
        handler.removeCallbacks(hideGestureOverlays)
        handler.postDelayed(hideGestureOverlays, 850L)
    }

    private fun applySubtitleStyle() {
        if (!::externalSubtitleView.isInitialized) return
        externalSubtitleView.setApplyEmbeddedStyles(!overrideAssStyles)
        externalSubtitleView.setApplyEmbeddedFontSizes(!overrideAssStyles)
        externalSubtitleView.setFractionalTextSize((0.0533f * subtitleScale).coerceIn(0.038f, 0.08f))
        val controllerSafeInset = if (controllerVisible) {
            if (isPortraitLayout) 0.09f else 0.055f
        } else {
            0f
        }
        externalSubtitleView.setBottomPaddingFraction(
            (subtitleBottomPadding + controllerSafeInset).coerceAtMost(0.32f),
        )
        externalSubtitleView.setStyle(
            CaptionStyleCompat(
                subtitleColor,
                Color.TRANSPARENT,
                Color.TRANSPARENT,
                CaptionStyleCompat.EDGE_TYPE_DROP_SHADOW,
                Color.BLACK,
                null,
            ),
        )
    }

    private fun updateSeekGesture(deltaX: Float) {
        val durationMs = player.duration.takeIf { it > 0 } ?: return
        val width = playerView.width.takeIf { it > 0 } ?: return
        val gestureRangeMs = (durationMs / 4)
            .coerceIn(MIN_GESTURE_SEEK_RANGE_MS, MAX_GESTURE_SEEK_RANGE_MS)
        val deltaMs = (deltaX / width * gestureRangeMs).toLong()
        gestureSeekTargetMs = (gestureStartPositionMs + deltaMs).coerceIn(0L, durationMs)
        val appliedDeltaSeconds = (gestureSeekTargetMs - gestureStartPositionMs) / 1000L
        adjustmentGestureOverlay.visibility = View.GONE
        seekGestureOverlay.text = buildString {
            if (appliedDeltaSeconds == 0L) {
                append(if (deltaX >= 0f) "已到结尾" else "已到开头")
            } else {
                append(if (appliedDeltaSeconds > 0) "快进" else "快退")
                append(' ')
                append(kotlin.math.abs(appliedDeltaSeconds))
                append(" 秒")
            }
            appendLine()
            append(formatPlaybackTime(gestureSeekTargetMs))
            append(" / ")
            append(formatPlaybackTime(durationMs))
        }
        seekGestureOverlay.visibility = View.VISIBLE
    }

    private fun updateBrightnessGesture(deltaY: Float) {
        val height = playerView.height.takeIf { it > 0 } ?: return
        val delta = -deltaY / height * 1.25f
        val brightness = (gestureStartBrightness + delta).coerceIn(0.01f, 1f)
        window.attributes = window.attributes.apply {
            screenBrightness = brightness
        }
        showAdjustmentGesture(
            PlayerGesture.BRIGHTNESS,
            (brightness * 100f).roundToInt(),
        )
    }

    private fun currentWindowBrightness(): Float {
        val windowBrightness = window.attributes.screenBrightness
        if (windowBrightness in 0f..1f) return windowBrightness
        val systemBrightness = Settings.System.getInt(
            contentResolver,
            Settings.System.SCREEN_BRIGHTNESS,
            128,
        )
        return (systemBrightness / 255f).coerceIn(0.01f, 1f)
    }

    private fun updateVolumeGesture(deltaY: Float) {
        val height = playerView.height.takeIf { it > 0 } ?: return
        val deltaSteps = (-deltaY / height * gestureMaxVolume * 1.25f).roundToInt()
        val targetVolume = (gestureStartVolume + deltaSteps).coerceIn(0, gestureMaxVolume)
        if (!audioManager.isVolumeFixed) {
            audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, targetVolume, 0)
        }
        showAdjustmentGesture(
            PlayerGesture.VOLUME,
            (targetVolume * 100f / gestureMaxVolume).roundToInt(),
        )
    }

    private fun showAdjustmentGesture(mode: PlayerGesture, percent: Int) {
        seekGestureOverlay.visibility = View.GONE
        adjustmentGestureIcon.setImageResource(
            if (mode == PlayerGesture.BRIGHTNESS) {
                R.drawable.ic_player_brightness
            } else {
                R.drawable.ic_player_volume
            },
        )
        val label = if (mode == PlayerGesture.BRIGHTNESS) "亮度" else "音量"
        adjustmentGestureIcon.contentDescription = label
        adjustmentGestureLabel.text = "$label ${percent.coerceIn(0, 100)}%"
        adjustmentGestureProgress.progress = percent.coerceIn(0, 100)
        (adjustmentGestureOverlay.layoutParams as? FrameLayout.LayoutParams)?.let { params ->
            val sideMargin = dp(if (isPortraitLayout) 12 else 28)
            params.gravity = Gravity.CENTER_VERTICAL or if (mode == PlayerGesture.BRIGHTNESS) {
                Gravity.START
            } else {
                Gravity.END
            }
            params.marginStart = if (mode == PlayerGesture.BRIGHTNESS) sideMargin else 0
            params.marginEnd = if (mode == PlayerGesture.VOLUME) sideMargin else 0
            adjustmentGestureOverlay.layoutParams = params
        }
        adjustmentGestureOverlay.visibility = View.VISIBLE
    }

    private fun formatPlaybackTime(timeMs: Long): String {
        val totalSeconds = (timeMs.coerceAtLeast(0L) / 1000L)
        val hours = totalSeconds / 3600L
        val minutes = (totalSeconds % 3600L) / 60L
        val seconds = totalSeconds % 60L
        return if (hours > 0) {
            String.format(Locale.US, "%d:%02d:%02d", hours, minutes, seconds)
        } else {
            String.format(Locale.US, "%02d:%02d", minutes, seconds)
        }
    }

    private fun syncTopActionsVisibility(
        controllerVisibility: Int = if (playerView.isControllerFullyVisible) View.VISIBLE else View.GONE,
    ) {
        controllerVisible = controllerVisibility == View.VISIBLE && !isPictureInPictureActive()
        topActions.visibility = if (
            isPictureInPictureActive() || controllerVisibility != View.VISIBLE
        ) {
            View.GONE
        } else {
            View.VISIBLE
        }
        applySubtitleStyle()
    }

    private fun isPictureInPictureActive(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && isInPictureInPictureMode

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    private fun buildSeasonSections(): List<SeasonSection> {
        val knownResourceIds = (0 until resources.length()).mapNotNull { index ->
            resources.optJSONObject(index)?.optString("id")?.takeIf { it.isNotBlank() }
        }.toSet()
        val idsBySeason = linkedMapOf<Int, LinkedHashSet<String>>()
        val titlesBySeason = mutableMapOf<Int, String>()

        val metadataSeasons = session.optJSONObject("movie")?.optJSONArray("seasons")
        if (metadataSeasons != null) {
            for (index in 0 until metadataSeasons.length()) {
                val metadata = metadataSeasons.optJSONObject(index) ?: continue
                val season = metadata.optInt("season", 0).takeIf { it > 0 } ?: continue
                val ids = idsBySeason.getOrPut(season) { linkedSetOf() }
                val resourceIds = metadata.optJSONArray("resourceIds")
                if (resourceIds != null) {
                    for (resourceIndex in 0 until resourceIds.length()) {
                        val id = resourceIds.optString(resourceIndex)
                        if (id in knownResourceIds) ids += id
                    }
                }
                titlesBySeason[season] = metadata.optString("displayTitle")
                    .takeIf { it.isNotBlank() }
                    ?: "第 ${season} 季"
            }
        }

        val assignedIds = idsBySeason.values.flatten().toMutableSet()
        val standaloneIds = linkedSetOf<String>()
        for (index in 0 until resources.length()) {
            val resource = resources.optJSONObject(index) ?: continue
            val id = resource.optString("id").takeIf { it.isNotBlank() } ?: continue
            if (id in assignedIds) continue
            val season = resource.optInt("season", 0).takeIf { it > 0 }
            if (season == null) {
                standaloneIds += id
            } else {
                idsBySeason.getOrPut(season) { linkedSetOf() } += id
                titlesBySeason.putIfAbsent(season, "第 ${season} 季")
                assignedIds += id
            }
        }

        val seasonEntries = idsBySeason.entries
            .filter { it.value.isNotEmpty() }
            .sortedBy { it.key }
            .map { (season, ids) ->
                SeasonSection(
                    key = "season:$season",
                    season = season,
                    title = titlesBySeason[season] ?: "第 ${season} 季",
                    resourceIds = ids,
                )
            }
        if (seasonEntries.isEmpty()) {
            return listOf(
                SeasonSection(
                    key = "all",
                    season = null,
                    title = "选集",
                    resourceIds = knownResourceIds,
                ),
            )
        }

        return buildList {
            if (standaloneIds.isNotEmpty()) {
                add(
                    SeasonSection(
                        key = "standalone",
                        season = null,
                        title = "正片",
                        resourceIds = standaloneIds,
                    ),
                )
            }
            addAll(seasonEntries)
        }
    }

    private fun seasonSectionForResource(resource: JSONObject?): SeasonSection? {
        val resourceId = resource?.optString("id")?.takeIf { it.isNotBlank() } ?: return null
        return seasonSections.firstOrNull { resourceId in it.resourceIds }
    }

    private fun seasonForResource(resource: JSONObject): Int? =
        resource.optInt("season", 0).takeIf { it > 0 }
            ?: seasonSectionForResource(resource)?.season

    private fun resourcesForSeason(section: SeasonSection): List<Pair<Int, JSONObject>> =
        (0 until resources.length()).mapNotNull { index ->
            val resource = resources.optJSONObject(index) ?: return@mapNotNull null
            if (resource.optString("id") in section.resourceIds) index to resource else null
        }

    private fun episodeGroupsForSeason(section: SeasonSection): List<EpisodeGroup> {
        val groups = linkedMapOf<String, MutableList<JSONObject>>()
        resourcesForSeason(section).forEach { (_, resource) ->
            val episode = resource.optString("episode").trim()
            val key = if (episode.isNotBlank()) {
                "${seasonForResource(resource) ?: section.season ?: 0}:${episode.lowercase(Locale.ROOT)}"
            } else {
                "resource:${resource.optString("id")}"
            }
            groups.getOrPut(key) { mutableListOf() } += resource
        }
        return groups.map { (key, groupedResources) -> EpisodeGroup(key, groupedResources) }
    }

    private fun episodeGroupForResource(resource: JSONObject?): EpisodeGroup? {
        val id = resource?.optString("id")?.takeIf { it.isNotBlank() } ?: return null
        return seasonSections.asSequence()
            .flatMap { episodeGroupsForSeason(it).asSequence() }
            .firstOrNull { group -> group.resources.any { it.optString("id") == id } }
    }

    private fun allEpisodeGroups(): List<EpisodeGroup> = seasonSections.flatMap(::episodeGroupsForSeason)

    private fun selectedSeasonSection(): SeasonSection =
        seasonSections.firstOrNull { it.key == activeSeasonKey }
            ?: seasonSectionForResource(currentResource)
            ?: seasonSections.first()

    private fun findResource(id: String): JSONObject? {
        for (index in 0 until resources.length()) {
            val candidate = resources.optJSONObject(index) ?: continue
            if (candidate.optString("id") == id) return candidate
        }
        return null
    }

    private fun findResourceAt(index: Int): JSONObject? = resources.optJSONObject(index)

    private fun currentResourceIndex(): Int = (0 until resources.length()).firstOrNull {
        resources.optJSONObject(it)?.optString("id") == currentResource?.optString("id")
    } ?: 0

    private fun switchEpisodeBy(offset: Int) {
        if (contentKind != "series") return
        val groups = allEpisodeGroups()
        val currentId = currentResource?.optString("id")
        val currentIndex = groups.indexOfFirst { group ->
            group.resources.any { it.optString("id") == currentId }
        }.takeIf { it >= 0 } ?: 0
        val target = groups.getOrNull(currentIndex + offset) ?: return
        target.resources.firstOrNull()?.let { loadResource(it, 0L, shouldPlay = true) }
    }

    private fun updateEpisodeNavigation(selectedIndex: Int) {
        if (contentKind != "series") {
            previousEpisodeButton?.visibility = View.GONE
            nextEpisodeButton?.visibility = View.GONE
            rebuildPortraitMoviePanel()
            return
        }
        val groups = allEpisodeGroups()
        val currentId = currentResource?.optString("id")
        val groupIndex = groups.indexOfFirst { group ->
            group.resources.any { it.optString("id") == currentId }
        }.takeIf { it >= 0 } ?: 0
        previousEpisodeButton?.apply {
            isEnabled = groupIndex > 0
            alpha = if (isEnabled) 1f else 0.35f
        }
        nextEpisodeButton?.apply {
            isEnabled = groupIndex < groups.size - 1
            alpha = if (isEnabled) 1f else 0.35f
        }
        activeSeasonKey = seasonSectionForResource(currentResource)?.key ?: activeSeasonKey
        rebuildPortraitSeasonTabs()
        rebuildPortraitEpisodeGrid(selectedIndex)
    }

    private fun rebuildPortraitSeasonTabs() {
        val scroll = portraitSeasonScroll ?: return
        val tabs = portraitSeasonTabs ?: return
        val hasMultipleSections = seasonSections.size > 1
        scroll.visibility = if (hasMultipleSections) View.VISIBLE else View.GONE
        tabs.removeAllViews()
        if (!hasMultipleSections) return

        val activeSection = selectedSeasonSection()
        var selectedButton: Button? = null
        seasonSections.forEach { section ->
            val selected = section.key == activeSection.key
            val button = Button(this).apply {
                text = section.title
                contentDescription = "查看${section.title}"
                isAllCaps = false
                minWidth = 0
                minHeight = 0
                textSize = 13f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(if (selected) 0xFF5BE7FF.toInt() else 0xCFFFFFFF.toInt())
                setPadding(dp(15), 0, dp(15), 0)
                setBackgroundResource(
                    if (selected) R.drawable.player_season_chip_selected else R.drawable.player_season_chip,
                )
                stateListAnimator = null
                setOnClickListener {
                    if (activeSeasonKey != section.key) {
                        activeSeasonKey = section.key
                        rebuildPortraitSeasonTabs()
                        rebuildPortraitEpisodeGrid(currentResourceIndex())
                    }
                }
            }
            tabs.addView(
                button,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    dp(36),
                ).apply {
                    marginEnd = dp(8)
                },
            )
            if (selected) selectedButton = button
        }
        selectedButton?.let { button ->
            scroll.post {
                scroll.smoothScrollTo((button.left - dp(16)).coerceAtLeast(0), 0)
            }
        }
    }

    private fun rebuildPortraitEpisodeGrid(selectedIndex: Int) {
        val grid = portraitEpisodeGrid ?: return
        if (contentKind != "series") {
            grid.removeAllViews()
            return
        }
        val section = selectedSeasonSection()
        val visibleGroups = episodeGroupsForSeason(section)
        portraitEpisodeSummary?.text = if (seasonSections.size > 1) {
            "${section.title} · 共 ${visibleGroups.size} 集"
        } else {
            "共 ${visibleGroups.size} 集"
        }
        grid.removeAllViews()
        val margin = dp(4)
        val currentId = currentResource?.optString("id")
        visibleGroups.forEachIndexed { displayIndex, group ->
            val resource = group.resources.first()
            val selected = group.resources.any { it.optString("id") == currentId }
            val button = Button(this).apply {
                text = portraitEpisodeLabel(resource, displayIndex)
                contentDescription = buildString {
                    append(resource.optString("title", "第 ${displayIndex + 1} 集"))
                    if (group.resources.size > 1) append("，${group.resources.size} 个片源")
                }
                isAllCaps = false
                minWidth = 0
                minHeight = 0
                textSize = 13f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(if (selected) 0xFF5BE7FF.toInt() else 0xEFFFFFFF.toInt())
                setPadding(dp(4), 0, dp(4), 0)
                setBackgroundResource(
                    if (selected) R.drawable.player_episode_chip_selected else R.drawable.player_episode_chip,
                )
                stateListAnimator = null
                setOnClickListener {
                    when {
                        group.resources.size > 1 -> showEpisodeSources(group)
                        !selected -> loadResource(resource, 0L, shouldPlay = true)
                    }
                }
            }
            grid.addView(
                button,
                GridLayout.LayoutParams(
                    GridLayout.spec(displayIndex / 5),
                    GridLayout.spec(displayIndex % 5, 1, 1f),
                ).apply {
                    width = 0
                    height = dp(46)
                    setMargins(margin, margin, margin, margin)
                },
            )
        }
    }

    private fun portraitEpisodeLabel(resource: JSONObject, index: Int): String {
        val episode = resource.optString("episode").trim()
        return episode.toIntOrNull()?.toString()
            ?: episode.takeIf { it.isNotBlank() }
            ?: (index + 1).toString()
    }

    private fun dp(value: Int): Int =
        (value * applicationContext.resources.displayMetrics.density).toInt()

    private fun loadResource(
        resource: JSONObject,
        positionMs: Long,
        shouldPlay: Boolean = true,
        selectedQuality: CloudQuality? = null,
        resetTrackSelection: Boolean = true,
    ) {
        currentResource = resource
        currentQuality = selectedQuality
        reachedEnd = false
        lastError = null
        if (::playerErrorOverlay.isInitialized) playerErrorOverlay.visibility = View.GONE
        if (resetTrackSelection) {
            audioSelectionOverridden = false
            subtitleSelectionOverridden = false
            subtitlesDisabled = false
        }
        audioDecoderName = null
        videoDecoderName = null
        audioInputFormat = null
        videoInputFormat = null
        audioOutputEncoding = null
        audioOutputSampleRate = null
        audioOutputChannelCount = null
        audioOutputOffload = false
        if (resetTrackSelection) {
            trackSelector.setParameters(
                trackSelector.buildUponParameters()
                    .clearOverridesOfType(C.TRACK_TYPE_AUDIO)
                    .clearOverridesOfType(C.TRACK_TYPE_TEXT)
                    .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false),
            )
        }
        lastCueGroup = CueGroup.EMPTY_TIME_ZERO
        if (::externalSubtitleView.isInitialized) externalSubtitleView.setCues(emptyList())

        val direct = resource.optJSONObject("direct")
        if (direct == null || direct.optString("url").isBlank()) {
            Toast.makeText(this, "资源地址不可用", Toast.LENGTH_LONG).show()
            return
        }

        val httpDataSourceFactory = DefaultHttpDataSource.Factory()
            .setAllowCrossProtocolRedirects(true)
        val userAgent = direct.optString("userAgent")
        if (userAgent.isNotBlank()) httpDataSourceFactory.setUserAgent(userAgent)
        direct.optJSONObject("headers")?.let { headers ->
            val values = mutableMapOf<String, String>()
            headers.keys().forEach { key -> values[key] = headers.optString(key) }
            if (values.isNotEmpty()) httpDataSourceFactory.setDefaultRequestProperties(values)
        }
        // DefaultDataSource keeps HTTP behavior while also allowing the
        // temporary local subtitle file used by online-preview mode.
        val dataSourceFactory = DefaultDataSource.Factory(this, httpDataSourceFactory)

        val streamUrl = selectedQuality?.url ?: direct.getString("url")
        val itemBuilder = MediaItem.Builder()
            .setMediaId(resource.optString("id"))
            .setUri(streamUrl)
            .setMediaMetadata(buildSystemMediaMetadata(resource))
        val mimeType = selectedQuality?.format?.let(::qualityMimeType)
            ?: direct.optString("mimeType").takeIf { it.isNotBlank() }
        mimeType?.let {
            itemBuilder.setMimeType(it)
        }
        itemBuilder.setSubtitleConfigurations(buildSubtitles(resource.optJSONArray("subtitles")))
        val source = DefaultMediaSourceFactory(dataSourceFactory).createMediaSource(itemBuilder.build())

        player.setMediaSource(source)
        prepareCount += 1
        player.prepare()
        if (positionMs > 0) player.seekTo(positionMs)
        player.playWhenReady = shouldPlay

        audioButton.text = "音轨"
        audioButton.isEnabled = false
        subtitleButton.text = "字幕"
        subtitleButton.isEnabled =
            resource.optJSONArray("subtitles")?.length()?.let { it > 0 } == true ||
                resource.optJSONObject("onlineSubtitles") != null
        refreshPlayerChrome()
    }

    private fun qualityMimeType(format: String): String? = when (format.lowercase(Locale.ROOT)) {
        "m3u8", "hls" -> "application/x-mpegURL"
        "mpd", "dash" -> "application/dash+xml"
        "mp4", "m4v" -> "video/mp4"
        "webm" -> "video/webm"
        else -> null
    }

    private fun buildSystemMediaMetadata(resource: JSONObject): MediaMetadata {
        val displayTitle = playerDisplayTitle(resource)
        val movieTitle = session.optJSONObject("movie")?.optString("title").orEmpty().trim()
        val sourceLabel = resource.optString("title").trim()
            .takeIf { it.isNotBlank() && it != displayTitle && it != movieTitle }
            ?: resource.optJSONObject("technical")
                ?.optString("filename")
                ?.trim()
                ?.takeIf { it.isNotBlank() }
        val metadata = MediaMetadata.Builder()
            .setTitle(displayTitle)
            .setDisplayTitle(displayTitle)
            .setSubtitle(sourceLabel)
            .setMediaType(
                if (contentKind == "series") {
                    MediaMetadata.MEDIA_TYPE_TV_SHOW
                } else {
                    MediaMetadata.MEDIA_TYPE_MOVIE
                },
            )
            .setIsPlayable(true)

        session.optJSONObject("movie")
            ?.optString("posterUrl")
            ?.trim()
            ?.takeIf { it.startsWith("https://") || it.startsWith("http://") }
            ?.let { metadata.setArtworkUri(Uri.parse(it)) }
        return metadata.build()
    }

    private fun buildSubtitles(subtitles: JSONArray?): List<MediaItem.SubtitleConfiguration> {
        if (subtitles == null) return emptyList()
        val result = mutableListOf<MediaItem.SubtitleConfiguration>()
        for (index in 0 until subtitles.length()) {
            val subtitle = subtitles.optJSONObject(index) ?: continue
            if (!subtitle.optBoolean("supported", true)) continue
            val url = subtitle.optString("url")
            if (url.isBlank()) continue

            val builder = MediaItem.SubtitleConfiguration.Builder(android.net.Uri.parse(url))
            subtitleMimeType(subtitle)?.let { builder.setMimeType(it) }
            subtitle.optString("label").takeIf { it.isNotBlank() }?.let { builder.setLabel(it) }
            subtitle.optString("language").takeIf { it.isNotBlank() }?.let { builder.setLanguage(it) }
            var selectionFlags = 0
            if (subtitle.optBoolean("isDefault", false)) {
                selectionFlags = selectionFlags or C.SELECTION_FLAG_DEFAULT
            }
            if (subtitle.optBoolean("isForced", false)) {
                selectionFlags = selectionFlags or C.SELECTION_FLAG_FORCED
            }
            if (selectionFlags != 0) builder.setSelectionFlags(selectionFlags)
            result.add(builder.build())
        }
        return result
    }

    private fun subtitleMimeType(subtitle: JSONObject): String? = subtitleMimeType(
        format = subtitle.optString("format"),
        explicitMimeType = subtitle.optString("mimeType"),
    )

    private fun subtitleMimeType(format: String, explicitMimeType: String?): String? {
        // The selected URL determines the parser. In particular, an ASS/SRT
        // source may use a backend-generated WebVTT URL while the raw item
        // still advertises its original MIME type. Let the normalized format
        // win so Media3 never receives a VTT payload as text/x-ssa.
        return when (format.lowercase(Locale.ROOT)) {
            "vtt" -> "text/vtt"
            "srt" -> "application/x-subrip"
            "ass", "ssa" -> "text/x-ssa"
            else -> explicitMimeType
                ?.substringBefore(';')
                ?.trim()
                ?.takeIf { it.isNotBlank() }
        }
    }

    private fun showSourcePanel(sectionKey: String? = null) {
        if (contentKind != "series") {
            showPlaybackInfo()
            return
        }
        val currentId = currentResource?.optString("id")
        val section = seasonSections.firstOrNull { it.key == sectionKey }
            ?: seasonSectionForResource(currentResource)
            ?: selectedSeasonSection()
        activeSeasonKey = section.key
        val episodeGroups = episodeGroupsForSeason(section)

        activePanelKind = "episodes"
        sidePanelTitle.text = "剧集"
        sidePanelItems.removeAllViews()
        if (seasonSections.size > 1) addSeasonTabsToPanel(section)
        val summary = TextView(this).apply {
            text = if (seasonSections.size > 1) {
                "${section.title} · ${episodeGroups.size} 集"
            } else {
                "共 ${episodeGroups.size} 集"
            }
            textSize = 13f
            setTextColor(0x8FFFFFFF.toInt())
            setPadding(dp(4), dp(8), dp(4), dp(10))
        }
        sidePanelItems.addView(
            summary,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ),
        )

        episodeGroups.forEachIndexed { index, group ->
            val resource = group.resources.first()
            val selected = group.resources.any { it.optString("id") == currentId }
            val episode = episodeLabel(resource)
            val details = listOfNotNull(
                resource.optString("title").takeIf { episode != null && it.isNotBlank() },
                if (group.resources.size > 1) "${group.resources.size} 个片源" else resourceSummary(resource),
                if (selected) "正在播放" else null,
            ).joinToString(" · ")
            addPanelItemRow(
                PanelItem(
                    title = episode ?: resource.optString("title", "第 ${index + 1} 集"),
                    subtitle = details.takeIf { it.isNotBlank() },
                    selected = selected,
                    closeOnAction = group.resources.size <= 1,
                    action = {
                        if (group.resources.size > 1) {
                            showEpisodeSources(group)
                        } else if (!selected) {
                            loadResource(resource, 0L, shouldPlay = true)
                        }
                    },
                ),
            )
        }
        if (!sidePanelOpen) openSidePanel()
    }

    private fun showEpisodeSources(group: EpisodeGroup) {
        activePanelKind = "episode_sources"
        val first = group.resources.firstOrNull() ?: return
        sidePanelTitle.text = "${episodeLabel(first) ?: "本集"} · 选择片源"
        sidePanelItems.removeAllViews()
        val currentId = currentResource?.optString("id")
        group.resources.forEachIndexed { index, resource ->
            val selected = resource.optString("id") == currentId
            addPanelItemRow(
                PanelItem(
                    title = resourceChoiceTitle(resource, index),
                    subtitle = resourceSummary(resource),
                    selected = selected,
                    enabled = !selected,
                    action = { switchToResource(resource, preservePosition = true) },
                ),
            )
        }
        if (!sidePanelOpen) openSidePanel()
    }

    private fun switchToResource(resource: JSONObject, preservePosition: Boolean) {
        val position = if (preservePosition && ::player.isInitialized) {
            val duration = player.duration.takeIf { it > 0 }
            if (duration == null) player.currentPosition.coerceAtLeast(0L)
            else player.currentPosition.coerceIn(0L, duration)
        } else {
            0L
        }
        val shouldPlay = player.playWhenReady
        loadResource(resource, position, shouldPlay = shouldPlay)
    }

    private fun resourceChoiceTitle(resource: JSONObject, index: Int): String {
        val technical = resource.optJSONObject("technical")
        return technical?.optString("filename")?.takeIf { it.isNotBlank() }
            ?: resource.optString("title").takeIf { it.isNotBlank() }
            ?: "片源 ${index + 1}"
    }

    private fun resourceSummary(resource: JSONObject): String? {
        val technical = resource.optJSONObject("technical")
        val badges = technical?.optJSONArray("badges")
        val badgeText = if (badges == null) null else (0 until badges.length())
            .mapNotNull { badges.optString(it).takeIf(String::isNotBlank) }
            .joinToString(" · ")
            .takeIf { it.isNotBlank() }
        val size = technical?.optLong("sizeBytes", 0L)?.takeIf { it > 0 }?.let(::formatFileSize)
        return listOfNotNull(
            technical?.optString("storageSource")?.takeIf { it.isNotBlank() },
            size,
            badgeText,
        ).joinToString(" · ").takeIf { it.isNotBlank() }
    }

    private fun addSeasonTabsToPanel(selectedSection: SeasonSection) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        seasonSections.forEach { section ->
            val selected = section.key == selectedSection.key
            val button = Button(this).apply {
                text = section.title
                contentDescription = "查看${section.title}"
                isAllCaps = false
                minWidth = 0
                minHeight = 0
                textSize = 13f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(if (selected) 0xFF5BE7FF.toInt() else 0xCFFFFFFF.toInt())
                setPadding(dp(15), 0, dp(15), 0)
                setBackgroundResource(
                    if (selected) R.drawable.player_season_chip_selected else R.drawable.player_season_chip,
                )
                stateListAnimator = null
                setOnClickListener {
                    if (!selected) showSourcePanel(section.key)
                }
            }
            row.addView(
                button,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    dp(38),
                ).apply {
                    marginEnd = dp(8)
                },
            )
        }
        val scroller = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            clipToPadding = false
            setPadding(dp(2), dp(4), dp(2), dp(6))
            addView(
                row,
                ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
        sidePanelItems.addView(
            scroller,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(50),
            ),
        )
    }

    private fun episodeLabel(resource: JSONObject): String? {
        val episode = resource.optString("episode").trim()
        if (episode.isBlank()) return null
        val season = seasonForResource(resource) ?: 0
        val episodeNumber = episode.toIntOrNull()
        return when {
            season > 0 && episodeNumber != null -> String.format(Locale.US, "S%02dE%02d", season, episodeNumber)
            episodeNumber != null -> "第 ${episodeNumber} 集"
            else -> episode
        }
    }

    private fun playerDisplayTitle(resource: JSONObject): String {
        val movieTitle = session.optJSONObject("movie")?.optString("title").orEmpty().trim()
        val episode = episodeLabel(resource)
        return when {
            movieTitle.isNotBlank() && episode != null -> "$movieTitle · $episode"
            movieTitle.isNotBlank() -> movieTitle
            else -> resource.optString("title", "CyberStream")
        }
    }

    private fun collectAudioTracks(tracks: Tracks = player.currentTracks): List<AudioTrackChoice> {
        val result = mutableListOf<AudioTrackChoice>()
        tracks.groups.forEach { group ->
            if (group.type != C.TRACK_TYPE_AUDIO) return@forEach
            for (trackIndex in 0 until group.length) {
                result.add(
                    AudioTrackChoice(
                        group = group.mediaTrackGroup,
                        trackIndex = trackIndex,
                        format = group.getTrackFormat(trackIndex),
                        selected = group.isTrackSelected(trackIndex),
                        supported = group.isTrackSupported(trackIndex),
                    ),
                )
            }
        }
        return result
    }

    private fun showAudioPanel() {
        val choices = collectAudioTracks()
        if (choices.isEmpty()) {
            Toast.makeText(this, "当前文件没有可选择的音轨", Toast.LENGTH_SHORT).show()
            return
        }

        val items = mutableListOf(
            PanelItem(
                title = "自动选择",
                subtitle = "按片源默认标记与设备能力选择",
                selected = !audioSelectionOverridden,
                action = {
                    audioSelectionOverridden = false
                    trackSelector.setParameters(
                        trackSelector.buildUponParameters().clearOverridesOfType(C.TRACK_TYPE_AUDIO),
                    )
                },
            ),
        )
        choices.forEach { choice ->
            items += PanelItem(
                title = audioTrackIdentity(choice.format),
                subtitle = audioTrackDetails(choice.format),
                selected = audioSelectionOverridden && choice.selected,
                enabled = choice.supported,
                action = {
                    audioSelectionOverridden = true
                    trackSelector.setParameters(
                        trackSelector.buildUponParameters()
                            .clearOverridesOfType(C.TRACK_TYPE_AUDIO)
                            .setOverrideForType(TrackSelectionOverride(choice.group, choice.trackIndex)),
                    )
                },
            )
        }
        showSelectionPanel("音轨", items)
    }

    private fun updateAudioButtonLabel(tracks: Tracks) {
        val choices = collectAudioTracks(tracks)
        val selected = choices.firstOrNull { it.selected }?.format ?: audioInputFormat
        audioButton.isEnabled = choices.isNotEmpty()
        audioButton.text = if (isPortraitLayout) {
            "音轨"
        } else {
            selected?.let { compactAudioTrackDescription(it) } ?: "音轨"
        }
    }

    private fun compactAudioTrackDescription(format: Format): String =
        listOf(audioCodecLabel(format), channelLayout(format.channelCount))
            .filter { it.isNotBlank() }
            .joinToString(" · ")
            .ifBlank { "音轨" }

    private fun audioTrackIdentity(format: Format): String =
        format.label?.takeIf { it.isNotBlank() }
            ?: format.language?.takeIf { it.isNotBlank() }
            ?: "未命名音轨"

    private fun audioTrackDetails(format: Format): String = listOfNotNull(
        audioCodecLabel(format),
        format.channelCount.takeIf { it > 0 }?.let(::channelLayout),
        format.sampleRate.takeIf { it > 0 }?.let(::sampleRateLabel),
        bitrateLabel(format),
    ).joinToString(" · ")

    private fun collectSubtitleTracks(tracks: Tracks = player.currentTracks): List<SubtitleTrackChoice> {
        val result = mutableListOf<SubtitleTrackChoice>()
        tracks.groups.forEach { group ->
            if (group.type != C.TRACK_TYPE_TEXT) return@forEach
            for (trackIndex in 0 until group.length) {
                result += SubtitleTrackChoice(
                    group = group.mediaTrackGroup,
                    trackIndex = trackIndex,
                    format = group.getTrackFormat(trackIndex),
                    selected = group.isTrackSelected(trackIndex),
                    supported = group.isTrackSupported(trackIndex),
                )
            }
        }
        return result
    }

    private fun showSubtitlePanel() {
        val choices = collectSubtitleTracks()
        val items = mutableListOf(
            PanelItem(
                title = "关闭字幕",
                subtitle = "保留视频原始画面",
                selected = subtitlesDisabled,
                action = {
                    subtitlesDisabled = true
                    subtitleSelectionOverridden = false
                    trackSelector.setParameters(
                        trackSelector.buildUponParameters()
                            .clearOverridesOfType(C.TRACK_TYPE_TEXT)
                            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, true),
                    )
                    updateSubtitleButtonLabel(player.currentTracks)
                },
            ),
            PanelItem(
                title = "自动选择",
                subtitle = "优先默认字幕与强制字幕",
                selected = choices.isNotEmpty() && !subtitlesDisabled && !subtitleSelectionOverridden,
                enabled = choices.isNotEmpty(),
                action = {
                    subtitlesDisabled = false
                    subtitleSelectionOverridden = false
                    trackSelector.setParameters(
                        trackSelector.buildUponParameters()
                            .clearOverridesOfType(C.TRACK_TYPE_TEXT)
                            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false),
                    )
                    updateSubtitleButtonLabel(player.currentTracks)
                },
            ),
        )
        choices.forEach { choice ->
            items += PanelItem(
                title = subtitleTrackIdentity(choice.format),
                subtitle = subtitleTrackDetails(choice.format),
                selected = !subtitlesDisabled && subtitleSelectionOverridden && choice.selected,
                enabled = choice.supported,
                action = {
                    subtitlesDisabled = false
                    subtitleSelectionOverridden = true
                    trackSelector.setParameters(
                        trackSelector.buildUponParameters()
                            .clearOverridesOfType(C.TRACK_TYPE_TEXT)
                            .setTrackTypeDisabled(C.TRACK_TYPE_TEXT, false)
                            .setOverrideForType(TrackSelectionOverride(choice.group, choice.trackIndex)),
                    )
                    updateSubtitleButtonLabel(player.currentTracks)
                },
            )
        }
        currentResource?.optJSONObject("onlineSubtitles")?.let {
            items += PanelItem(
                title = "在线搜索字幕",
                subtitle = "SubHD · SrtKu · 点击候选先预览，绑定需单独确认",
                closeOnAction = false,
                action = ::showOnlineSubtitleSearchPanel,
            )
        }
        showSelectionPanel("字幕", items)
    }

    private fun updateSubtitleButtonLabel(tracks: Tracks) {
        val choices = collectSubtitleTracks(tracks)
        val hasDeclaredSubtitles = currentResource?.optJSONArray("subtitles")?.length()?.let { it > 0 } == true
        val hasOnlineSubtitles = currentResource?.optJSONObject("onlineSubtitles") != null
        subtitleButton.isEnabled = choices.isNotEmpty() || hasDeclaredSubtitles || hasOnlineSubtitles
        subtitleButton.text = when {
            subtitlesDisabled -> "字幕关"
            choices.any { it.selected } -> "字幕开"
            else -> "字幕"
        }
    }

    private fun subtitleTrackIdentity(format: Format): String =
        format.label?.takeIf { it.isNotBlank() }
            ?: format.language?.takeIf { it.isNotBlank() }
            ?: "未命名字幕"

    private fun subtitleTrackDetails(format: Format): String? {
        val details = listOfNotNull(
            format.language?.takeIf { it.isNotBlank() && it != format.label },
            format.sampleMimeType?.substringAfterLast('/')?.uppercase(Locale.ROOT),
        )
        return details.joinToString(" · ").takeIf { it.isNotBlank() }
    }

    private fun showOnlineSubtitleSearchPanel() {
        val resource = currentResource ?: return
        val config = resource.optJSONObject("onlineSubtitles") ?: run {
            Toast.makeText(this, "当前片源未提供在线字幕入口", Toast.LENGTH_SHORT).show()
            return
        }
        activePanelKind = "online_subtitles"
        sidePanelTitle.text = "在线字幕"
        sidePanelItems.removeAllViews()

        val header = layoutInflater.inflate(
            R.layout.player_online_subtitle_search,
            sidePanelItems,
            false,
        )
        val queryField = header.findViewById<EditText>(R.id.online_subtitle_query)
        val searchButton = header.findViewById<Button>(R.id.online_subtitle_search)
        val progress = header.findViewById<ProgressBar>(R.id.online_subtitle_progress)
        val status = header.findViewById<TextView>(R.id.online_subtitle_status)
        queryField.setText(config.optString("defaultKeyword"))
        queryField.setSelection(queryField.text.length)
        sidePanelItems.addView(header)

        val startSearch = {
            dismissKeyboard(queryField)
            val keyword = queryField.text?.toString()?.trim().orEmpty()
            performOnlineSubtitleSearch(
                config = config,
                resourceId = resource.optString("id"),
                keyword = keyword,
                header = header,
                searchButton = searchButton,
                progress = progress,
                status = status,
            )
        }
        searchButton.setOnClickListener { startSearch() }
        queryField.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                startSearch()
                true
            } else {
                false
            }
        }
        if (!sidePanelOpen) openSidePanel()
        header.post { startSearch() }
    }

    private fun performOnlineSubtitleSearch(
        config: JSONObject,
        resourceId: String,
        keyword: String,
        header: View,
        searchButton: Button,
        progress: ProgressBar,
        status: TextView,
    ) {
        if (resourceId.isBlank() || onlineSubtitleSearching || onlineSubtitleBinding || onlineSubtitlePreviewing) return
        val searchEndpoint = config.optString("searchUrl")
        if (searchEndpoint.isBlank()) {
            status.text = "在线字幕搜索地址不可用"
            return
        }
        val requestId = ++onlineSubtitleRequestId
        onlineSubtitleSearching = true
        removePanelViewsAfter(header)
        searchButton.isEnabled = false
        progress.visibility = View.VISIBLE
        status.text = "正在搜索 SubHD 与 SrtKu…"

        val builder = Uri.parse(searchEndpoint).buildUpon()
        if (keyword.isNotBlank()) builder.appendQueryParameter("keyword", keyword)
        val providers = config.optJSONArray("providers")?.toStringList()?.joinToString(",")
        if (!providers.isNullOrBlank()) builder.appendQueryParameter("providers", providers)
        if (builder.build().getQueryParameter("limit") == null) {
            builder.appendQueryParameter("limit", config.optInt("limit", 20).coerceIn(1, 50).toString())
        }
        val searchUrl = builder.build().toString()

        networkExecutor.execute {
            val result = requestJson(searchUrl)
            handler.post {
                if (requestId == onlineSubtitleRequestId) onlineSubtitleSearching = false
                if (
                    didFinish || requestId != onlineSubtitleRequestId ||
                    activePanelKind != "online_subtitles" ||
                    currentResource?.optString("id") != resourceId
                ) {
                    return@post
                }
                searchButton.isEnabled = true
                progress.visibility = View.GONE
                if (!result.successful) {
                    status.text = onlineSubtitleFailureMessage(
                        status = result.status,
                        message = result.message,
                        fallback = "在线字幕搜索失败",
                    )
                    addPanelMessage("没有取得字幕候选", status.text.toString())
                    return@post
                }
                val data = result.body?.optJSONObject("data") ?: result.body ?: JSONObject()
                val candidates = data.optJSONArray("items") ?: JSONArray()
                val providerNotice = onlineSubtitleProviderNotice(data.optJSONObject("providers"))
                status.text = if (candidates.length() > 0) {
                    "找到 ${candidates.length()} 条候选${providerNotice?.let { " · $it" }.orEmpty()}"
                } else {
                    "没有匹配结果${providerNotice?.let { " · $it" }.orEmpty()}"
                }
                if (candidates.length() == 0) {
                    addPanelMessage("未找到在线字幕", "可以修改影片名、英文名或季集编号后重试")
                    return@post
                }
                for (index in 0 until candidates.length()) {
                    val candidate = candidates.optJSONObject(index) ?: continue
                    addOnlineSubtitleCandidate(
                        config = config,
                        resourceId = resourceId,
                        keyword = keyword,
                        candidate = candidate,
                        progress = progress,
                        status = status,
                    )
                }
            }
        }
    }

    private fun addOnlineSubtitleCandidate(
        config: JSONObject,
        resourceId: String,
        keyword: String,
        candidate: JSONObject,
        progress: ProgressBar,
        status: TextView,
    ) {
        val candidateId = candidate.optString("candidate_id")
            .ifBlank { candidate.optString("id") }
        if (candidateId.isBlank()) return
        val normalizedFormat = candidate.optString("format_normalized")
            .ifBlank { candidate.optString("format") }
            .lowercase(Locale.ROOT)
        val bitmapSubtitle = normalizedFormat in setOf("sub", "sup", "pgs")
        val provider = candidate.optString("provider_name")
            .ifBlank { candidate.optString("provider_id") }
            .ifBlank {
                candidate.optJSONArray("downloads")
                    ?.optJSONObject(0)
                    ?.optString("provider_id")
                    .orEmpty()
            }
            .ifBlank { candidateId.substringBefore(':') }
        val language = candidate.optJSONArray("language")?.toStringList()?.joinToString(" / ")
        val formatLabel = normalizedFormat.takeIf { it.isNotBlank() }?.uppercase(Locale.ROOT)
            ?: "格式待下载确认"
        val downloads = candidate.optInt("download_count", 0).takeIf { it > 0 }?.toString()
            ?: candidate.optString("download_number").takeIf { it.isNotBlank() }
        val quality = candidate.optString("quality").takeIf { it.isNotBlank() }
        val fileSize = candidate.optString("file_size").takeIf { it.isNotBlank() }
        val details = listOfNotNull(
            provider.takeIf { it.isNotBlank() }?.replaceFirstChar { it.uppercase() },
            language?.takeIf { it.isNotBlank() },
            formatLabel,
            quality,
            fileSize,
            downloads?.let { "$it 次下载" },
            if (bitmapSubtitle) "位图字幕暂不支持" else "点击条目预览 · 绑定需单独确认",
        ).joinToString(" · ")
        val title = candidate.optString("title").ifBlank {
            candidate.optString("film_name").ifBlank { "未命名字幕" }
        }
        val row = layoutInflater.inflate(
            R.layout.player_online_subtitle_candidate,
            sidePanelItems,
            false,
        )
        row.findViewById<TextView>(R.id.online_subtitle_candidate_title).text = title
        row.findViewById<TextView>(R.id.online_subtitle_candidate_details).text = details
        val previewButton = row.findViewById<Button>(R.id.online_subtitle_candidate_preview)
        val bindButton = row.findViewById<Button>(R.id.online_subtitle_candidate_bind)
        previewButton.contentDescription = "预览 $title"
        bindButton.contentDescription = "绑定 $title"
        row.alpha = if (bitmapSubtitle) 0.42f else 1f
        row.isEnabled = !bitmapSubtitle
        previewButton.isEnabled = !bitmapSubtitle
        bindButton.isEnabled = !bitmapSubtitle
        if (!bitmapSubtitle) {
            val previewAction = {
                previewOnlineSubtitle(
                    config = config,
                    resourceId = resourceId,
                    candidate = candidate,
                    row = row,
                    previewButton = previewButton,
                    bindButton = bindButton,
                    progress = progress,
                    status = status,
                )
            }
            row.setOnClickListener { previewAction() }
            previewButton.setOnClickListener { previewAction() }
            bindButton.setOnClickListener {
                bindOnlineSubtitle(
                    config = config,
                    resourceId = resourceId,
                    keyword = keyword,
                    candidate = candidate,
                    progress = progress,
                    status = status,
                )
            }
        }
        sidePanelItems.addView(row)
    }

    private fun previewOnlineSubtitle(
        config: JSONObject,
        resourceId: String,
        candidate: JSONObject,
        row: View,
        previewButton: Button,
        bindButton: Button,
        progress: ProgressBar,
        status: TextView,
    ) {
        if (onlineSubtitlePreviewing || onlineSubtitleBinding || onlineSubtitleSearching) return
        val candidateId = candidate.optString("candidate_id")
            .ifBlank { candidate.optString("id") }
        val downloadUrl = config.optString("downloadUrl")
        if (candidateId.isBlank() || downloadUrl.isBlank()) {
            status.text = "当前版本没有可用的字幕预览地址"
            return
        }
        val downloadIndex = candidate.optJSONArray("downloads")
            ?.optJSONObject(0)
            ?.optInt("download_index", 0)
            ?: 0
        val payload = JSONObject()
            .put("candidate_id", candidateId)
            .put("download_index", downloadIndex)
        val requestId = ++onlineSubtitleRequestId
        onlineSubtitlePreviewing = true
        previewButton.isEnabled = false
        previewButton.text = "下载中…"
        bindButton.isEnabled = false
        progress.visibility = View.VISIBLE
        status.text = "正在下载字幕预览，不会绑定到媒体库…"

        networkExecutor.execute {
            val result = requestBytes(downloadUrl, payload)
            val format = previewSubtitleFormat(candidate, result.contentType)
            val file = if (result.successful && format != null) {
                savePreviewSubtitle(requestId, format, result.bytes!!)
            } else {
                null
            }
            handler.post {
                onlineSubtitlePreviewing = false
                if (
                    didFinish || requestId != onlineSubtitleRequestId ||
                    currentResource?.optString("id") != resourceId ||
                    row.parent == null
                ) {
                    file?.delete()
                    return@post
                }
                progress.visibility = View.GONE
                previewButton.isEnabled = true
                previewButton.text = "预览"
                bindButton.isEnabled = true
                if (!result.successful || file == null || format == null) {
                    status.text = onlineSubtitleFailureMessage(
                        status = result.status,
                        message = result.message,
                        fallback = "字幕预览下载失败，请换一个候选",
                    )
                    file?.delete()
                    return@post
                }
                val resource = currentResource ?: run {
                    file.delete()
                    return@post
                }
                val currentItems = resource.optJSONArray("subtitles") ?: JSONArray()
                val previewItems = JSONArray()
                for (index in 0 until currentItems.length()) {
                    val item = currentItems.optJSONObject(index) ?: continue
                    if (item.optString("id") == ONLINE_SUBTITLE_PREVIEW_ID) continue
                    previewItems.put(JSONObject(item.toString()).put("isDefault", false))
                }
                val title = candidate.optString("title")
                    .ifBlank { candidate.optString("film_name") }
                    .ifBlank { "在线字幕" }
                previewItems.put(
                    JSONObject()
                        .put("id", ONLINE_SUBTITLE_PREVIEW_ID)
                        .put("label", "预览 · $title")
                        .put("format", format)
                        .put("mimeType", subtitleMimeType(format, result.contentType))
                        .put("url", Uri.fromFile(file).toString())
                        .put("isDefault", true)
                        .put("supported", true),
                )
                resource.put("subtitles", previewItems)
                rawSessionJson = session.toString()
                val oldPreview = previewSubtitleFile
                previewSubtitleFile = file
                val position = player.currentPosition.coerceAtLeast(0L)
                val shouldPlay = player.playWhenReady
                loadResource(resource, position, shouldPlay = shouldPlay, resetTrackSelection = true)
                oldPreview?.takeIf { it != file }?.delete()
                previewButton.text = "预览中"
                row.setBackgroundResource(R.drawable.player_panel_item_selected)
                status.text = "正在预览此字幕 · 尚未绑定"
            }
        }
    }

    private fun previewSubtitleFormat(candidate: JSONObject, contentType: String?): String? {
        val declared = candidate.optString("format_normalized")
            .ifBlank { candidate.optString("format") }
            .lowercase(Locale.ROOT)
        if (declared in setOf("vtt", "srt", "ass", "ssa")) return declared
        return when (contentType?.substringBefore(';')?.trim()?.lowercase(Locale.ROOT)) {
            "text/vtt" -> "vtt"
            "application/x-subrip" -> "srt"
            "text/x-ssa", "text/x-ass" -> "ass"
            "text/plain" -> "srt"
            else -> null
        }
    }

    private fun savePreviewSubtitle(requestId: Int, format: String, bytes: ByteArray): File? = runCatching {
        val directory = File(cacheDir, "online-subtitle-preview").apply { mkdirs() }
        File(directory, "preview-$requestId.$format").also { file ->
            FileOutputStream(file).use { it.write(bytes) }
        }
    }.getOrNull()

    private fun bindOnlineSubtitle(
        config: JSONObject,
        resourceId: String,
        keyword: String,
        candidate: JSONObject,
        progress: ProgressBar,
        status: TextView,
    ) {
        if (onlineSubtitleBinding || onlineSubtitlePreviewing || onlineSubtitleSearching) return
        val candidateId = candidate.optString("candidate_id")
            .ifBlank { candidate.optString("id") }
        val bindUrl = config.optString("bindUrl")
        if (candidateId.isBlank() || bindUrl.isBlank()) return
        val downloadIndex = candidate.optJSONArray("downloads")
            ?.optJSONObject(0)
            ?.optInt("download_index", 0)
            ?: 0
        val payload = JSONObject()
            .put("candidate_id", candidateId)
            .put("download_index", downloadIndex)
            .put("confirm", true)
        val requestId = ++onlineSubtitleRequestId
        onlineSubtitleBinding = true
        progress.visibility = View.VISIBLE
        status.text = "正在下载并绑定字幕…"

        networkExecutor.execute {
            val result = requestJson(bindUrl, "POST", payload)
            handler.post {
                onlineSubtitleBinding = false
                if (
                    didFinish || requestId != onlineSubtitleRequestId ||
                    currentResource?.optString("id") != resourceId
                ) {
                    return@post
                }
                progress.visibility = View.GONE
                if (!result.successful) {
                    status.text = onlineSubtitleFailureMessage(
                        status = result.status,
                        message = result.message,
                        fallback = "字幕源下载失败，请换一个候选",
                    )
                    return@post
                }
                val data = result.body?.optJSONObject("data") ?: result.body ?: JSONObject()
                val selectedSubtitleId = data.optJSONObject("subtitle")?.optString("id").orEmpty()
                val rawItems = data.optJSONObject("subtitles")?.optJSONArray("items")
                    ?: data.optJSONObject("playback")
                        ?.optJSONObject("subtitles")
                        ?.optJSONArray("items")
                if (rawItems == null || rawItems.length() == 0) {
                    status.text = "字幕已绑定，但播放器没有收到可加载地址"
                    return@post
                }
                val normalized = normalizeBoundSubtitles(
                    rawItems = rawItems,
                    config = config,
                    selectedSubtitleId = selectedSubtitleId,
                )
                if (normalized.length() == 0) {
                    status.text = "字幕格式暂不受 Android 播放器支持"
                    return@post
                }
                val resource = currentResource ?: return@post
                resource.put("subtitles", normalized)
                rawSessionJson = session.toString()
                val position = player.currentPosition.coerceAtLeast(0L)
                val shouldPlay = player.playWhenReady
                loadResource(resource, position, shouldPlay = shouldPlay, resetTrackSelection = true)
                previewSubtitleFile?.delete()
                previewSubtitleFile = null
                Toast.makeText(this, "在线字幕已下载并应用", Toast.LENGTH_SHORT).show()
                closeSidePanel()
            }
        }
    }

    private fun normalizeBoundSubtitles(
        rawItems: JSONArray,
        config: JSONObject,
        selectedSubtitleId: String,
    ): JSONArray {
        val normalized = JSONArray()
        for (index in 0 until rawItems.length()) {
            val raw = rawItems.optJSONObject(index) ?: continue
            val id = raw.optString("id")
            if (id.isBlank()) continue
            val webPlayer = raw.optJSONObject("web_player")
            val webPlayerUrl = webPlayer?.optString("url")?.takeIf { it.isNotBlank() }
            val format = if (webPlayerUrl != null) {
                webPlayer.optString("format").takeIf { it.isNotBlank() }
                    ?: raw.optString("format")
            } else {
                raw.optString("format")
            }
            if (format.lowercase(Locale.ROOT) in setOf("sub", "sup", "pgs")) continue
            val sourceUrl = webPlayerUrl ?: raw.optString("url")
            if (sourceUrl.isBlank()) continue
            val explicitMimeType = if (webPlayerUrl != null) {
                webPlayer.optString("mime_type").takeIf { it.isNotBlank() }
            } else {
                raw.optString("mime_type").takeIf { it.isNotBlank() }
            }
            val native = JSONObject()
                .put("id", id)
                .put(
                    "label",
                    raw.optString("display_name")
                        .ifBlank { raw.optString("label") }
                        .ifBlank { raw.optString("filename") }
                        .ifBlank { "在线字幕" },
                )
                .put("format", format.lowercase(Locale.ROOT))
                .put("mimeType", subtitleMimeType(format, explicitMimeType))
                .put("url", resolveOnlineSubtitleUrl(config, sourceUrl))
                .put("isDefault", id == selectedSubtitleId || raw.optBoolean("is_default", false))
                .put("isForced", raw.optBoolean("is_forced", false))
                .put("supported", webPlayer?.optBoolean("supported", true) != false)
            subtitleLanguageLabel(raw.opt("language"))?.let { native.put("language", it) }
            normalized.put(native)
        }
        return normalized
    }

    private fun resolveOnlineSubtitleUrl(config: JSONObject, value: String): String {
        val apiBase = config.optString("apiBaseUrl").trimEnd('/')
        val resolved = when {
            value.startsWith("http://") || value.startsWith("https://") -> value
            value.startsWith("/api/") -> {
                val origin = runCatching {
                    val parsed = URL(apiBase)
                    "${parsed.protocol}://${parsed.authority}"
                }.getOrDefault(apiBase.removeSuffix("/api"))
                "$origin$value"
            }
            value.startsWith("/v1/") -> "$apiBase$value"
            value.startsWith("/") -> {
                val origin = runCatching {
                    val parsed = URL(apiBase)
                    "${parsed.protocol}://${parsed.authority}"
                }.getOrDefault(apiBase.removeSuffix("/api"))
                "$origin$value"
            }
            else -> "$apiBase/$value"
        }
        val ticket = Uri.parse(config.optString("bindUrl")).getQueryParameter("ticket")
        if (ticket.isNullOrBlank() || Uri.parse(resolved).getQueryParameter("ticket") != null) {
            return resolved
        }
        return Uri.parse(resolved).buildUpon().appendQueryParameter("ticket", ticket).build().toString()
    }

    private fun subtitleLanguageLabel(value: Any?): String? = when (value) {
        is String -> value.takeIf { it.isNotBlank() }
        is JSONObject -> listOf("label", "name", "code")
            .firstNotNullOfOrNull { key -> value.optString(key).takeIf { it.isNotBlank() } }
        is JSONArray -> value.toStringList().joinToString(" / ").takeIf { it.isNotBlank() }
        else -> null
    }

    private fun JSONArray.toStringList(): List<String> = (0 until length()).mapNotNull { index ->
        optString(index).takeIf { it.isNotBlank() }
    }

    private fun removePanelViewsAfter(header: View) {
        val headerIndex = sidePanelItems.indexOfChild(header)
        while (headerIndex >= 0 && sidePanelItems.childCount > headerIndex + 1) {
            sidePanelItems.removeViewAt(headerIndex + 1)
        }
    }

    private fun onlineSubtitleProviderNotice(providers: JSONObject?): String? {
        if (providers == null) return null
        val used = providers.optJSONArray("used")?.toStringList()?.joinToString("+")
        val errors = providers.optJSONArray("errors")
        val errorText = if (errors == null || errors.length() == 0) null else {
            (0 until errors.length()).mapNotNull { index ->
                val error = errors.optJSONObject(index) ?: return@mapNotNull null
                val provider = error.optString("provider_id").ifBlank { "字幕源" }
                val reason = when (error.optString("reason").lowercase(Locale.ROOT)) {
                    "timeout" -> "超时"
                    "rate_limited" -> "繁忙"
                    "unknown_captcha", "captcha" -> "需要验证码"
                    else -> error.optString("reason").ifBlank { "不可用" }
                }
                "$provider $reason"
            }.joinToString("、").takeIf { it.isNotBlank() }
        }
        return listOfNotNull(used?.takeIf { it.isNotBlank() }, errorText).joinToString(" · ").takeIf { it.isNotBlank() }
    }

    private fun onlineSubtitleFailureMessage(
        status: Int,
        message: String?,
        fallback: String,
    ): String {
        val normalized = message.orEmpty().lowercase(Locale.ROOT)
        return when {
            status == 401 -> "播放授权已过期，请退出播放器后重新进入"
            status == 409 -> "该字幕已经绑定，可返回字幕列表选择"
            status == 413 -> "字幕压缩包过大，已停止下载"
            status == 429 || normalized.contains("rate_limit") -> "字幕源正忙，请稍后重试"
            normalized.contains("unknown_captcha") || normalized.contains("captcha") ->
                "该字幕源需要验证码，请换用另一个候选或字幕源"
            normalized.contains("timeout") -> "字幕源响应超时，请稍后重试"
            status == 502 -> fallback
            !message.isNullOrBlank() -> message
            else -> fallback
        }
    }

    private fun dismissKeyboard(view: View) {
        (getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager)
            ?.hideSoftInputFromWindow(view.windowToken, 0)
        view.clearFocus()
    }

    private fun requestJson(
        endpoint: String,
        method: String = "GET",
        payload: JSONObject? = null,
    ): HttpJsonResult {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
                requestMethod = method
                instanceFollowRedirects = true
                connectTimeout = 15_000
                readTimeout = 60_000
                setRequestProperty("Accept", "application/json")
                if (payload != null) {
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                }
            }
            if (payload != null) {
                connection.outputStream.use { output ->
                    output.write(payload.toString().toByteArray(Charsets.UTF_8))
                }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            val body = text.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }
            HttpJsonResult(
                status = status,
                body = body,
                message = body?.optString("msg")?.takeIf { it.isNotBlank() }
                    ?: body?.optString("message")?.takeIf { it.isNotBlank() }
                    ?: if (status in 200..299) null else "HTTP $status",
            )
        } catch (error: Exception) {
            // The endpoint contains a playback ticket. Never copy it (or an
            // exception message that may repeat it) into Logcat or the UI.
            Log.w(
                LOG_TAG,
                "Online subtitle request failed ($method): ${error.javaClass.simpleName}",
            )
            HttpJsonResult(0, null, "网络连接失败，请稍后重试")
        } finally {
            connection?.disconnect()
        }
    }

    private fun requestBytes(endpoint: String, payload: JSONObject): HttpBytesResult {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                instanceFollowRedirects = true
                connectTimeout = 15_000
                readTimeout = 60_000
                doOutput = true
                setRequestProperty("Accept", "text/vtt,application/x-subrip,text/plain,text/x-ssa,application/octet-stream")
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
            connection.outputStream.use { output ->
                output.write(payload.toString().toByteArray(Charsets.UTF_8))
            }
            val status = connection.responseCode
            val contentType = connection.contentType?.substringBefore(';')?.trim()
            if (status in 200..299) {
                HttpBytesResult(status, connection.inputStream.use { it.readBytes() }, contentType, null)
            } else {
                val text = connection.errorStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                val body = text.takeIf { it.isNotBlank() }?.let { runCatching { JSONObject(it) }.getOrNull() }
                HttpBytesResult(
                    status = status,
                    bytes = null,
                    contentType = contentType,
                    message = body?.optString("msg")?.takeIf { it.isNotBlank() }
                        ?: body?.optString("message")?.takeIf { it.isNotBlank() }
                        ?: "HTTP $status",
                )
            }
        } catch (error: Exception) {
            Log.w(LOG_TAG, "Online subtitle preview failed: ${error.javaClass.simpleName}")
            HttpBytesResult(0, null, null, "网络连接失败，请稍后重试")
        } finally {
            connection?.disconnect()
        }
    }

    private fun showSpeedPanel() {
        val currentSpeed = player.playbackParameters.speed
        val speeds = listOf(0.5f, 0.75f, 1f, 1.25f, 1.5f, 1.75f, 2f)
        val items = speeds.map { speed ->
            PanelItem(
                title = formatPlaybackSpeed(speed),
                subtitle = if (speed == 1f) "原始播放速度" else null,
                selected = kotlin.math.abs(currentSpeed - speed) < 0.01f,
                action = {
                    player.setPlaybackSpeed(speed)
                },
            )
        }
        showSelectionPanel("播放速度", items)
    }

    private fun formatPlaybackSpeed(speed: Float): String {
        val value = if (speed % 1f == 0f) {
            speed.toInt().toString()
        } else {
            String.format(Locale.US, "%.2f", speed).trimEnd('0').trimEnd('.')
        }
        return "${value}x"
    }

    private fun showQualityPanel() {
        val resource = currentResource ?: return
        val resourceId = resource.optString("id")
        val cloud = resource.optJSONObject("cloudTranscode")
        if (resourceId.isBlank() || cloud?.optBoolean("supported", false) != true) return
        activePanelKind = "quality"
        qualityCache[resourceId]?.let {
            renderQualityPanel(resource, it)
            return
        }

        sidePanelTitle.text = "画质"
        sidePanelItems.removeAllViews()
        addPanelMessage("正在获取可用画质…", "原文件始终是默认播放路径")
        if (!sidePanelOpen) openSidePanel()
        if (!qualityRequests.add(resourceId)) return

        networkExecutor.execute {
            try {
                val qualities = fetchCloudQualities(resource, cloud)
                handler.post {
                    qualityRequests.remove(resourceId)
                    qualityCache[resourceId] = qualities
                    if (
                        !didFinish &&
                        currentResource?.optString("id") == resourceId &&
                        sidePanelOpen &&
                        activePanelKind == "quality"
                    ) {
                        renderQualityPanel(resource, qualities)
                    }
                }
            } catch (_: PlaybackAuthException) {
                handler.post {
                    qualityRequests.remove(resourceId)
                    authExpired = true
                    closePlayer()
                }
            } catch (error: Throwable) {
                Log.w(LOG_TAG, "Unable to load provider qualities", error)
                handler.post {
                    qualityRequests.remove(resourceId)
                    if (
                        currentResource?.optString("id") == resourceId &&
                        sidePanelOpen &&
                        activePanelKind == "quality"
                    ) {
                        sidePanelItems.removeAllViews()
                        addPanelMessage("暂时无法获取云端画质", "仍可继续播放原文件")
                    }
                }
            }
        }
    }

    private fun fetchCloudQualities(resource: JSONObject, cloud: JSONObject): List<CloudQuality> {
        val endpoint = cloud.optString("qualitiesUrl").takeIf { it.isNotBlank() }
            ?: return emptyList()
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            connectTimeout = 12_000
            readTimeout = 15_000
            instanceFollowRedirects = true
            requestMethod = "GET"
            setRequestProperty("Accept", "application/json")
            resource.optJSONObject("direct")?.optString("userAgent")
                ?.takeIf { it.isNotBlank() }
                ?.let { setRequestProperty("User-Agent", it) }
        }
        try {
            val responseCode = connection.responseCode
            if (responseCode == 401) throw PlaybackAuthException()
            if (responseCode !in 200..299) error("HTTP $responseCode")
            val body = connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            val root = JSONObject(body)
            val data = root.optJSONObject("data") ?: root
            val defaultResolution = data.optString("default_resolution")
            val items = data.optJSONArray("items") ?: JSONArray()
            val streamUrl = cloud.optString("streamUrl")
            val resolutionParam = cloud.optString("resolutionParam", "resolution")
            return (0 until items.length()).mapNotNull { index ->
                val item = items.optJSONObject(index) ?: return@mapNotNull null
                if (!item.optBoolean("available", false)) return@mapNotNull null
                val resolution = item.optString("resolution").takeIf { it.isNotBlank() }
                    ?: return@mapNotNull null
                val url = Uri.parse(streamUrl).buildUpon()
                    .appendQueryParameter(resolutionParam, resolution)
                    .build()
                    .toString()
                val label = item.optString("label").takeIf { it.isNotBlank() } ?: resolution.uppercase(Locale.ROOT)
                CloudQuality(
                    resolution = resolution,
                    label = label,
                    url = url,
                    rank = item.optInt("rank", index),
                    format = item.optString("format").takeIf { it.isNotBlank() },
                    width = item.optInt("width", 0).takeIf { it > 0 },
                    height = item.optInt("height", 0).takeIf { it > 0 },
                    bitrate = item.optLong("bitrate", 0L).takeIf { it > 0 },
                    isDefault = resolution == defaultResolution,
                )
            }.sortedByDescending { it.rank }
        } finally {
            connection.disconnect()
        }
    }

    private fun renderQualityPanel(resource: JSONObject, qualities: List<CloudQuality>) {
        activePanelKind = "quality"
        sidePanelTitle.text = "画质"
        sidePanelItems.removeAllViews()
        val directSelected = currentQuality == null
        addPanelItemRow(
            PanelItem(
                title = "原文件",
                subtitle = "未经 CyberStream 服务器转码",
                selected = directSelected,
                enabled = !directSelected,
                action = {
                    val position = player.currentPosition.coerceAtLeast(0L)
                    val shouldPlay = player.playWhenReady
                    loadResource(
                        resource,
                        position,
                        shouldPlay = shouldPlay,
                        selectedQuality = null,
                        resetTrackSelection = false,
                    )
                },
            ),
        )
        qualities.forEach { quality ->
            val selected = currentQuality?.resolution == quality.resolution
            val details = listOfNotNull(
                if (quality.width != null && quality.height != null) "${quality.width}×${quality.height}" else null,
                quality.bitrate?.let(::formatBitrate),
                if (quality.isDefault) "云端默认" else null,
            ).joinToString(" · ").takeIf { it.isNotBlank() }
            addPanelItemRow(
                PanelItem(
                    title = quality.label,
                    subtitle = details,
                    selected = selected,
                    enabled = !selected,
                    action = {
                        val position = player.currentPosition.coerceAtLeast(0L)
                        val shouldPlay = player.playWhenReady
                        loadResource(
                            resource,
                            position,
                            shouldPlay = shouldPlay,
                            selectedQuality = quality,
                            resetTrackSelection = false,
                        )
                    },
                ),
            )
        }
        if (qualities.isEmpty()) addPanelMessage("当前没有可用的云端画质", "继续播放原文件")
        if (!sidePanelOpen) openSidePanel()
    }

    private fun showSettingsPanel() {
        val currentSpeed = formatPlaybackSpeed(player.playbackParameters.speed)
        val items = listOf(
            PanelItem("播放速度", currentSpeed, closeOnAction = false, action = ::showSpeedPanel),
            PanelItem("画面模式", displayModeLabel(), closeOnAction = false, action = ::showDisplayModePanel),
            PanelItem("字幕字号", subtitleScaleLabel(), closeOnAction = false, action = ::showSubtitleSizePanel),
            PanelItem("字幕位置", subtitlePositionLabel(), closeOnAction = false, action = ::showSubtitlePositionPanel),
            PanelItem("字幕颜色", subtitleColorLabel(), closeOnAction = false, action = ::showSubtitleColorPanel),
            PanelItem(
                "ASS 样式",
                if (overrideAssStyles) "使用播放器样式" else "跟随字幕文件",
                closeOnAction = false,
                action = ::showAssStylePanel,
            ),
            PanelItem("睡眠定时", sleepStatusLabel(), closeOnAction = false, action = ::showSleepTimerPanel),
            PanelItem(
                "定时结束动作",
                if (sleepAction == SleepAction.PAUSE) "暂停播放" else "退出播放器",
                closeOnAction = false,
                action = ::showSleepActionPanel,
            ),
            PanelItem("播放信息", resourceSummary(currentResource ?: JSONObject()), closeOnAction = false, action = ::showPlaybackInfo),
        )
        showSelectionPanel("设置", items, "settings")
    }

    private fun showDisplayModePanel() {
        showSelectionPanel(
            "画面模式",
            listOf(
                PanelItem(
                    "完整画面",
                    "保留全部画面，可能出现黑边",
                    resizeMode == AspectRatioFrameLayout.RESIZE_MODE_FIT,
                    action = { setResizeMode(AspectRatioFrameLayout.RESIZE_MODE_FIT) },
                ),
                PanelItem(
                    "宽度优先填充",
                    "铺满屏幕，边缘画面可能被裁切",
                    resizeMode == AspectRatioFrameLayout.RESIZE_MODE_ZOOM,
                    action = { setResizeMode(AspectRatioFrameLayout.RESIZE_MODE_ZOOM) },
                ),
            ),
            "display_mode",
        )
    }

    private fun setResizeMode(mode: Int) {
        resizeMode = mode
        playerView.resizeMode = mode
        getSharedPreferences("cyber_player_settings", Context.MODE_PRIVATE)
            .edit().putInt("resize_mode", mode).apply()
    }

    private fun showSubtitleSizePanel() {
        val choices = listOf(0.85f to "较小", 1f to "标准", 1.15f to "较大", 1.3f to "特大")
        showSelectionPanel(
            "字幕字号",
            choices.map { (scale, label) ->
                PanelItem(
                    label,
                    "${(scale * 100).roundToInt()}%",
                    abs(subtitleScale - scale) < 0.01f,
                    action = {
                        subtitleScale = scale
                        persistSubtitleSettings()
                        applySubtitleStyle()
                    },
                )
            },
            "subtitle_size",
        )
    }

    private fun showSubtitlePositionPanel() {
        val choices = listOf(0.07f to "靠下", 0.12f to "标准", 0.18f to "偏上")
        showSelectionPanel(
            "字幕位置",
            choices.map { (position, label) ->
                PanelItem(
                    label,
                    null,
                    abs(subtitleBottomPadding - position) < 0.015f,
                    action = {
                        subtitleBottomPadding = position
                        persistSubtitleSettings()
                        applySubtitleStyle()
                    },
                )
            },
            "subtitle_position",
        )
    }

    private fun showSubtitleColorPanel() {
        val choices = listOf(
            Color.WHITE to "白色",
            0xFFFFE082.toInt() to "暖黄",
            0xFF80DEEA.toInt() to "青色",
        )
        showSelectionPanel(
            "字幕颜色",
            choices.map { (color, label) ->
                PanelItem(
                    label,
                    null,
                    subtitleColor == color,
                    action = {
                        subtitleColor = color
                        persistSubtitleSettings()
                        applySubtitleStyle()
                    },
                )
            },
            "subtitle_color",
        )
    }

    private fun showAssStylePanel() {
        showSelectionPanel(
            "ASS 样式",
            listOf(
                PanelItem(
                    "跟随字幕文件",
                    "保留 ASS 字体、颜色与定位",
                    !overrideAssStyles,
                    action = {
                        overrideAssStyles = false
                        persistSubtitleSettings()
                        applySubtitleStyle()
                    },
                ),
                PanelItem(
                    "使用播放器样式",
                    "忽略 ASS 内嵌样式，使用上方设置",
                    overrideAssStyles,
                    action = {
                        overrideAssStyles = true
                        persistSubtitleSettings()
                        applySubtitleStyle()
                    },
                ),
            ),
            "ass_style",
        )
    }

    private fun persistSubtitleSettings() {
        getSharedPreferences("cyber_player_settings", Context.MODE_PRIVATE).edit()
            .putFloat("subtitle_scale", subtitleScale)
            .putFloat("subtitle_position", subtitleBottomPadding)
            .putInt("subtitle_color", subtitleColor)
            .putBoolean("subtitle_override_ass", overrideAssStyles)
            .apply()
    }

    private fun subtitleScaleLabel(): String = when {
        subtitleScale < 0.93f -> "较小"
        subtitleScale < 1.08f -> "标准"
        subtitleScale < 1.23f -> "较大"
        else -> "特大"
    }

    private fun subtitlePositionLabel(): String = when {
        subtitleBottomPadding < 0.095f -> "靠下"
        subtitleBottomPadding < 0.15f -> "标准"
        else -> "偏上"
    }

    private fun subtitleColorLabel(): String = when (subtitleColor) {
        0xFFFFE082.toInt() -> "暖黄"
        0xFF80DEEA.toInt() -> "青色"
        else -> "白色"
    }

    private fun showSleepTimerPanel() {
        showSelectionPanel(
            "睡眠定时",
            listOf(
                PanelItem("关闭定时", null, sleepDeadlineMs == 0L && !sleepAtEpisodeEnd, action = ::cancelSleepTimer),
                PanelItem("15 分钟", "到时${sleepActionDescription()}", false, action = { scheduleSleepTimer(15) }),
                PanelItem("30 分钟", "到时${sleepActionDescription()}", false, action = { scheduleSleepTimer(30) }),
                PanelItem("60 分钟", "到时${sleepActionDescription()}", false, action = { scheduleSleepTimer(60) }),
                PanelItem("本集结束", "片尾到达后${sleepActionDescription()}", sleepAtEpisodeEnd, action = {
                    handler.removeCallbacks(sleepTimer)
                    sleepDeadlineMs = 0L
                    sleepAtEpisodeEnd = true
                }),
            ),
            "sleep_timer",
        )
    }

    private fun showSleepActionPanel() {
        showSelectionPanel(
            "定时结束动作",
            listOf(
                PanelItem("暂停播放", "默认，不退出播放器", sleepAction == SleepAction.PAUSE, action = { sleepAction = SleepAction.PAUSE }),
                PanelItem("退出播放器", "返回影片详情页", sleepAction == SleepAction.EXIT, action = { sleepAction = SleepAction.EXIT }),
            ),
            "sleep_action",
        )
    }

    private fun scheduleSleepTimer(minutes: Int) {
        handler.removeCallbacks(sleepTimer)
        sleepAtEpisodeEnd = false
        sleepDeadlineMs = System.currentTimeMillis() + minutes * 60_000L
        handler.postDelayed(sleepTimer, minutes * 60_000L)
    }

    private fun cancelSleepTimer() {
        handler.removeCallbacks(sleepTimer)
        sleepDeadlineMs = 0L
        sleepAtEpisodeEnd = false
    }

    private fun executeSleepAction() {
        if (!::player.isInitialized) return
        if (sleepAction == SleepAction.EXIT) closePlayer() else player.pause()
    }

    private fun sleepActionDescription(): String =
        if (sleepAction == SleepAction.PAUSE) "暂停" else "退出播放器"

    private fun sleepStatusLabel(): String {
        if (sleepAtEpisodeEnd) return "本集结束"
        if (sleepDeadlineMs <= 0L) return "关闭"
        val minutes = ((sleepDeadlineMs - System.currentTimeMillis()).coerceAtLeast(0L) + 59_999L) / 60_000L
        return "约 $minutes 分钟后"
    }

    private fun showSelectionPanel(title: String, items: List<PanelItem>, kind: String = "selection") {
        activePanelKind = kind
        sidePanelTitle.text = title
        sidePanelItems.removeAllViews()
        items.forEach(::addPanelItemRow)
        openSidePanel()
    }

    private fun addPanelMessage(title: String, subtitle: String? = null) {
        val view = TextView(this).apply {
            text = listOfNotNull(title, subtitle).joinToString("\n")
            textSize = 14f
            setTextColor(0xCFFFFFFF.toInt())
            setLineSpacing(0f, 1.2f)
            setPadding(dp(16), dp(16), dp(16), dp(16))
            setBackgroundResource(R.drawable.player_panel_item_background)
        }
        sidePanelItems.addView(
            view,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ),
        )
    }

    private fun addPanelItemRow(item: PanelItem) {
        val row = layoutInflater.inflate(R.layout.player_panel_item, sidePanelItems, false)
        row.findViewById<TextView>(R.id.panel_item_title).text = item.title
        row.findViewById<TextView>(R.id.panel_item_subtitle).apply {
            text = item.subtitle
            visibility = if (item.subtitle.isNullOrBlank()) View.GONE else View.VISIBLE
        }
        row.findViewById<TextView>(R.id.panel_item_selected).visibility =
            if (item.selected) View.VISIBLE else View.GONE
        if (item.selected) row.setBackgroundResource(R.drawable.player_panel_item_selected)
        row.isEnabled = item.enabled
        row.alpha = if (item.enabled) 1f else 0.42f
        if (item.enabled) {
            row.setOnClickListener {
                item.action()
                if (item.closeOnAction) closeSidePanel()
            }
        }
        sidePanelItems.addView(row)
    }

    private fun openSidePanel() {
        if (sidePanelOpen) {
            sidePanel.visibility = View.VISIBLE
            sidePanelScrim.visibility = View.VISIBLE
            return
        }
        sidePanel.animate().cancel()
        sidePanelScrim.animate().cancel()
        sidePanelOpen = true
        playerView.hideController()
        sidePanelScrim.alpha = 0f
        sidePanelScrim.visibility = View.VISIBLE
        sidePanel.translationX = 0f
        sidePanel.translationY = 0f
        if (isPortraitLayout) {
            sidePanel.translationY = window.decorView.height.coerceAtLeast(1).toFloat()
        } else {
            sidePanel.translationX = window.decorView.width.coerceAtLeast(1).toFloat()
        }
        sidePanel.visibility = View.VISIBLE
        sidePanelScrim.animate().alpha(1f).setDuration(180L).start()
        sidePanel.post {
            if (sidePanelOpen) {
                sidePanel.animate()
                    .translationX(0f)
                    .translationY(0f)
                    .setDuration(240L)
                    .start()
            }
        }
    }

    private fun closeSidePanel() {
        if (!sidePanelOpen) return
        sidePanelOpen = false
        activePanelKind = null
        sidePanel.animate().cancel()
        sidePanelScrim.animate().cancel()
        val distance = if (isPortraitLayout) {
            sidePanel.height.takeIf { it > 0 } ?: window.decorView.height.coerceAtLeast(1)
        } else {
            sidePanel.width.takeIf { it > 0 } ?: window.decorView.width.coerceAtLeast(1)
        }
        sidePanelScrim.animate()
            .alpha(0f)
            .setDuration(160L)
            .start()
        sidePanel.animate()
            .translationX(if (isPortraitLayout) 0f else distance.toFloat())
            .translationY(if (isPortraitLayout) distance.toFloat() else 0f)
            .setDuration(210L)
            .withEndAction {
                if (!sidePanelOpen) {
                    sidePanel.visibility = View.GONE
                    sidePanelScrim.visibility = View.GONE
                    sidePanel.translationX = 0f
                    sidePanel.translationY = 0f
                    if (!isPictureInPictureActive()) {
                        playerView.setControllerShowTimeoutMs(CONTROLLER_TIMEOUT_MS)
                        playerView.showController()
                    }
                }
            }
            .start()
    }

    private fun dismissSidePanelImmediately() {
        sidePanelOpen = false
        activePanelKind = null
        sidePanel.animate().cancel()
        sidePanelScrim.animate().cancel()
        sidePanel.visibility = View.GONE
        sidePanelScrim.visibility = View.GONE
        sidePanel.translationX = 0f
        sidePanel.translationY = 0f
        sidePanelScrim.alpha = 1f
    }

    private fun allResourceObjects(): List<JSONObject> = (0 until resources.length()).mapNotNull {
        resources.optJSONObject(it)
    }

    private fun rebuildPortraitMoviePanel() {
        val sourceRow = portraitMovieSources ?: return
        val technicalContainer = portraitMovieTechnical ?: return
        if (contentKind != "movie") return
        val current = currentResource ?: return
        sourceRow.removeAllViews()
        val allResources = allResourceObjects()
        portraitMovieSourcesScroll?.visibility = if (allResources.size > 1) View.VISIBLE else View.GONE
        if (allResources.size > 1) populateMovieSourceButtons(sourceRow, allResources)

        technicalContainer.removeAllViews()
        val technical = current.optJSONObject("technical") ?: JSONObject()
        addTechnicalBadges(technicalContainer, technical.optJSONArray("badges"))
        addTechnicalSection(
            technicalContainer,
            "片源文件",
            listOfNotNull(
                technical.optString("filename").takeIf { it.isNotBlank() }?.let { "文件名" to it },
                technical.optString("storageSource").takeIf { it.isNotBlank() }?.let { "来源" to it },
                technical.optLong("sizeBytes", 0L).takeIf { it > 0 }?.let { "容量" to formatFileSize(it) },
                technical.optString("container").takeIf { it.isNotBlank() }?.let { "容器" to it.uppercase(Locale.ROOT) },
                "播放档" to (currentQuality?.label ?: "原文件"),
            ),
        )

        val video = videoInputFormat ?: selectedTrackFormat(C.TRACK_TYPE_VIDEO)
        addTechnicalSection(
            technicalContainer,
            "视频",
            listOfNotNull(
                "分辨率" to (video?.let(::videoSizeLabel)
                    ?: technical.optString("videoResolution").takeIf { it.isNotBlank() }
                    ?: "等待解析"),
                video?.let { "帧率" to frameRateLabel(it) },
                "编码" to (video?.let(::videoCodecLabel)
                    ?: technical.optString("videoCodec").takeIf { it.isNotBlank() }
                    ?: "等待解析"),
                "HDR" to (video?.let(::hdrLabel)
                    ?: technical.optString("dynamicRange").takeIf { it.isNotBlank() }
                    ?: "未标记"),
                technical.optString("bitDepth").takeIf { it.isNotBlank() }?.let { "位深" to it },
                "解码器" to decoderDescription(videoDecoderName),
            ),
        )

        val audio = audioInputFormat ?: selectedTrackFormat(C.TRACK_TYPE_AUDIO)
        addTechnicalSection(
            technicalContainer,
            "音频",
            listOfNotNull(
                "编码" to (audio?.let(::audioCodecLabel)
                    ?: technical.optString("audioCodec").takeIf { it.isNotBlank() }
                    ?: "等待解析"),
                audio?.channelCount?.takeIf { it > 0 }?.let { "声道" to channelLayout(it) }
                    ?: technical.optString("audioChannels").takeIf { it.isNotBlank() }?.let { "声道" to it },
                audio?.sampleRate?.takeIf { it > 0 }?.let { "采样率" to sampleRateLabel(it) },
                audio?.let(::bitrateLabel)?.let { "码率" to it },
                "解码器" to decoderDescription(audioDecoderName),
            ),
        )

        addTechnicalSection(
            technicalContainer,
            "设备输出",
            listOf(
                "AudioTrack" to audioOutputDescription(),
                "下混" to downmixDescription(audio),
                "重采样" to resampleDescription(audio),
                "FFmpeg" to ffmpegLibraryStatus(),
            ),
        )
    }

    private fun populateMovieSourceButtons(target: LinearLayout, sourceResources: List<JSONObject>) {
        val currentId = currentResource?.optString("id")
        sourceResources.forEachIndexed { index, resource ->
            val selected = resource.optString("id") == currentId
            val technical = resource.optJSONObject("technical")
            val firstBadge = technical?.optJSONArray("badges")?.optString(0)?.takeIf { it.isNotBlank() }
            val storage = technical?.optString("storageSource")?.takeIf { it.isNotBlank() }
            val label = listOfNotNull("片源 ${index + 1}", firstBadge ?: storage).joinToString(" · ")
            val button = Button(this).apply {
                text = label
                contentDescription = resourceChoiceTitle(resource, index)
                isAllCaps = false
                minWidth = 0
                minHeight = 0
                textSize = 13f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(if (selected) 0xFF5BE7FF.toInt() else 0xEFFFFFFF.toInt())
                setPadding(dp(15), 0, dp(15), 0)
                setBackgroundResource(
                    if (selected) R.drawable.player_season_chip_selected else R.drawable.player_season_chip,
                )
                stateListAnimator = null
                isEnabled = !selected
                setOnClickListener { switchToResource(resource, preservePosition = true) }
            }
            target.addView(
                button,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    dp(40),
                ).apply { marginEnd = dp(8) },
            )
        }
    }

    private fun addMovieSourceStrip(target: LinearLayout) {
        val title = TextView(this).apply {
            text = "切换片源"
            textSize = 14f
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setTextColor(Color.WHITE)
            setPadding(dp(4), dp(4), dp(4), dp(8))
        }
        target.addView(title)
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        populateMovieSourceButtons(row, allResourceObjects())
        val scroller = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            addView(
                row,
                ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
        target.addView(
            scroller,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(50),
            ).apply { bottomMargin = dp(10) },
        )
    }

    private fun addTechnicalBadges(target: LinearLayout, badges: JSONArray?) {
        if (badges == null || badges.length() == 0) return
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        for (index in 0 until badges.length()) {
            val value = badges.optString(index).takeIf { it.isNotBlank() } ?: continue
            row.addView(
                TextView(this).apply {
                    text = value
                    textSize = 12f
                    typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                    setTextColor(0xFF5BE7FF.toInt())
                    gravity = Gravity.CENTER
                    setPadding(dp(12), 0, dp(12), 0)
                    setBackgroundResource(R.drawable.player_quality_chip)
                },
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    dp(34),
                ).apply { marginEnd = dp(7) },
            )
        }
        val scroller = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            addView(row)
        }
        target.addView(
            scroller,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(42),
            ).apply { bottomMargin = dp(8) },
        )
    }

    private fun addTechnicalSection(
        target: LinearLayout,
        title: String,
        rows: List<Pair<String, String>>,
    ) {
        if (rows.isEmpty()) return
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(14), dp(16), dp(12))
            setBackgroundResource(R.drawable.player_technical_card)
        }
        card.addView(
            TextView(this).apply {
                text = title
                textSize = 15f
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setTextColor(Color.WHITE)
                setPadding(0, 0, 0, dp(8))
            },
        )
        rows.forEach { (label, value) ->
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.TOP
                setPadding(0, dp(4), 0, dp(4))
            }
            row.addView(
                TextView(this).apply {
                    text = label
                    textSize = 12f
                    setTextColor(0x80FFFFFF.toInt())
                },
                LinearLayout.LayoutParams(dp(76), ViewGroup.LayoutParams.WRAP_CONTENT),
            )
            row.addView(
                TextView(this).apply {
                    text = value
                    textSize = 13f
                    setTextColor(0xEFFFFFFF.toInt())
                    setTextIsSelectable(true)
                },
                LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f),
            )
            card.addView(row)
        }
        target.addView(
            card,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply { bottomMargin = dp(10) },
        )
    }

    private fun formatFileSize(bytes: Long): String {
        if (bytes < 1024L) return "$bytes B"
        val units = arrayOf("KB", "MB", "GB", "TB")
        var value = bytes.toDouble()
        var unit = -1
        do {
            value /= 1024.0
            unit += 1
        } while (value >= 1024.0 && unit < units.lastIndex)
        return String.format(Locale.US, if (value >= 100) "%.0f %s" else "%.2f %s", value, units[unit])
    }

    private fun formatBitrate(bitrate: Long): String = if (bitrate >= 1_000_000L) {
        String.format(Locale.US, "%.2f Mbps", bitrate / 1_000_000.0)
    } else {
        "${bitrate / 1000L} kbps"
    }

    private fun selectedTrackFormat(trackType: Int): Format? {
        player.currentTracks.groups.forEach { group ->
            if (group.type != trackType) return@forEach
            for (index in 0 until group.length) {
                if (group.isTrackSelected(index)) return group.getTrackFormat(index)
            }
        }
        return null
    }

    private fun showPlaybackInfo() {
        activePanelKind = "playback_info"
        sidePanelTitle.text = "播放信息"
        sidePanelItems.removeAllViews()
        if (contentKind == "movie" && resources.length() > 1) {
            addMovieSourceStrip(sidePanelItems)
        }
        val density = applicationContext.resources.displayMetrics.density
        val padding = (16 * density).toInt()
        val info = TextView(this).apply {
            text = buildPlaybackInfo()
            typeface = Typeface.MONOSPACE
            textSize = 13f
            setTextColor(0xD9FFFFFF.toInt())
            setLineSpacing(0f, 1.2f)
            setPadding(padding, padding, padding, padding)
            setTextIsSelectable(true)
            setBackgroundResource(R.drawable.player_panel_item_background)
        }
        sidePanelItems.addView(
            info,
            LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ),
        )
        openSidePanel()
    }

    private fun buildPlaybackInfo(): String {
        val video = videoInputFormat ?: selectedTrackFormat(C.TRACK_TYPE_VIDEO)
        val audio = audioInputFormat ?: selectedTrackFormat(C.TRACK_TYPE_AUDIO)
        val technical = currentResource?.optJSONObject("technical")
        return buildString {
            appendLine("当前片源")
            technical?.optString("filename")?.takeIf { it.isNotBlank() }?.let { appendLine("  文件：$it") }
            technical?.optString("storageSource")?.takeIf { it.isNotBlank() }?.let { appendLine("  来源：$it") }
            technical?.optLong("sizeBytes", 0L)?.takeIf { it > 0 }?.let { appendLine("  容量：${formatFileSize(it)}") }
            technical?.optString("container")?.takeIf { it.isNotBlank() }?.let { appendLine("  容器：${it.uppercase(Locale.ROOT)}") }
            appendLine("  播放档：${currentQuality?.label ?: "原文件"}")
            appendLine()
            appendLine("视频")
            if (video == null) {
                appendLine("  分辨率：${technical?.optString("videoResolution")?.takeIf { it.isNotBlank() } ?: "等待解析"}")
                appendLine("  编码：${technical?.optString("videoCodec")?.takeIf { it.isNotBlank() } ?: "等待解析"}")
                appendLine("  HDR：${technical?.optString("dynamicRange")?.takeIf { it.isNotBlank() } ?: "未标记"}")
            } else {
                appendLine("  编码：${videoCodecLabel(video)}")
                appendLine("  画面：${videoSizeLabel(video)} · ${frameRateLabel(video)}")
                appendLine("  HDR：${hdrLabel(video)}")
            }
            technical?.optString("bitDepth")?.takeIf { it.isNotBlank() }?.let { appendLine("  位深：$it") }
            appendLine("  解码器：${decoderDescription(videoDecoderName)}")
            appendLine()
            appendLine("音频")
            if (audio == null) {
                appendLine("  编码：${technical?.optString("audioCodec")?.takeIf { it.isNotBlank() } ?: "等待解析"}")
                technical?.optString("audioChannels")?.takeIf { it.isNotBlank() }?.let { appendLine("  声道：$it") }
            } else {
                appendLine("  编码：${audioCodecLabel(audio)}")
                appendLine("  输入：${channelLayout(audio.channelCount)} · ${sampleRateLabel(audio.sampleRate)} · ${bitrateLabel(audio) ?: "码率未知"}")
                audio.language?.takeIf { it.isNotBlank() }?.let { appendLine("  语言：$it") }
            }
            appendLine("  解码器：${decoderDescription(audioDecoderName)}")
            appendLine("  输出：${audioOutputDescription()}")
            appendLine("  下混：${downmixDescription(audio)}")
            appendLine("  重采样：${resampleDescription(audio)}")
            appendLine("  FFmpeg：${ffmpegLibraryStatus()}")
            appendLine()
            appendLine("输出策略")
            appendLine("  响度处理：关闭")
            appendLine("  PCM：设备支持时使用 32-bit float")
            append("  Atmos：系统支持时保留；FFmpeg 回退时输出多声道 PCM")
        }
    }

    private fun decoderDescription(name: String?): String {
        if (name.isNullOrBlank()) return "等待初始化"
        val lower = name.lowercase(Locale.ROOT)
        return when {
            "ffmpeg" in lower -> "FFmpeg 软件解码（$name）"
            lower.startsWith("omx.google.") || lower.startsWith("c2.android.") || lower.startsWith("c2.google.") ->
                "系统软件解码（$name）"
            else -> "MediaCodec 厂商解码（$name）"
        }
    }

    private fun ffmpegLibraryStatus(): String = try {
        val library = Class.forName("androidx.media3.decoder.ffmpeg.FfmpegLibrary")
        val available = library.getMethod("isAvailable").invoke(null) as? Boolean == true
        if (!available) {
            "已集成，但本机动态库不可用"
        } else {
            val version = library.getMethod("getVersion").invoke(null)?.toString()?.takeIf { it.isNotBlank() }
            if (version == null) "可用" else "可用（$version）"
        }
    } catch (_: Throwable) {
        "未集成"
    }

    private fun audioOutputDescription(): String {
        val encoding = audioOutputEncoding ?: return "等待 AudioTrack 初始化"
        val channels = audioOutputChannelCount?.let(::channelLayout) ?: "声道未知"
        val sampleRate = audioOutputSampleRate?.let(::sampleRateLabel) ?: "采样率未知"
        val offload = if (audioOutputOffload) " · 系统 offload" else ""
        return "${pcmEncodingLabel(encoding)} · $channels · $sampleRate$offload"
    }

    private fun downmixDescription(audio: Format?): String {
        val inputChannels = audio?.channelCount?.takeIf { it > 0 } ?: return "等待输入格式"
        val outputChannels = audioOutputChannelCount ?: return "等待系统输出格式"
        return if (outputChannels < inputChannels) {
            "${channelLayout(inputChannels)} → ${channelLayout(outputChannels)}（设备兼容下混）"
        } else {
            "未检测到"
        }
    }

    private fun resampleDescription(audio: Format?): String {
        val inputRate = audio?.sampleRate?.takeIf { it > 0 } ?: return "等待输入格式"
        val outputRate = audioOutputSampleRate ?: return "等待系统输出格式"
        return if (inputRate == outputRate) {
            "未检测到（${sampleRateLabel(inputRate)}）"
        } else {
            "${sampleRateLabel(inputRate)} → ${sampleRateLabel(outputRate)}（系统输出）"
        }
    }

    private fun audioCodecLabel(format: Format): String = when (format.sampleMimeType) {
        MimeTypes.AUDIO_AAC -> "AAC"
        MimeTypes.AUDIO_AC3 -> "Dolby Digital (AC-3)"
        MimeTypes.AUDIO_E_AC3 -> "Dolby Digital Plus (E-AC-3)"
        MimeTypes.AUDIO_E_AC3_JOC -> "Dolby Digital Plus / Atmos (JOC)"
        MimeTypes.AUDIO_TRUEHD -> "Dolby TrueHD"
        MimeTypes.AUDIO_DTS -> "DTS"
        MimeTypes.AUDIO_DTS_HD -> "DTS-HD"
        MimeTypes.AUDIO_FLAC -> "FLAC"
        MimeTypes.AUDIO_OPUS -> "Opus"
        MimeTypes.AUDIO_VORBIS -> "Vorbis"
        MimeTypes.AUDIO_MPEG -> "MP3"
        else -> format.codecs?.takeIf { it.isNotBlank() }
            ?: format.sampleMimeType?.takeIf { it.isNotBlank() }
            ?: "未知"
    }

    private fun videoCodecLabel(format: Format): String = when (format.sampleMimeType) {
        MimeTypes.VIDEO_DOLBY_VISION -> "Dolby Vision"
        MimeTypes.VIDEO_H265 -> "HEVC / H.265"
        MimeTypes.VIDEO_H264 -> "AVC / H.264"
        MimeTypes.VIDEO_AV1 -> "AV1"
        MimeTypes.VIDEO_VP9 -> "VP9"
        MimeTypes.VIDEO_VP8 -> "VP8"
        else -> format.codecs?.takeIf { it.isNotBlank() }
            ?: format.sampleMimeType?.takeIf { it.isNotBlank() }
            ?: "未知"
    }

    private fun hdrLabel(format: Format): String {
        val codecs = format.codecs.orEmpty().lowercase(Locale.ROOT)
        if (
            format.sampleMimeType == MimeTypes.VIDEO_DOLBY_VISION ||
            codecs.startsWith("dvhe") ||
            codecs.startsWith("dvh1") ||
            codecs.startsWith("dvav") ||
            codecs.startsWith("dva1")
        ) {
            return "Dolby Vision（设备支持时原生输出）"
        }
        return when (format.colorInfo?.colorTransfer) {
            C.COLOR_TRANSFER_ST2084 -> "HDR10 / PQ"
            C.COLOR_TRANSFER_HLG -> "HLG"
            else -> "SDR / 未标记"
        }
    }

    private fun videoSizeLabel(format: Format): String =
        if (format.width > 0 && format.height > 0) "${format.width}×${format.height}" else "分辨率未知"

    private fun frameRateLabel(format: Format): String =
        if (format.frameRate > 0f) String.format(Locale.US, "%.3g fps", format.frameRate) else "帧率未知"

    private fun channelLayout(channelCount: Int): String = when (channelCount) {
        1 -> "1.0"
        2 -> "2.0"
        3 -> "2.1 / 3ch"
        4 -> "4.0"
        5 -> "5.0"
        6 -> "5.1"
        7 -> "6.1"
        8 -> "7.1"
        in 9..Int.MAX_VALUE -> "${channelCount}ch"
        else -> "声道未知"
    }

    private fun sampleRateLabel(sampleRate: Int): String {
        if (sampleRate <= 0) return "采样率未知"
        return if (sampleRate % 1000 == 0) {
            "${sampleRate / 1000} kHz"
        } else {
            String.format(Locale.US, "%.1f kHz", sampleRate / 1000.0)
        }
    }

    private fun bitrateLabel(format: Format): String? {
        val bitrate = format.averageBitrate.takeIf { it > 0 }
            ?: format.peakBitrate.takeIf { it > 0 }
            ?: return null
        return if (bitrate >= 1_000_000) {
            String.format(Locale.US, "%.2f Mbps", bitrate / 1_000_000.0)
        } else {
            "${bitrate / 1000} kbps"
        }
    }

    private fun pcmEncodingLabel(encoding: Int): String = when (encoding) {
        C.ENCODING_PCM_8BIT -> "PCM 8-bit"
        C.ENCODING_PCM_16BIT -> "PCM 16-bit"
        C.ENCODING_PCM_24BIT -> "PCM 24-bit"
        C.ENCODING_PCM_32BIT -> "PCM 32-bit"
        C.ENCODING_PCM_FLOAT -> "PCM 32-bit float"
        else -> "压缩直通 / encoding=$encoding"
    }

    // Package-visible runtime probes used only by instrumentation tests. They
    // deliberately expose codec metadata, never media URLs or playback tickets.
    fun audioDecoderNameForTesting(): String? = audioDecoderName

    fun audioMimeTypeForTesting(): String? = audioInputFormat?.sampleMimeType

    fun lastPlaybackErrorForTesting(): String? = lastError

    fun playerForTesting(): ExoPlayer = player

    fun mediaSessionForTesting(): MediaSession = mediaSession

    fun activePlayerViewForTesting(): PlayerView = playerView

    fun gestureSurfaceForTesting(): View = gestureSurface

    fun externalSubtitleViewForTesting(): SubtitleView = externalSubtitleView

    fun prepareCountForTesting(): Int = prepareCount

    fun initialPlaybackStartedForTesting(): Boolean = initialPlaybackStarted

    fun cellularWarningVisibleForTesting(): Boolean = cellularWarningView?.isShown == true

    fun cellularArtworkUrlForTesting(): String? = cellularArtworkUrl

    fun contentKindForTesting(): String = contentKind

    fun currentResourceIdForTesting(): String? = currentResource?.optString("id")

    fun currentTechnicalFilenameForTesting(): String? =
        currentResource?.optJSONObject("technical")?.optString("filename")

    fun resizeModeForTesting(): Int = resizeMode

    fun toggleResizeModeForTesting() = toggleResizeMode()

    fun subtitleBottomPaddingForTesting(): Float = subtitleBottomPadding

    fun normalizeBoundSubtitlesForTesting(
        rawItems: JSONArray,
        config: JSONObject,
        selectedSubtitleId: String,
    ): JSONArray = normalizeBoundSubtitles(rawItems, config, selectedSubtitleId)

    fun onlineSubtitleFailureMessageForTesting(status: Int, message: String?): String =
        onlineSubtitleFailureMessage(status, message, "字幕操作失败")

    fun addOnlineSubtitleCandidateForTesting(config: JSONObject, candidate: JSONObject): View {
        val progress = ProgressBar(this)
        val status = TextView(this)
        addOnlineSubtitleCandidate(
            config = config,
            resourceId = currentResource?.optString("id").orEmpty(),
            keyword = "",
            candidate = candidate,
            progress = progress,
            status = status,
        )
        return sidePanelItems.getChildAt(sidePanelItems.childCount - 1)
    }

    fun onlineSubtitleBindingForTesting(): Boolean = onlineSubtitleBinding

    fun playerErrorVisibleForTesting(): Boolean =
        ::playerErrorOverlay.isInitialized && playerErrorOverlay.visibility == View.VISIBLE

    fun handlePlaybackEndedForTesting() = handlePlaybackEnded()

    fun switchResourceForTesting(resourceId: String, preservePosition: Boolean) {
        findResource(resourceId)?.let { switchToResource(it, preservePosition) }
    }

    fun qualityButtonVisibilityForTesting(): Int = qualityButton.visibility

    fun injectQualityForTesting(
        resourceId: String,
        resolution: String,
        label: String,
        url: String,
    ) {
        qualityCache[resourceId] = listOf(
            CloudQuality(
                resolution = resolution,
                label = label,
                url = url,
                rank = 1,
                format = null,
                width = null,
                height = null,
                bitrate = null,
                isDefault = false,
            ),
        )
    }

    fun currentQualityResolutionForTesting(): String? = currentQuality?.resolution

    private fun emitProgress(state: String) {
        val resourceId = currentResource?.optString("id") ?: return
        // Android may finish a PiP task before all lifecycle callbacks run.
        // Keep Activity's result pre-armed with the latest safe playback state
        // so platform-driven finishes do not degrade to RESULT_CANCELED.
        preparePlaybackResult()
        CyberPlayerPlugin.emitProgress(
            sessionId,
            resourceId,
            player.currentPosition.coerceAtLeast(0L),
            player.duration.takeIf { it > 0 } ?: 0L,
            state,
        )
    }

    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && player.isPlaying && !isInPictureInPictureMode) {
            hasEnteredPictureInPicture = enterPictureInPictureMode(
                PictureInPictureParams.Builder().setAspectRatio(Rational(16, 9)).build(),
            )
        }
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onPictureInPictureModeChanged(isInPictureInPictureMode: Boolean) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        if (isInPictureInPictureMode) {
            hasEnteredPictureInPicture = true
            pipExitCheckPending = false
            handler.removeCallbacks(completeDismissedPictureInPicture)
            dismissSidePanelImmediately()
            topActions.visibility = View.GONE
        } else {
            syncTopActionsVisibility()
            if (hasEnteredPictureInPicture) {
                scheduleDismissedPictureInPictureCheck()
            }
        }
    }

    private fun scheduleDismissedPictureInPictureCheck() {
        if (!hasEnteredPictureInPicture || isInPictureInPictureMode || didFinish) return
        pipExitCheckPending = true
        handler.removeCallbacks(completeDismissedPictureInPicture)
        handler.post(completeDismissedPictureInPicture)
    }

    /** Captures playback state for both an explicit close and a PiP close. */
    private fun preparePlaybackResult() {
        if (!::player.isInitialized || !::sessionId.isInitialized) return
        setResult(
            Activity.RESULT_OK,
            Intent()
                .putExtra(RESULT_SESSION_ID, sessionId)
                .putExtra(RESULT_RESOURCE_ID, currentResource?.optString("id"))
                .putExtra(RESULT_POSITION_MS, player.currentPosition.coerceAtLeast(0L))
                .putExtra(RESULT_DURATION_MS, player.duration.takeIf { it > 0 } ?: 0L)
                .putExtra(RESULT_ENDED, reachedEnd)
                .putExtra(RESULT_AUTH_EXPIRED, authExpired)
                .putExtra(RESULT_ERROR, lastError),
        )
    }

    private fun completePlaybackResult() {
        if (didFinish) return
        didFinish = true
        emitProgress(if (reachedEnd) "ended" else "paused")
        preparePlaybackResult()
    }

    private fun closePlayer() {
        completePlaybackResult()
        finish()
    }

    override fun onStop() {
        // A normal PiP entry remains in PiP here. A system PiP close changes
        // out of PiP but (on current Android) does not set isFinishing; defer
        // one loop turn so an expand-to-fullscreen can cancel the close.
        scheduleDismissedPictureInPictureCheck()

        // Explicit Back and other normal finishing paths still complete here.
        if (isFinishing && !didFinish && ::player.isInitialized && ::sessionId.isInitialized) {
            completePlaybackResult()
        }
        super.onStop()
    }

    override fun onDestroy() {
        // onStop normally handles a finish. Keep this idempotent fallback for
        // platform paths that destroy a finishing Activity directly.
        if (isFinishing && !didFinish && ::player.isInitialized && ::sessionId.isInitialized) {
            completePlaybackResult()
        }
        handler.removeCallbacksAndMessages(null)
        networkExecutor.shutdownNow()
        previewSubtitleFile?.delete()
        previewSubtitleFile = null
        if (::mediaSession.isInitialized) mediaSession.release()
        if (::player.isInitialized) player.release()
        super.onDestroy()
    }
}
