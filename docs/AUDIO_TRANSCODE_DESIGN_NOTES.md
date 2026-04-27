# 实时音频转码设计笔记

本文记录 `1.17.0-beta` 当前音频转码链路的设计、实现取舍和未收口事项，方便后续继续开发。

## 目标

解决网页播放器无法解码 DTS、AC3、E-AC3、TrueHD 等音轨导致“有画面无声音”的问题，同时尽量避免前端误触发多条后端下载和转码流。

当前方案不改原视频播放链路：`video` 仍使用已有 `/stream` 或 AList `/d` 直链；缺声音时额外启动一个隐藏 `audio`，由后端实时转码输出 MP3/AAC。

## 接口边界

音频转码接口：

```http
GET /api/v1/resources/{resource_id}/audio-transcode?start={seconds}&audio_track=0&format=mp3&session_id={session_id}
DELETE /api/v1/resources/{resource_id}/audio-transcode?session_id={session_id}
```

资源能力矩阵中：

- `playback.audio.server_transcode.available=true` 表示后端能力可用，用户可手动启用。
- `playback.audio.server_transcode.recommended=true` 表示后端根据音轨风险建议启用。
- 不再用文件名或后端猜测阻止用户启用转码，是否需要转码以用户实际听感为准。

## 当前链路

整体链路：

```text
Browser video
  -> GET /api/v1/resources/{id}/stream
  -> 原始视频直连/302/AList 下载链路

Browser audio
  -> GET /api/v1/resources/{id}/audio-transcode?start=...
  -> Flask Response(stream_with_context)
  -> ffmpeg stdout pipe
  -> 本机 HTTP input proxy
  -> AList /d 或网盘 CDN Range 请求
```

这样做的原因：

- ffmpeg 直接读部分 HTTPS 直链时曾遇到 TLS/GnuTLS、Range 断流、首包失败等问题。
- 后端 Python 代理可以统一处理 `/d` 重试、Range 续读、内存缓存和关闭时清理。
- 转码输出走 stdout pipe，不写临时音频文件，避免磁盘被打爆。

## 播放与 seek 生命周期

后端把音频转码流定义为 forward-only：从 `start` 指定的原片时间开始，持续向后输出转码音频。前端应把浏览器 `audio.buffered` 当作主缓冲区：

- 目标 seek 时间落在当前 audio 已缓冲区内时，只调整 `audio.currentTime`。
- 目标 seek 时间超出当前 audio 缓冲区时，才释放旧 audio 并用新的 `start` 重建转码流。

当前策略不追求网页端 seek 秒开。这个链路只是网页播放器的兼容兜底，不是主播放内核；未来 Windows 客户端会优先调用系统解码能力。真实网盘源上，超出 `audio.buffered` 后重新转码可能等待十几秒到半分钟，只要能稳定接上且不拖慢原视频直链，就属于可接受范围。

前端应为每个播放器实例生成稳定 `session_id`。同一资源同一 `session_id` 发起新的 GET 时，后端会：

1. 先停止旧的 active stream。
2. 保留当前资源的 Range 内存缓存。
3. 重新按新的 `start` 启动 ffmpeg。
4. 注册新的 active stream。

保留缓存只是兜底：ffmpeg 可能会重复读取相邻 MKV cluster 或索引。主策略不依赖后端 Range 缓存，避免把临时网页播放方案做成复杂播放器内核。

页面卸载、切换资源、销毁播放器时，前端应调用 DELETE。DELETE 停止当前 `resource_id + session_id` 的流，但不负责删除仍可能被其他观看会话使用的资源缓存。

## Range 输入代理

`_AudioTranscodeHttpInputProxy` 是 ffmpeg 看到的本机 HTTP 服务，实际远端读取由 Python 完成。

关键行为：

- 支持 GET/HEAD。
- 透传 ffmpeg 发来的 `Range` 和 `If-Range`。
- 上游 408/425/429/500/502/503/504 会按配置重试。
- 上游中途断流时，会按已经写给 ffmpeg 的字节数续接下一段 Range。
- 客户端断开、seek 替换、watchdog 停止时，会关闭当前上游 response。

115/AList 现象：`/d` 链接偶发首次 Range 失败时，重试一两次通常能接上，所以重试在后端内部完成，前端不要频繁重建 `audio.src` 作为重试手段。

## Range 内存缓存

缓存对象：远程输入的原始视频字节 Range。

不缓存：

