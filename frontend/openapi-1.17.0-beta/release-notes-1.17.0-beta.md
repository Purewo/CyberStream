# 1.17.0-beta 更新说明

本文档记录 `1.17.0-beta` 的接口变化，作为 `develop/1.17.0` 的前后端联调基线。

## 当前重点

`1.17.0` 第一阶段围绕三个方向推进：

- 播放能力矩阵
- 推荐观看
- 元数据工作台增强

## 元数据工作台增强

本轮补齐面向前端复核闭环的解释型字段，不改变既有接口路径：

- `POST /api/v1/movies/{id}/metadata/preview` 和 `POST /api/v1/movies/{id}/metadata/re-scrape` 新增 `explanation`，包含结果分类、候选信息、解析信号和推荐动作。
- `GET /api/v1/movies/{id}/metadata/search` 的候选项新增 `rank` 和 `match_explanation`，用于解释标题、年份、媒体类型等命中信号。
- `POST /api/v1/metadata/re-scrape` 的逐条结果新增 `status`、`changed`、`updated_fields`、`season_metadata_result`；失败项新增 `error.category`、`retryable`、`recommended_action`。
- 批量 summary 新增 `succeeded`、`unchanged`、`status_counts`、`failed_movie_ids`，同时保留 `updated`、`failed`、`updated_movie_ids`。

## 推荐观看

全局 `GET /api/v1/recommendations` 与库级 `GET /api/v1/libraries/{id}/recommendations` 保持返回影片数组，但每个影片条目新增 `recommendation`：

- `strategy`、`rank`、`score`
- `primary_reason`
- `reasons[]`
- `reason_text`
- `signals.progress_ratio/quality_badge/resource_count`

`default` 现在是综合推荐，会考虑续看、最近入库、评分、质量标签、资源可播放性和类型多样性。`strategy` 新增 `continue_watching`，并继续支持 `latest`、`top_rated`、`surprise`。

新增单片上下文推荐接口：

- `GET /api/v1/movies/{id}/recommendations`

该接口用于详情页或播放页下方推荐。同系列 / 同标题族优先，同系列不足时用同类型补齐，再不足时只在同动漫或同非动漫分区内兜底。动漫与非动漫严格隔离，候选不足时允许少于 `limit`。

资源库内详情页可追加 `library_id`，服务端会先从当前资源库最终影片集合推荐，库内候选不足时再从全局补齐。库内命中会带 `same_library` 理由，库外补位会带 `outside_library_fill` 理由。

## 播放能力矩阵

`Resource` 对象新增 `playback` 字段。该字段会随现有资源返回一起出现，例如：

- `GET /api/v1/movies/{id}/resources`
- `PATCH /api/v1/resources/{id}/metadata`
- `PATCH /api/v1/movies/{id}/resources/metadata`

第一阶段不新增独立播放能力接口，也不改变 `GET /api/v1/resources/{id}/stream` 的默认行为；音频转码通过独立流接口提供，避免影响原始视频播放链路。

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

`server_transcode.available` 现在表示后端转码能力可用，不再要求后端提前识别音轨一定无法网页解码；即使音频编码未知或看起来可能支持，只要存储源支持 ffmpeg 输入且后端 ffmpeg 可用，前端也可以暴露“使用转码音频”的手动入口。`server_transcode.recommended=true` 才表示后端建议优先启用转码。

当前已新增独立音频实时转码接口：

- `GET /api/v1/resources/{id}/audio-transcode?start=0&audio_track=0&format=mp3`
- 强烈建议前端追加 `session_id`；同一资源同一 `session_id` 的新请求会先停止旧转码进程，并短暂等待旧进程释放单并发名额，避免 seek 时被旧流挡成 `429`。
- 页面卸载、切换资源或销毁播放器时调用 `DELETE /api/v1/resources/{id}/audio-transcode?session_id=...` 主动停止会话。
- 转码流启动后必须持续提交 `POST /api/v1/user/history`。默认 `180` 秒内未收到对应 `resource_id` 的进度提交时，后端会主动停止 ffmpeg，避免前端测试或悬挂连接长期占用远程下载流。
- 默认输出 `audio/mpeg` MP3，优先保证 HTML `audio` 兼容性。
- 默认下混到双声道、48kHz，避免网页端多声道解码差异影响播放。
- 可选 `format=aac` 输出 ADTS AAC。
- `start` 表示从原片多少秒开始转码，前端拖动进度后应以新的 `video.currentTime` 重建音频流。
- 音频转码流采用 forward-only 策略。前端应优先用当前 `audio.buffered` 完成缓冲区内 seek；只有目标时间超出音频缓冲区时才释放旧 audio 并用新的 `start` 重建。
- 后端会限制并发转码数；达到上限时返回 `429`。
- AList `/d` 或网盘 CDN 首次 Range 偶发失败时，后端会在同一个转码请求内部重试上游输入，并在首包前必要时重启 ffmpeg；前端不要用频繁重建 `audio.src` 的方式自行重试。
- 后端会对远程输入 HTTP Range 做进程内内存缓存，默认 256MB，用于复用 MKV 索引和相邻 seek 的原始字节片段；不缓存完整转码文件，不写磁盘。缓存按资源归属清理：history 判断同一 `session_id` 切换资源后，如果旧资源没有其他活跃观看会话，会清理旧资源缓存。
- 后端默认启用 ffmpeg `-re` 输入限速，优先保护原始视频直链，避免音频转码从同一个远端原片过度预读并挤占 CDN 带宽；seek 后音频首包可能略慢，前端不要因短暂等待频繁重建 `audio.src`。
- 新增 `GET /api/v1/resources/{id}/audio-transcode/diagnostics?session_id=...`，用于真实源联调时查看缓存命中、上游 Range 打开次数、首包耗时、输出字节与关闭原因。诊断中的输入 URL 会去掉 query/fragment，避免泄漏短期签名。

`playback.audio.server_transcode` 会在可用时返回 `endpoint`、默认 `url`、`start_param`、`audio_track_param`、`format_param`、`session_param`、`mime_type` 和 `sync_strategy=video_audio_dual_element`。

前端安全对接细节见 `docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md`。
