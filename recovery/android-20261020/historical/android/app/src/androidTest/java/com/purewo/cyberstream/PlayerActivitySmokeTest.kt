package com.purewo.cyberstream

import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.os.Looper
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.GridLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import androidx.media3.ui.SubtitleView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

@UnstableApi
@RunWith(AndroidJUnit4::class)
class PlayerActivitySmokeTest {
    companion object {
        private const val HLS_URL =
            "https://storage.googleapis.com/shaka-demo-assets/angel-one-hls/hls.m3u8"
        private const val PLAYER_PREFERENCES = "cyber_player_settings"
        private const val PREF_ALLOW_CELLULAR_PLAYBACK = "allow_cellular_playback"
    }

    @Test
    fun launchEntersLandscapeFullscreenByDefault() {
        val activity = launch(
            session(
                "movie",
                JSONArray().put(resource("movie-main", "Movie source", "Movie.REMUX.mkv")),
                "movie-main",
            ),
        )
        try {
            waitForOrientation(activity, Configuration.ORIENTATION_LANDSCAPE)
            assertEquals(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE, activity.requestedOrientation)
            waitUntilReady(activity)
        } finally {
            finish(activity)
        }
    }

    @Test
    fun cellularPlaybackWaitsForThisTimeConsentWithoutPersisting() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val preferences = instrumentation.targetContext.getSharedPreferences(
            PLAYER_PREFERENCES,
            Context.MODE_PRIVATE,
        )
        preferences.edit().remove(PREF_ALLOW_CELLULAR_PLAYBACK).commit()
        val testSession = session(
            "movie",
            JSONArray().put(resource("cellular-once", "Movie source", "Movie.REMUX.mkv")),
            "cellular-once",
        )
        val posterUrl = "https://picsum.photos/600/900"
        testSession.getJSONObject("movie").put("posterUrl", posterUrl)
        val activity = launch(testSession, forceCellular = true)
        try {
            waitForOrientation(activity, Configuration.ORIENTATION_LANDSCAPE)
            assertTrue(activity.cellularWarningVisibleForTesting())
            assertEquals(posterUrl, activity.cellularArtworkUrlForTesting())
            assertFalse(activity.initialPlaybackStartedForTesting())
            assertEquals(0, activity.prepareCountForTesting())
            assertTrue(
                activity.findViewById<TextView>(R.id.cellular_warning_message)
                    .text
                    .toString()
                    .contains("74.51 GB"),
            )
            instrumentation.runOnMainSync {
                activity.findViewById<View>(R.id.cellular_warning_allow_once).performClick()
            }
            waitUntilReady(activity)
            assertFalse(preferences.getBoolean(PREF_ALLOW_CELLULAR_PLAYBACK, false))
        } finally {
            finish(activity)
            preferences.edit().remove(PREF_ALLOW_CELLULAR_PLAYBACK).commit()
        }
    }

    @Test
    fun cellularAlwaysAllowPersistsOnThisDeviceAndSkipsTheNextPrompt() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val preferences = instrumentation.targetContext.getSharedPreferences(
            PLAYER_PREFERENCES,
            Context.MODE_PRIVATE,
        )
        preferences.edit().remove(PREF_ALLOW_CELLULAR_PLAYBACK).commit()
        val testSession = session(
            "movie",
            JSONArray().put(resource("cellular-always", "Movie source", "Movie.REMUX.mkv")),
            "cellular-always",
        )
        var firstActivity: PlayerActivity? = null
        var secondActivity: PlayerActivity? = null
        try {
            val first = launch(testSession, forceCellular = true)
            firstActivity = first
            waitForOrientation(first, Configuration.ORIENTATION_LANDSCAPE)
            assertTrue(first.cellularWarningVisibleForTesting())
            instrumentation.runOnMainSync {
                first.findViewById<View>(R.id.cellular_warning_allow_always).performClick()
            }
            waitUntilReady(first)
            assertTrue(preferences.getBoolean(PREF_ALLOW_CELLULAR_PLAYBACK, false))
            finish(first)
            firstActivity = null

            val second = launch(testSession, forceCellular = true)
            secondActivity = second
            waitForOrientation(second, Configuration.ORIENTATION_LANDSCAPE)
            assertFalse(second.cellularWarningVisibleForTesting())
            waitUntilReady(second)
        } finally {
            firstActivity?.let(::finish)
            secondActivity?.let(::finish)
            preferences.edit().remove(PREF_ALLOW_CELLULAR_PLAYBACK).commit()
        }
    }

    @Test
    fun onlineSubtitleEntryRemainsAvailableWhenTheFileHasNoLocalSubtitles() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val testResource = resource(
            id = "online-subtitle",
            title = "Movie source",
            filename = "Movie.REMUX.mkv",
        ).put(
            "onlineSubtitles",
            JSONObject()
                // Keep this UI/mobile test deterministic and offline. The
                // real endpoint contract is covered by normalization below.
                .put("searchUrl", "")
                .put("downloadUrl", "https://example.invalid/download?ticket=test")
                .put("bindUrl", "https://example.invalid/bind?ticket=test")
                .put("apiBaseUrl", "https://example.invalid/api")
                .put("defaultKeyword", "Media3 fixture")
                .put("providers", JSONArray().put("subhd").put("srtku")),
        )
        val activity = launch(
            session(
                "movie",
                JSONArray().put(testResource),
                "online-subtitle",
            ),
        )
        try {
            waitForOrientation(activity, Configuration.ORIENTATION_LANDSCAPE)
            waitUntilReady(activity)
            forcePortrait(activity)
            val subtitleButton = activity.findViewById<Button>(R.id.subtitle_button)
            assertTrue("Online subtitle entry should keep the subtitle button enabled", subtitleButton.isEnabled)
            instrumentation.runOnMainSync { subtitleButton.performClick() }
            instrumentation.waitForIdleSync()
            val panel = activity.findViewById<ViewGroup>(R.id.side_panel_items)
            assertTrue(
                "Subtitle panel should expose online search on phones/tablets",
                collectText(panel).any { it.contains("在线搜索字幕") },
            )
            instrumentation.runOnMainSync {
                panel.getChildAt(panel.childCount - 1).performClick()
            }
            instrumentation.waitForIdleSync()
            val query = activity.findViewById<EditText>(R.id.online_subtitle_query)
            val search = activity.findViewById<Button>(R.id.online_subtitle_search)
            val sidePanel = activity.findViewById<View>(R.id.side_panel)
            assertEquals("Media3 fixture", query.text.toString())
            assertEquals("手机竖屏字幕面板应占满可用宽度", activity.window.decorView.width, sidePanel.width)
            assertTrue(
                "手机端搜索按钮触控高度不能小于 48dp",
                search.height >= (48 * activity.resources.displayMetrics.density).toInt(),
            )
            assertTrue(
                collectText(activity.findViewById(R.id.side_panel_items))
                    .any { it.contains("在线字幕搜索地址不可用") },
            )
        } finally {
            finish(activity)
        }
    }

    @Test
    fun onlineSubtitleCandidateClicksPreviewAndKeepsBindingOnASeparateButton() {
        val testResource = resource(
            id = "online-candidate-actions",
            title = "Movie source",
            filename = "Movie.REMUX.mkv",
        )
        val activity = launch(
            session(
                "movie",
                JSONArray().put(testResource),
                "online-candidate-actions",
            ),
        )
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            val config = JSONObject()
                // Empty endpoints keep this interaction test offline. Clicking
                // the row must take the preview path and must not bind.
                .put("downloadUrl", "")
                .put("bindUrl", "")
            val candidate = JSONObject()
                .put("candidate_id", "subhd:fixture")
                .put("title", "Fixture Chinese subtitle")
                .put("format_normalized", "srt")
                .put(
                    "downloads",
                    JSONArray().put(JSONObject().put("download_index", 0)),
                )
            val row = AtomicReference<View>()
            instrumentation.runOnMainSync {
                row.set(activity.addOnlineSubtitleCandidateForTesting(config, candidate))
            }
            val candidateRow = row.get()
            val preview = candidateRow.findViewById<Button>(R.id.online_subtitle_candidate_preview)
            val bind = candidateRow.findViewById<Button>(R.id.online_subtitle_candidate_bind)
            assertTrue(candidateRow.hasOnClickListeners())
            assertEquals("预览", preview.text.toString())
            assertEquals("绑定", bind.text.toString())
            assertTrue(bind.hasOnClickListeners())

            instrumentation.runOnMainSync { candidateRow.performClick() }
            instrumentation.waitForIdleSync()
            assertFalse("Clicking a candidate must never enter the bind path", activity.onlineSubtitleBindingForTesting())
        } finally {
            finish(activity)
        }
    }

    @Test
    fun boundOnlineSubtitleUsesTheMimeTypeOfItsPlayableUrlAndKeepsTicket() {
        val activity = launch(
            session(
                "movie",
                JSONArray().put(resource("online-normalize", "Movie source", "Movie.REMUX.mkv")),
                "online-normalize",
            ),
        )
        try {
            waitUntilReady(activity)
            val rawItems = JSONArray()
                .put(
                    JSONObject()
                        .put("id", "sub-online-1")
                        .put("source", "online_bound")
                        .put("display_name", "真实接口 ASS 候选")
                        .put("format", "ass")
                        .put("mime_type", "text/x-ssa; charset=utf-8")
                        .put("url", "/api/v1/resources/resource/stream?subtitle_id=sub-online-1")
                        .put("language", JSONObject().put("label", "简体中文"))
                        .put(
                            "web_player",
                            JSONObject()
                                .put("supported", true)
                                .put("native_supported", false)
                                .put("format", "vtt")
                                .put(
                                    "url",
                                    "/api/v1/resources/resource/stream?subtitle_id=sub-online-1&format=vtt",
                                ),
                        ),
                )
                .put(
                    JSONObject()
                        .put("id", "bitmap-subtitle")
                        .put("format", "sup")
                        .put("url", "/api/v1/resources/resource/stream?subtitle_id=bitmap-subtitle"),
                )
            val config = JSONObject()
                .put("apiBaseUrl", "https://example.invalid/api")
                .put("bindUrl", "https://example.invalid/api/v1/bind?ticket=secret-ticket")

            val normalized = activity.normalizeBoundSubtitlesForTesting(
                rawItems,
                config,
                "sub-online-1",
            )
            assertEquals("位图字幕不应交给 Media3 文本字幕解析器", 1, normalized.length())
            val subtitle = normalized.getJSONObject(0)
            assertEquals("vtt", subtitle.getString("format"))
            assertEquals("text/vtt", subtitle.getString("mimeType"))
            assertEquals("简体中文", subtitle.getString("language"))
            assertTrue(subtitle.getBoolean("isDefault"))
            assertEquals(
                "https://example.invalid/api/v1/resources/resource/stream?subtitle_id=sub-online-1&format=vtt&ticket=secret-ticket",
                subtitle.getString("url"),
            )
            assertTrue(
                activity.onlineSubtitleFailureMessageForTesting(
                    502,
                    "SubHD download failed: unknown_captcha",
                ).contains("验证码"),
            )
        } finally {
            finish(activity)
        }
    }

    @Test
    fun movieUsesModernControlsAndKeepsSubtitlesOutsideTheCropLayer() {
        val resource = resource(
            id = "movie-main",
            title = "Movie source",
            filename = "Movie.REMUX.mkv",
            subtitles = JSONArray().put(
                JSONObject()
                    .put("id", "public-vtt")
                    .put("label", "English")
                    .put("language", "en")
                    .put("format", "vtt")
                    .put("mimeType", "text/vtt")
                    .put("isDefault", true)
                    .put(
                        "url",
                        "https://raw.githubusercontent.com/shaka-project/shaka-player/main/test/test/assets/text-clip.vtt",
                    ),
            ),
        )
        val activity = launch(session("movie", JSONArray().put(resource), "movie-main"))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            instrumentation.runOnMainSync {
                activity.activePlayerViewForTesting().showController()
            }

            val subtitleButton = activity.findViewById<Button>(R.id.subtitle_button)
            val audioButton = activity.findViewById<Button>(R.id.audio_button)
            val settingsButton = activity.findViewById<View>(R.id.settings_button)
            val qualityButton = activity.findViewById<Button>(R.id.quality_button)
            val sourceButton = activity.findViewById<Button>(R.id.source_button)
            assertNotNull(subtitleButton)
            assertTrue(subtitleButton.isEnabled)
            assertNotNull(audioButton)
            assertTrue(audioButton.isEnabled)
            assertNotNull(settingsButton)
            assertEquals("普通原文件不应常驻显示画质入口", View.GONE, qualityButton.visibility)
            assertEquals("电影不显示剧集入口", View.GONE, sourceButton.visibility)

            val playerView = activity.activePlayerViewForTesting()
            val externalSubtitles = activity.externalSubtitleViewForTesting()
            assertNull(
                "独立字幕层不能成为可裁切 PlayerView 的子节点",
                playerView.findViewById<SubtitleView>(R.id.external_subtitle_view),
            )
            assertTrue(activity.subtitleBottomPaddingForTesting() >= 0.05f)

            instrumentation.runOnMainSync { settingsButton.performClick() }
            assertEquals(
                View.VISIBLE,
                waitForVisibility(instrumentation, activity.findViewById(R.id.side_panel), View.VISIBLE),
            )
            assertEquals("设置", activity.findViewById<android.widget.TextView>(R.id.side_panel_title).text.toString())
            instrumentation.runOnMainSync { activity.findViewById<View>(R.id.side_panel_close).performClick() }
            waitForVisibility(instrumentation, activity.findViewById(R.id.side_panel), View.GONE)

            val beforeMode = activity.resizeModeForTesting()
            instrumentation.runOnMainSync { dispatchDoubleTap(activity.gestureSurfaceForTesting()) }
            assertEquals(
                if (beforeMode == AspectRatioFrameLayout.RESIZE_MODE_FIT) {
                    AspectRatioFrameLayout.RESIZE_MODE_ZOOM
                } else {
                    AspectRatioFrameLayout.RESIZE_MODE_FIT
                },
                activity.resizeModeForTesting(),
            )
            assertSame(externalSubtitles, activity.externalSubtitleViewForTesting())
        } finally {
            finish(activity)
        }
    }

    @Test
    fun rotationKeepsTheSamePlayerPositionAndPrepareCount() {
        val activity = launch(
            session(
                "series",
                JSONArray().put(resource("s1e1", "Episode 1", "S01E01.mkv", season = 1, episode = "1")),
                "s1e1",
                seasons = JSONArray().put(
                    JSONObject()
                        .put("season", 1)
                        .put("displayTitle", "第 1 季")
                        .put("resourceIds", JSONArray().put("s1e1")),
                ),
            ),
        )
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            val playerBefore = activity.playerForTesting()
            val viewBefore = activity.activePlayerViewForTesting()
            val prepareBefore = activity.prepareCountForTesting()
            val orientationBefore = activity.resources.configuration.orientation
            instrumentation.runOnMainSync {
                playerBefore.pause()
                playerBefore.seekTo(12_000L)
                activity.requestedOrientation = if (orientationBefore == Configuration.ORIENTATION_PORTRAIT) {
                    ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                } else {
                    ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                }
            }
            waitForOrientationChange(activity, orientationBefore)
            instrumentation.waitForIdleSync()

            assertSame("旋转不能替换 ExoPlayer", playerBefore, activity.playerForTesting())
            assertNotSame("旋转应只替换目标 PlayerView", viewBefore, activity.activePlayerViewForTesting())
            assertEquals("旋转不能重新 prepare", prepareBefore, activity.prepareCountForTesting())
            assertTrue("旋转后播放位置不能回到开头", playerPosition(activity) >= 10_500L)
        } finally {
            finish(activity)
        }
    }

    @Test
    fun seriesAutoAdvancesByEpisodeButStopsAtTheFinalEpisode() {
        val resources = JSONArray()
            .put(resource("s1e1-a", "Episode 1 A", "S01E01.A.mkv", 1, "1"))
            .put(resource("s1e1-b", "Episode 1 B", "S01E01.B.mkv", 1, "1"))
            .put(resource("s1e2", "Episode 2", "S01E02.mkv", 1, "2"))
            .put(resource("s2e1", "Season 2 Episode 1", "S02E01.mkv", 2, "1"))
        val seasons = JSONArray()
            .put(
                JSONObject()
                    .put("season", 1)
                    .put("displayTitle", "第 1 季")
                    .put("resourceIds", JSONArray().put("s1e1-a").put("s1e1-b").put("s1e2")),
            )
            .put(
                JSONObject()
                    .put("season", 2)
                    .put("displayTitle", "第 2 季")
                    .put("resourceIds", JSONArray().put("s2e1")),
            )
        val activity = launch(session("series", resources, "s1e1-b", seasons))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            val firstPrepareCount = activity.prepareCountForTesting()
            instrumentation.runOnMainSync { activity.handlePlaybackEndedForTesting() }
            waitForPrepareCount(activity, firstPrepareCount + 1)
            waitUntilReady(activity)
            assertEquals(
                "同集备用片源不能被自动连播当成下一集",
                "S01E02.mkv",
                activity.currentTechnicalFilenameForTesting(),
            )
            assertTrue(playerPlayWhenReady(activity))

            val secondPrepareCount = activity.prepareCountForTesting()
            instrumentation.runOnMainSync { activity.handlePlaybackEndedForTesting() }
            waitForPrepareCount(activity, secondPrepareCount + 1)
            waitUntilReady(activity)
            assertEquals("连播应自然跨季", "S02E01.mkv", activity.currentTechnicalFilenameForTesting())

            val finalPrepareCount = activity.prepareCountForTesting()
            instrumentation.runOnMainSync {
                activity.handlePlaybackEndedForTesting()
                activity.handlePlaybackEndedForTesting()
            }
            SystemClock.sleep(500L)
            assertEquals("最后一集结束后不能循环或重复 prepare", finalPrepareCount, activity.prepareCountForTesting())
            assertEquals("S02E01.mkv", activity.currentTechnicalFilenameForTesting())
        } finally {
            finish(activity)
        }
    }

    @Test
    fun movieEndingNeverTreatsAnotherSourceAsTheNextEpisode() {
        val resources = JSONArray()
            .put(resource("movie-a", "Movie A", "Movie.2160p.REMUX.mkv"))
            .put(resource("movie-b", "Movie B", "Movie.1080p.WEB-DL.mkv"))
        val activity = launch(session("movie", resources, "movie-a"))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            val prepareCount = activity.prepareCountForTesting()
            instrumentation.runOnMainSync { activity.handlePlaybackEndedForTesting() }
            SystemClock.sleep(500L)
            assertEquals("电影结束不能自动切到备用片源", prepareCount, activity.prepareCountForTesting())
            assertEquals("Movie.2160p.REMUX.mkv", activity.currentTechnicalFilenameForTesting())
        } finally {
            finish(activity)
        }
    }

    @Test
    fun systemMediaSessionPublishesMetadataAndControlsTheActiveEpisode() {
        val resources = JSONArray()
            .put(resource("s1e1", "Episode 1", "S01E01.mkv", 1, "1"))
            .put(resource("s1e2", "Episode 2", "S01E02.mkv", 1, "2"))
        val seasons = JSONArray().put(
            JSONObject()
                .put("season", 1)
                .put("displayTitle", "第 1 季")
                .put("resourceIds", JSONArray().put("s1e1").put("s1e2")),
        )
        val activity = launch(session("series", resources, "s1e1", seasons))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var controller: MediaController? = null
        var controllerFuture: java.util.concurrent.Future<MediaController>? = null
        try {
            waitUntilReady(activity)
            controllerFuture = MediaController.Builder(
                instrumentation.targetContext,
                activity.mediaSessionForTesting().token,
            )
                .setApplicationLooper(Looper.getMainLooper())
                .buildAsync()
            controller = controllerFuture.get(10, TimeUnit.SECONDS)
            assertTrue("系统 MediaController 必须能连接播放器会话", controller.isConnected)
            assertEquals("Media3 fixture · S01E01", controllerDisplayTitle(instrumentation, controller))
            assertTrue(
                "剧集媒体会话必须向耳机/蓝牙暴露下一集命令",
                controllerCommandAvailable(instrumentation, controller, Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM),
            )
            assertTrue(
                "剧集媒体会话必须向耳机/蓝牙暴露上一集命令",
                controllerCommandAvailable(instrumentation, controller, Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM),
            )

            instrumentation.runOnMainSync { controller.pause() }
            waitForPlayWhenReady(activity, false)

            val prepareBefore = activity.prepareCountForTesting()
            instrumentation.runOnMainSync { controller.seekToNextMediaItem() }
            waitForPrepareCount(activity, prepareBefore + 1)
            waitUntilReady(activity)
            waitForControllerDisplayTitle(instrumentation, controller, "Media3 fixture · S01E02")
            assertEquals("s1e2", controllerMediaId(instrumentation, controller))

            val previousPrepareCount = activity.prepareCountForTesting()
            waitForControllerCommandAvailable(
                instrumentation,
                controller,
                Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM,
            )
            instrumentation.runOnMainSync { controller.seekToPreviousMediaItem() }
            waitForPrepareCount(activity, previousPrepareCount + 1)
            waitUntilReady(activity)
            waitForControllerDisplayTitle(instrumentation, controller, "Media3 fixture · S01E01")
            assertEquals("s1e1", controllerMediaId(instrumentation, controller))

            val finalPrepareCount = activity.prepareCountForTesting()
            waitForControllerCommandAvailable(instrumentation, controller, Player.COMMAND_SEEK_TO_NEXT)
            instrumentation.runOnMainSync { controller.seekToNext() }
            waitForPrepareCount(activity, finalPrepareCount + 1)
            waitUntilReady(activity)
            waitForControllerDisplayTitle(instrumentation, controller, "Media3 fixture · S01E02")

            instrumentation.runOnMainSync { controller.play() }
            waitForPlayWhenReady(activity, true)
        } finally {
            controller?.let { connected ->
                instrumentation.runOnMainSync { connected.release() }
            } ?: controllerFuture?.let(MediaController::releaseFuture)
            finish(activity)
        }
    }

    @Test
    fun multiSeasonSeriesGroupsAlternateSourcesInsideOneEpisode() {
        val resources = JSONArray()
            .put(resource("s1e1-a", "Episode 1 A", "S01E01.A.mkv", 1, "1", "4K · Dolby Vision"))
            .put(resource("s1e1-b", "Episode 1 B", "S01E01.B.mkv", 1, "1", "1080P"))
            .put(resource("s1e2", "Episode 2", "S01E02.mkv", 1, "2", "4K"))
            .put(resource("s2e1", "Season 2 Episode 1", "S02E01.mkv", 2, "1", "4K"))
        val seasons = JSONArray()
            .put(
                JSONObject()
                    .put("season", 1)
                    .put("displayTitle", "第 1 季")
                    .put("resourceIds", JSONArray().put("s1e1-a").put("s1e1-b").put("s1e2")),
            )
            .put(
                JSONObject()
                    .put("season", 2)
                    .put("displayTitle", "第 2 季")
                    .put("resourceIds", JSONArray().put("s2e1")),
            )
        val activity = launch(session("series", resources, "s1e1-a", seasons))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            forcePortrait(activity)
            val tabs = activity.findViewById<LinearLayout>(R.id.portrait_season_tabs)
            val grid = activity.findViewById<GridLayout>(R.id.portrait_episode_grid)
            assertEquals(2, tabs.childCount)
            assertEquals("同集备用片源不能被算成第三集", 2, grid.childCount)

            instrumentation.runOnMainSync { (grid.getChildAt(0) as Button).performClick() }
            val panelItems = activity.findViewById<LinearLayout>(R.id.side_panel_items)
            assertEquals("第一集应在二级面板中展示两个独立片源", 2, panelItems.childCount)
            instrumentation.runOnMainSync { activity.findViewById<View>(R.id.side_panel_close).performClick() }
            waitForVisibility(instrumentation, activity.findViewById(R.id.side_panel), View.GONE)

            instrumentation.runOnMainSync {
                activity.playerForTesting().pause()
                activity.playerForTesting().seekTo(8_000L)
                activity.switchResourceForTesting("s1e1-b", true)
            }
            waitUntilReady(activity)
            assertEquals("S01E01.B.mkv", activity.currentTechnicalFilenameForTesting())
            assertTrue("同集切源应保留播放位置", playerPosition(activity) >= 6_500L)

            instrumentation.runOnMainSync { activity.switchResourceForTesting("s1e2", false) }
            waitUntilReady(activity)
            assertEquals("S01E02.mkv", activity.currentTechnicalFilenameForTesting())
            assertTrue("换集必须从零开始", playerPosition(activity) < 3_000L)
        } finally {
            finish(activity)
        }
    }

    @Test
    fun multipleMovieSourcesStayMoviesAndTechnicalDataDoesNotMix() {
        val resources = JSONArray()
            .put(resource("movie-a", "Movie A", "Movie.2160p.REMUX.mkv", badges = "4K · HDR10 · TrueHD Atmos"))
            .put(resource("movie-b", "Movie B", "Movie.1080p.WEB-DL.mkv", badges = "1080P · SDR · AAC"))
        val activity = launch(session("movie", resources, "movie-a"))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            forcePortrait(activity)
            assertEquals("movie", activity.contentKindForTesting())
            assertEquals(View.GONE, activity.findViewById<View>(R.id.portrait_episode_section).visibility)
            assertEquals(View.VISIBLE, activity.findViewById<View>(R.id.portrait_movie_section).visibility)
            assertEquals(2, activity.findViewById<LinearLayout>(R.id.portrait_movie_sources).childCount)
            assertEquals("Movie.2160p.REMUX.mkv", activity.currentTechnicalFilenameForTesting())

            instrumentation.runOnMainSync {
                activity.playerForTesting().pause()
                activity.playerForTesting().seekTo(7_000L)
                activity.switchResourceForTesting("movie-b", true)
            }
            waitUntilReady(activity)
            assertEquals("Movie.1080p.WEB-DL.mkv", activity.currentTechnicalFilenameForTesting())
            assertTrue(playerPosition(activity) >= 5_500L)
        } finally {
            finish(activity)
        }
    }

    @Test
    fun providerQualityFailureFallsBackToTheOriginalAtTheSamePosition() {
        val cloud = JSONObject()
            .put("supported", true)
            .put("provider", "fixture")
            .put("providerName", "Fixture Cloud")
            .put("qualitiesUrl", "https://127.0.0.1:1/qualities")
            .put("streamUrl", "https://127.0.0.1:1/stream-transcoded")
            .put("resolutionParam", "resolution")
        val resource = resource("cloud-movie", "Cloud movie", "Cloud.Movie.mkv")
            .put("cloudTranscode", cloud)
        val activity = launch(session("movie", JSONArray().put(resource), "cloud-movie"))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            waitUntilReady(activity)
            assertEquals(View.VISIBLE, activity.qualityButtonVisibilityForTesting())
            instrumentation.runOnMainSync {
                activity.playerForTesting().pause()
                activity.playerForTesting().seekTo(9_000L)
                activity.injectQualityForTesting(
                    "cloud-movie",
                    "fhd",
                    "FHD",
                    "https://127.0.0.1:1/unavailable-quality",
                )
                activity.findViewById<Button>(R.id.quality_button).performClick()
            }
            val items = activity.findViewById<LinearLayout>(R.id.side_panel_items)
            assertEquals("画质面板必须包含原文件与 provider 档位", 2, items.childCount)
            val prepareBefore = activity.prepareCountForTesting()
            instrumentation.runOnMainSync { items.getChildAt(1).performClick() }
            waitForPrepareCount(activity, prepareBefore + 2)
            waitUntilReady(activity)
            assertNull("provider 流失败后必须回到原文件", activity.currentQualityResolutionForTesting())
            assertEquals("cloud-movie", activity.currentResourceIdForTesting())
            assertTrue("回退原文件时应保留位置", playerPosition(activity) >= 7_000L)
        } finally {
            finish(activity)
        }
    }

    @Test
    fun directFailureShowsARecoverableErrorWithoutAServerTranscodeFallback() {
        val broken = resource("broken-original", "Broken original", "Broken.mkv")
        broken.getJSONObject("direct").put("url", "https://127.0.0.1:1/unavailable")
        val activity = launch(session("movie", JSONArray().put(broken), "broken-original"))
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        try {
            val deadline = SystemClock.elapsedRealtime() + 15_000L
            while (SystemClock.elapsedRealtime() < deadline && !activity.playerErrorVisibleForTesting()) {
                Thread.sleep(200L)
            }
            assertFalse("解码或网络失败不能再表现成播放器闪退", activity.isFinishing)
            assertTrue("失败后应留在播放器并显示可恢复提示", activity.playerErrorVisibleForTesting())
            assertNotNull(activity.lastPlaybackErrorForTesting())
        } finally {
            finish(activity)
        }
    }

    private fun session(
        contentKind: String,
        resources: JSONArray,
        initialResourceId: String,
        seasons: JSONArray? = null,
    ): JSONObject {
        val movie = JSONObject().put("id", "test").put("title", "Media3 fixture")
        if (seasons != null) movie.put("seasons", seasons)
        return JSONObject()
            .put("version", 2)
            .put("sessionId", "android-test-${System.nanoTime()}")
            .put("initialResourceId", initialResourceId)
            .put("startTimeMs", 0L)
            .put("contentKind", contentKind)
            .put("movie", movie)
            .put("resources", resources)
    }

    private fun resource(
        id: String,
        title: String,
        filename: String,
        season: Int? = null,
        episode: String? = null,
        badges: String? = null,
        subtitles: JSONArray = JSONArray(),
    ): JSONObject {
        val badgeArray = JSONArray()
        badges?.split(" · ")?.forEach(badgeArray::put)
        return JSONObject()
            .put("id", id)
            .put("title", title)
            .put("season", season)
            .put("episode", episode)
            .put(
                "technical",
                JSONObject()
                    .put("filename", filename)
                    .put("sizeBytes", 80_000_000_000L)
                    .put("storageSource", "Test Library")
                    .put("container", "mkv")
                    .put("badges", badgeArray),
            )
            .put(
                "direct",
                JSONObject()
                    .put("id", "direct")
                    .put("label", "原文件")
                    .put("mimeType", "application/x-mpegURL")
                    .put("url", HLS_URL),
            )
            .put("subtitles", subtitles)
    }

    private fun launch(session: JSONObject, forceCellular: Boolean = false): PlayerActivity {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        return instrumentation.startActivitySync(
            Intent(instrumentation.targetContext, PlayerActivity::class.java)
                .putExtra(PlayerActivity.EXTRA_SESSION_JSON, session.toString())
                .putExtra(PlayerActivity.EXTRA_CELLULAR_NETWORK_FOR_TESTING, forceCellular)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        ) as PlayerActivity
    }

    private fun waitUntilReady(activity: PlayerActivity, timeoutMs: Long = 20_000L) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val state = AtomicInteger(Player.STATE_IDLE)
        val error = AtomicReference<Throwable?>(null)
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            instrumentation.runOnMainSync {
                state.set(activity.playerForTesting().playbackState)
                error.set(activity.playerForTesting().playerError)
            }
            if (state.get() == Player.STATE_READY || error.get() != null || activity.isFinishing) break
            Thread.sleep(200L)
        }
        assertNull("Media3 failed to prepare fixture: ${error.get()}", error.get())
        assertEquals("Media3 never reached READY", Player.STATE_READY, state.get())
    }

    private fun forcePortrait(activity: PlayerActivity) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        if (activity.resources.configuration.orientation == Configuration.ORIENTATION_PORTRAIT) return
        instrumentation.runOnMainSync {
            activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
        waitForOrientation(activity, Configuration.ORIENTATION_PORTRAIT)
        instrumentation.waitForIdleSync()
        val deadline = SystemClock.elapsedRealtime() + 4_000L
        while (
            SystemClock.elapsedRealtime() < deadline &&
            activity.findViewById<View>(R.id.portrait_movie_section) == null
        ) {
            Thread.sleep(50L)
        }
        assertNotNull("Portrait player layout was not attached", activity.findViewById<View>(R.id.portrait_movie_section))
    }

    private fun waitForOrientationChange(activity: PlayerActivity, oldOrientation: Int) {
        val deadline = SystemClock.elapsedRealtime() + 8_000L
        while (
            SystemClock.elapsedRealtime() < deadline &&
            activity.resources.configuration.orientation == oldOrientation
        ) {
            Thread.sleep(100L)
        }
        assertTrue(activity.resources.configuration.orientation != oldOrientation)
    }

    private fun waitForOrientation(activity: PlayerActivity, orientation: Int) {
        val deadline = SystemClock.elapsedRealtime() + 8_000L
        while (
            SystemClock.elapsedRealtime() < deadline &&
            activity.resources.configuration.orientation != orientation
        ) {
            Thread.sleep(100L)
        }
        assertEquals(orientation, activity.resources.configuration.orientation)
    }

    private fun waitForPrepareCount(activity: PlayerActivity, expected: Int) {
        val deadline = SystemClock.elapsedRealtime() + 15_000L
        while (SystemClock.elapsedRealtime() < deadline && activity.prepareCountForTesting() < expected) {
            Thread.sleep(100L)
        }
        assertTrue(activity.prepareCountForTesting() >= expected)
    }

    private fun playerPosition(activity: PlayerActivity): Long {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val position = AtomicReference(0L)
        instrumentation.runOnMainSync { position.set(activity.playerForTesting().currentPosition) }
        return position.get()
    }

    private fun playerPlayWhenReady(activity: PlayerActivity): Boolean {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val playWhenReady = AtomicReference(false)
        instrumentation.runOnMainSync { playWhenReady.set(activity.playerForTesting().playWhenReady) }
        return playWhenReady.get()
    }

    private fun waitForPlayWhenReady(activity: PlayerActivity, expected: Boolean, timeoutMs: Long = 5_000L) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (playerPlayWhenReady(activity) == expected) return
            Thread.sleep(100L)
        }
        assertEquals("系统媒体控制没有同步到 Activity 播放状态", expected, playerPlayWhenReady(activity))
    }

    private fun controllerDisplayTitle(
        instrumentation: android.app.Instrumentation,
        controller: MediaController,
    ): String {
        val title = AtomicReference("")
        instrumentation.runOnMainSync { title.set(controller.mediaMetadata.displayTitle?.toString().orEmpty()) }
        return title.get()
    }

    private fun controllerMediaId(
        instrumentation: android.app.Instrumentation,
        controller: MediaController,
    ): String? {
        val mediaId = AtomicReference<String?>(null)
        instrumentation.runOnMainSync { mediaId.set(controller.currentMediaItem?.mediaId) }
        return mediaId.get()
    }

    private fun controllerCommandAvailable(
        instrumentation: android.app.Instrumentation,
        controller: MediaController,
        command: Int,
    ): Boolean {
        val available = AtomicReference(false)
        instrumentation.runOnMainSync { available.set(controller.isCommandAvailable(command)) }
        return available.get()
    }

    private fun waitForControllerCommandAvailable(
        instrumentation: android.app.Instrumentation,
        controller: MediaController,
        command: Int,
        timeoutMs: Long = 5_000L,
    ) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (controllerCommandAvailable(instrumentation, controller, command)) return
            Thread.sleep(100L)
        }
        assertTrue(
            "切集后系统媒体命令没有恢复",
            controllerCommandAvailable(instrumentation, controller, command),
        )
    }

    private fun waitForControllerDisplayTitle(
        instrumentation: android.app.Instrumentation,
        controller: MediaController,
        expected: String,
        timeoutMs: Long = 5_000L,
    ) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (controllerDisplayTitle(instrumentation, controller) == expected) return
            Thread.sleep(100L)
        }
        assertEquals(expected, controllerDisplayTitle(instrumentation, controller))
    }

    private fun dispatchDoubleTap(view: View) {
        val x = view.width.coerceAtLeast(2) / 2f
        val y = view.height.coerceAtLeast(2) / 2f
        val first = SystemClock.uptimeMillis()
        dispatchTap(view, first, x, y)
        dispatchTap(view, first + 120L, x, y)
    }

    private fun dispatchTap(view: View, time: Long, x: Float, y: Float) {
        MotionEvent.obtain(time, time, MotionEvent.ACTION_DOWN, x, y, 0).also {
            view.dispatchTouchEvent(it)
            it.recycle()
        }
        MotionEvent.obtain(time, time + 20L, MotionEvent.ACTION_UP, x, y, 0).also {
            view.dispatchTouchEvent(it)
            it.recycle()
        }
    }

    private fun waitForVisibility(
        instrumentation: android.app.Instrumentation,
        view: View,
        expectedVisibility: Int,
        timeoutMs: Long = 2_000L,
    ): Int {
        val observed = AtomicInteger(Int.MIN_VALUE)
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        do {
            instrumentation.runOnMainSync { observed.set(view.visibility) }
            if (observed.get() == expectedVisibility) break
            Thread.sleep(50L)
        } while (SystemClock.elapsedRealtime() < deadline)
        return observed.get()
    }

    private fun collectText(view: View): List<String> {
        val own = (view as? TextView)?.text?.toString()?.let(::listOf) ?: emptyList()
        if (view !is ViewGroup) return own
        return own + (0 until view.childCount).flatMap { collectText(view.getChildAt(it)) }
    }

    private fun finish(activity: PlayerActivity) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync { if (!activity.isFinishing) activity.finish() }
        instrumentation.waitForIdleSync()
    }
}