- 不缓存转码后的 MP3/AAC。
- 不缓存“音频时间轴”或任意秒数对应的转码音频片段。
- 不写磁盘。
- 不缓存完整视频。

默认：

- `FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_ENABLED=true`
- `FFMPEG_AUDIO_TRANSCODE_RANGE_CACHE_BYTES=268435456`，即 256MB。
- 单次 cache-only Range 返回最多 8MB，避免一次命中把内存块长时间占在本地 socket 上。

命中策略：

1. ffmpeg 请求带 `Range` 时，代理先查本地 Range 缓存。
2. 如果命中，直接返回 `206`，不打开远端连接。
3. 如果未完全覆盖请求区间，代理后续会按剩余 Range 继续打开远端。
4. 远端返回的新字节会按 `cache_key + offset` 写入缓存。

这个顺序很重要。之前的问题是“先打开远端，再尝试写缓存前缀”，即使缓存里已有数据，也可能卡在远端连接阶段。

需要特别注意：诊断里的 `cache_hit_count` 只表示原始视频字节 Range 命中，通常是 MKV 头、索引、尾部 metadata 或相邻 cluster。它不代表目标 seek 时间附近的转码音频已经存在。一次 seek 可能同时出现多次 cache hit 和一次关键 cache miss；如果关键 miss 落在远端 CDN 响应慢的位置，首包仍然会慢。

缓存归属：

- cache key 由 `resource_id + 去掉 query/fragment 的输入 URL` 组成。
- query 中的短期签名不进入 key，避免同一个文件每次换签名都 miss。
- `resource_cache_keys` 记录某个 resource 下有哪些 cache key。

清理策略：

- 同一 session seek 替换旧流时，设置 `preserve_cache_on_close=true`，保留当前资源缓存。
- history 心跳会记录 session 维度和 resource 维度的最近观看时间。
- 当用户切到其他资源，且旧资源没有 active stream、没有其他近期 history，会清理旧资源缓存。
- watchdog 或正常关闭时，如果资源已不活跃，也会尝试清理。

## 输出节流与背压

这一块是今晚多次调整后的当前策略。

已经验证过的问题：

- 如果完全不限制 ffmpeg，浏览器或 ffmpeg 可能快速预读远程视频，后端进程短时间读取超过 1GB，导致 256MB 缓存窗口被推到很远，小幅 seek 也 miss。
- 如果使用 ffmpeg 原生 `-re` 严格 1x 实时读取，前端 audio 元素几乎没有缓冲余量，缓存首段播完后容易出现“播 1 秒，卡 3-4 秒”。

当前默认策略：

- `FFMPEG_AUDIO_TRANSCODE_REALTIME_INPUT=true`，默认使用 ffmpeg 原生 `-re` 限制远端输入读取速度。
- 后端读取 ffmpeg stdout 时使用较小 chunk：`DEFAULT_AUDIO_TRANSCODE_OUTPUT_CHUNK_SIZE=16KB`。
- 后端仍保留输出突发与限速逻辑；当 `-re` 生效时，实际输出速度主要受 ffmpeg 输入读取速度约束。
- 这样牺牲一部分 seek 后音频首包速度，换取更稳定的原始视频播放，避免同一个 115/AList 远端文件被转码链路预读几十 GB。

相关配置：

- `FFMPEG_AUDIO_TRANSCODE_OUTPUT_INITIAL_BURST_SECONDS=8`
- `FFMPEG_AUDIO_TRANSCODE_OUTPUT_RATE_MULTIPLIER=1.5`
- `FFMPEG_AUDIO_TRANSCODE_REALTIME_INPUT=true`

这个策略的意图是在两端之间取平衡：让前端有可用缓冲，同时让远端读取不要无限领先当前播放点。

## 首包与重试

首包阶段的兜底：

- `FFMPEG_AUDIO_TRANSCODE_FIRST_BYTE_TIMEOUT_SECONDS=90`
- `FFMPEG_AUDIO_TRANSCODE_INPUT_RETRIES=2`

如果 ffmpeg 长时间没有输出任何音频字节，或者启动阶段出现可重试错误，后端会停止当前 ffmpeg 和输入代理，再重建一次。这个重试发生在同一个 HTTP 响应内部，前端不用参与。

已纳入可重试判断的 stderr 关键字：

- `End of file`
- `Connection timed out`
- `Input/output error`
- `Server returned`
- `Invalid data found when processing input`
- `Error in the pull function`

## 诊断快照

