package com.purewo.cyberstream

import androidx.media3.common.MimeTypes
import androidx.media3.common.util.UnstableApi
import androidx.media3.decoder.ffmpeg.FfmpegLibrary
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Verifies the packaged native library and every explicitly enabled decoder. */
@UnstableApi
@RunWith(AndroidJUnit4::class)
class FfmpegExtensionSmokeTest {
    @Test
    fun packagedFfmpegLibraryExposesAllRequiredAudioDecoders() {
        assertTrue("FFmpeg JNI library must load on this device ABI", FfmpegLibrary.isAvailable())
        // Media3 exposes libavcodec's ABI string rather than FFmpeg's release
        // tag. FFmpeg 6.0.x uses libavcodec major version 60.
        val version = FfmpegLibrary.getVersion().orEmpty()
        assertTrue("Unexpected FFmpeg/libavcodec version: $version", version.startsWith("Lavc60."))

        val requiredFormats = linkedMapOf(
            "AAC" to MimeTypes.AUDIO_AAC,
            "AC-3" to MimeTypes.AUDIO_AC3,
            "E-AC-3" to MimeTypes.AUDIO_E_AC3,
            "E-AC-3 JOC" to MimeTypes.AUDIO_E_AC3_JOC,
            "DTS" to MimeTypes.AUDIO_DTS,
            "DTS-HD" to MimeTypes.AUDIO_DTS_HD,
            "TrueHD" to MimeTypes.AUDIO_TRUEHD,
            "FLAC" to MimeTypes.AUDIO_FLAC,
            "Opus" to MimeTypes.AUDIO_OPUS,
            "Vorbis" to MimeTypes.AUDIO_VORBIS,
        )
        requiredFormats.forEach { (label, mimeType) ->
            assertTrue("FFmpeg build is missing the $label decoder", FfmpegLibrary.supportsFormat(mimeType))
        }
    }
}
