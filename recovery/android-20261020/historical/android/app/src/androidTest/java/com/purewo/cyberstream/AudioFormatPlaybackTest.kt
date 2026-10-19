package com.purewo.cyberstream

import android.content.Intent
import android.os.SystemClock
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.ui.PlayerView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Plays real encoded fixtures and verifies the decoder that Media3 initialized. */
@UnstableApi
@RunWith(AndroidJUnit4::class)
class AudioFormatPlaybackTest {
    private data class Fixture(
        val label: String,
        val file: String,
        val mustUseFfmpeg: Boolean = false,
        val mustUsePlatformDecoder: Boolean = false,
    )

    @Test
    fun playsRequiredAudioFormatsAndInitializesExpectedDecoders() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val baseUrl = InstrumentationRegistry.getArguments().getString("fixtureBaseUrl")?.trimEnd('/')
        assumeTrue("Pass -e fixtureBaseUrl to run local codec playback tests", !baseUrl.isNullOrBlank())

        val fixtures = listOf(
            Fixture("AAC", "aac.m4a", mustUsePlatformDecoder = true),
            Fixture("AC-3", "ac3.mka"),
            Fixture("E-AC-3", "eac3.mka"),
            Fixture("E-AC-3 JOC", "eac3-joc.mka"),
            Fixture("DTS", "dts.mkv", mustUseFfmpeg = true),
            Fixture("DTS-HD MA", "dts-hd-ma.mkv", mustUseFfmpeg = true),
            Fixture("DTS:X", "dts-x.mkv", mustUseFfmpeg = true),
            Fixture("Dolby TrueHD 5.1", "truehd-5.1.mka", mustUseFfmpeg = true),
            Fixture("FLAC 24-bit", "flac-24bit.mka"),
            Fixture("Opus 5.1", "opus-5.1.mka"),
            Fixture("Vorbis", "vorbis.mkv"),
        )

        fixtures.forEachIndexed { index, fixture ->
            val session = JSONObject()
                .put("sessionId", "codec-${index}-${System.nanoTime()}")
                .put("initialResourceId", fixture.file)
                .put("startTimeMs", 0L)
                .put("movie", JSONObject().put("id", "codec-test").put("title", fixture.label))
                .put(
                    "resources",
                    JSONArray().put(
                        JSONObject()
                            .put("id", fixture.file)
                            .put("title", fixture.label)
                            .put(
                                "direct",
                                JSONObject()
                                    .put("id", "direct")
                                    .put("label", "Original")
                                    .put("url", "$baseUrl/${fixture.file}"),
                            )
                            .put("subtitles", JSONArray()),
                    ),
                )

            val activity = instrumentation.startActivitySync(
                Intent(instrumentation.targetContext, PlayerActivity::class.java)
                    .putExtra(PlayerActivity.EXTRA_SESSION_JSON, session.toString())
                    .putExtra(PlayerActivity.EXTRA_CELLULAR_NETWORK_FOR_TESTING, false)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            ) as PlayerActivity

            try {
                var decoderName: String? = null
                var playbackError: String? = null
                var playbackState = Player.STATE_IDLE
                val deadline = SystemClock.elapsedRealtime() + 15_000L
                while (SystemClock.elapsedRealtime() < deadline) {
                    instrumentation.runOnMainSync {
                        decoderName = activity.audioDecoderNameForTesting()
                        playbackError = activity.lastPlaybackErrorForTesting()
                        playbackState = activity.findViewById<PlayerView>(R.id.media_player_view)
                            .player
                            ?.playbackState
                            ?: Player.STATE_IDLE
                    }
                    if (playbackError != null || (decoderName != null && playbackState != Player.STATE_IDLE)) break
                    Thread.sleep(100L)
                }

                assertNull("${fixture.label} playback failed: $playbackError", playbackError)
                assertNotNull("${fixture.label} never initialized an audio decoder", decoderName)
                if (fixture.mustUseFfmpeg) {
                    assertTrue(
                        "${fixture.label} should use FFmpeg fallback, got $decoderName",
                        decoderName!!.startsWith("ffmpeg"),
                    )
                }
                if (fixture.mustUsePlatformDecoder) {
                    assertFalse(
                        "${fixture.label} should keep the platform decoder ahead of FFmpeg, got $decoderName",
                        decoderName!!.startsWith("ffmpeg"),
                    )
                }
                assertNotNull("${fixture.label} did not expose an input MIME type", activity.audioMimeTypeForTesting())
            } finally {
                instrumentation.runOnMainSync { activity.finish() }
                instrumentation.waitForIdleSync()
            }
        }
    }
}