联调真实远程源时可查询：

```http
GET /api/v1/resources/{resource_id}/audio-transcode/diagnostics?session_id={session_id}
```

返回最近的转码流诊断项，包含：

- `counters.cache_only_hit_count/cache_prefix_hit_count/cache_miss_count/cache_hit_bytes`
- `counters.upstream_open_count/upstream_retry_count/upstream_bytes`
- `timings.first_audio_byte_ms`
- `counters.output_bytes/output_chunk_count/output_throttle_sleep_ms`
- `events[]`：`stream_started`、`input_proxy_started`、`upstream_open`、`cache_only_hit`、`first_audio_byte`、`stream_closed` 等关键事件

诊断中的输入 URL 会移除 query 和 fragment，避免把 AList/网盘短期签名暴露给前端日志。

## 安全保护

当前保护：

- 默认全局只允许 1 条转码流：`FFMPEG_AUDIO_TRANSCODE_MAX_CONCURRENT=1`。
- 同 session 新 GET 会替换旧流，避免 seek 时并发堆积。
- `FFMPEG_AUDIO_TRANSCODE_ACQUIRE_TIMEOUT_SECONDS=3`，给旧流释放并发名额的短窗口。
- 客户端断开、DELETE、watchdog 都会停止 ffmpeg。
- `POST /api/v1/user/history` 超过默认 180 秒没有对应资源心跳时，watchdog 停止转码。
- 输出响应 `Cache-Control: no-store`。

## 前端对接原则

前端细节见 `docs/FRONTEND_AUDIO_TRANSCODE_GUIDE.md`。后端实现依赖以下前端行为：

- 同一播放器实例保持稳定 `session_id`。
- seek 时先使用 `audio.buffered` 判断是否能在前端缓冲内完成；只有超出缓冲区时才在 `seeked` 后重建音频流，不在拖动过程高频请求。
- 重建前释放旧 audio：`pause()`、`removeAttribute("src")`、`load()`。
- 播放时持续提交 history，建议带同一个 `session_id`。
- 页面卸载、切换资源、销毁播放器时调用 DELETE。
- `waiting/stalled` 不要立刻循环重建 `audio.src`，先给后端重试窗口。

## 当前未完全收口

当前决策：

- 不继续扩大音频缓存复杂度。
- 不引入磁盘级转码音频缓存。
- 不为了网页兼容兜底牺牲原始视频直链稳定性。
- 保留现有诊断，方便将来如果要做“音频分片缓存 / 受控预读 / 更激进 seek 缓存窗口”时有排查基础。

后续如果重新投入这一块，优先看这些点：

1. 真实前端下验证 `-re` 输入限速后，seek 首包等待是否可接受，以及原始视频是否不再被音频转码挤占。
2. 继续观察诊断快照在真实前端下的噪声和字段是否够用，必要时再补更细的上游耗时统计。
3. 观察小幅 seek 后是否仍有远端 Range 长时间阻塞；如果有，考虑更激进的预缓冲或 seek 前后缓存窗口策略。
4. 评估 `mp3 192k` 是否足够稳定；如果 audio 标签对 MP3 流缓冲不理想，可以对比 `aac`。
5. 多用户并发暂未压测。当前默认单并发是保护策略，不是最终产品策略。
6. 资源缓存仍是进程内缓存，后端重启会清空；多 worker 部署时每个 worker 缓存独立，后续需要明确部署模型。

## 快速排障

常用观察：

```bash
tail -n 200 backend_server.log
ps -eo pid,ppid,etimes,pcpu,pmem,stat,args | rg "ffmpeg|python.*create_app|audio-transcode"
ss -tnp | rg "ffmpeg|python|:5004|:81|:443"
cat /proc/<python_pid>/io
cat /proc/<ffmpeg_pid>/io
```

判断思路：

- 有 `first byte unavailable`：首包阶段仍没接上，优先看远端 Range、ffmpeg stderr 和输入重试。
- seek 后请求很快返回 200 但前端卡顿：看输出速率、浏览器 audio buffer、后端到 ffmpeg 的本地 socket 队列。
- Python 远端读数快速飙升：说明预读仍过快，优先检查 `FFMPEG_AUDIO_TRANSCODE_REALTIME_INPUT` 是否实际生效，运行中的服务是否已重启加载新配置。
- 小幅 seek 仍慢：看是否 cache miss、是否缓存被清理、前端传给后端的 `start` 是否确实只移动了几秒。
