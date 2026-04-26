# 1.17.0-beta 更新说明

本文档记录 `1.17.0-beta` 的接口变化，作为 `develop/1.17.0` 的前后端联调基线。

## 当前重点

`1.17.0` 第一阶段围绕三个方向推进：

- 播放能力矩阵
- 推荐观看
- 元数据工作台增强

## 播放能力矩阵

`Resource` 对象新增 `playback` 字段。该字段会随现有资源返回一起出现，例如：

- `GET /api/v1/movies/{id}/resources`
- `PATCH /api/v1/resources/{id}/metadata`
- `PATCH /api/v1/movies/{id}/resources/metadata`

第一阶段不新增独立播放能力接口，也不改变 `GET /api/v1/resources/{id}/stream` 的默认行为。

### 字段说明

- `stream_url`：后端播放入口，外部播放器也可使用该 URL；AList/OpenList 场景会继续由该入口 302 到上游 `/d/...` 直链。
- `playback_modes` / `default_mode`：当前资源的播放方式，例如 `redirect`、`proxy`、`server_stream`。
- `web_player`：网页播放器所需的 MIME、Range、音频兼容判断。
- `external_player`：PotPlayer、IINA、VLC 等外部播放器可用的 HTTP 播放地址。
- `subtitles`：字幕占位。当前尚未实现字幕发现/下载接口，因此固定返回空数组和 `subtitle_api_not_implemented`。
- `audio`：网页音频解码兼容和服务端音频转码状态。

### 音频转码现状

对于 DTS、AC3、E-AC3、TrueHD、TrueHD Atmos 等网页播放器常见无声风险格式，后端会标记：

- `audio.web_decode_status = unsupported`
- `audio.web_decode_risk = true`
- `web_player.needs_server_audio_transcode = true`

当前运行环境尚未安装 `ffmpeg` / `ffprobe`，因此服务端实时音频转码暂时只返回能力占位：

- `audio.server_transcode.supported = true`
- `audio.server_transcode.available = false`
- `audio.server_transcode.reason = ffmpeg_not_installed`

后续真正接入实时音频转码时，需要独立实现 seek 同步、Range 映射和服务器中转策略。
