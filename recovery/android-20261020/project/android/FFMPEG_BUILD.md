# Media3 FFmpeg audio extension

CyberStream Android uses the official AndroidX Media3 FFmpeg decoder module as
a local audio fallback. Platform `MediaCodec` renderers remain first in the
renderer list; FFmpeg is selected only when Android cannot decode an audio
track itself.

## Pinned sources

- AndroidX Media tag: `1.10.1`
- AndroidX source: `https://github.com/androidx/media/tree/1.10.1/libraries/decoder_ffmpeg`
- FFmpeg release: `6.0.1`
- FFmpeg archive: `https://ffmpeg.org/releases/ffmpeg-6.0.1.tar.xz`
- FFmpeg archive SHA-256: `9B16B8731D78E596B4BE0D720428CA42DF642BB2D78342881FF7F5BC29FC9623`
- Android NDK used for FFmpeg static libraries: `26.1.10909125` (r26b)
- Android ABI level: `24`

The Media3 Gradle build selected NDK `27.0.12077973` to compile the small JNI
wrapper around the already-built FFmpeg static libraries. The resulting AAR is
compatible with the app's `minSdk 24` and contains all four standard ABIs.

## Enabled FFmpeg decoders

`aac ac3 eac3 dca truehd flac opus vorbis mp3 alac`

`dca` covers DTS and DTS-HD. `truehd` covers Dolby TrueHD. No encoder, muxer,
network protocol, GPL component, or non-free component is enabled.

The FFmpeg configure result reports `License: LGPL version 2.1 or later`.

## Build command

From an AndroidX Media `1.10.1` checkout, with FFmpeg 6.0.1 extracted at
`libraries/decoder_ffmpeg/src/main/jni/ffmpeg`:

```bash
FFMPEG_MODULE_PATH="$PWD/libraries/decoder_ffmpeg/src/main"
"$FFMPEG_MODULE_PATH/jni/build_ffmpeg.sh" \
  "$FFMPEG_MODULE_PATH" \
  "$ANDROID_SDK_ROOT/ndk/26.1.10909125" \
  linux-x86_64 \
  24 \
  aac ac3 eac3 dca truehd flac opus vorbis mp3 alac

./gradlew :lib-decoder-ffmpeg:assembleRelease
```

Copy `lib-decoder-ffmpeg-release.aar` to:

`app/libs/media3-decoder-ffmpeg-1.10.1-ffmpeg6.0.1.aar`

Current AAR SHA-256:

`8721422B552D0BEAE9222B265B6BE580EC2C6215493602D51195E361C8719916`

## Runtime policy

- `DefaultRenderersFactory.EXTENSION_RENDERER_MODE_ON`: Android system decoder
  first, FFmpeg only as fallback.
- Float PCM output is enabled when the device's `AudioTrack` supports it.
- No loudness normalization, lossy re-encoding, or intentional sample-rate
  conversion is configured.
- Multichannel audio is downmixed only when the Android output path cannot
  accept the source channel layout.
- This extension is local decoding only. It never invokes a server transcode.

## Distribution obligations

The APK includes the FFmpeg LGPL 2.1 license and a third-party notice under
`app/src/main/assets`. FFmpeg is statically linked into `libffmpegJNI.so`, so a
public production release must also satisfy LGPL 2.1 section 6, including a
practical relinking/source path for the exact FFmpeg build. Keep this build
recipe and the corresponding source archive with each release artifact.
