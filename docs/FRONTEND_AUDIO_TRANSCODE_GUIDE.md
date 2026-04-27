# 前端音频实时转码对接指南

本文档面向 `1.17.0-beta` 前端联调。目标是解决 TrueHD、DTS、AC3、E-AC3 等网页播放器可能无声的问题，同时避免误触发多条后端转码流。

后端实现细节、缓存和输出背压策略见 `docs/AUDIO_TRANSCODE_DESIGN_NOTES.md`。本文只约束前端安全接入方式。

## 接口

资源详情中的 `playback.audio.server_transcode` 会暴露转码能力：

- `available=true`：可使用独立音频转码流。该字段只表示后端能力可用，不再要求后端提前判断音频一定无法网页解码。
- `recommended=true`：后端识别到 DTS、AC3、E-AC3、TrueHD 等高风险音轨，建议前端默认启用或突出提示。
- `endpoint`：不带查询参数的接口地址。
- `url`：默认示例 URL，仍建议前端自行拼接 `start` 和 `session_id`。
- `start_param= "start"`：从原片多少秒开始转码。
- `session_param= "session_id"`：播放会话 ID。
- `default_format= "mp3"`，`mime_type= "audio/mpeg"`。

实际接口：

```http
GET /api/v1/resources/{id}/audio-transcode?start=0&audio_track=0&format=mp3&session_id={sessionId}
DELETE /api/v1/resources/{id}/audio-transcode?session_id={sessionId}
GET /api/v1/resources/{id}/audio-transcode/diagnostics?session_id={sessionId}
```

`diagnostics` 仅用于联调和排障，前端播放主流程不要轮询。需要定位 seek 卡顿、首包慢、缓存未命中时再按资源和 `session_id` 查询。

## 当前产品定位

音频实时转码只是网页播放器的兼容兜底，用来解决少数音频编码在浏览器里无声的问题，不作为主播放通道优化。当前接受的体验边界是：

- 命中浏览器 `audio.buffered` 时，前端本地调整进度。
- 超出 `audio.buffered` 时，释放旧音频流并从目标时间重新请求后端转码。
- 真实网盘源 seek 后可能等待十几秒到半分钟；只要能稳定接上且不影响原始视频直链，就优先保持现有策略。
- 后端 Range 缓存只缓存原始视频字节，不缓存转码后的音频时间轴；看到诊断中的 cache hit 不等于目标秒数音频已缓存。

## 后端保护

后端当前有这些硬限制：

- 默认全局只允许 `1` 条实时音频转码流，可通过 `FFMPEG_AUDIO_TRANSCODE_MAX_CONCURRENT` 调整。
- 同一 `resource_id + session_id` 的新 GET 会先停止旧转码进程，再启动新进程；seek 请求会给旧进程短暂退出窗口，避免被单并发瞬时挡成 `429`。
- 客户端断开、audio 元素释放或响应关闭后，后端会终止对应 ffmpeg 进程。
- 后端会在同一个转码请求内部对 AList `/d` / 网盘 CDN 的偶发失败做重试；前端不要通过频繁重建 `audio.src` 自行重试。
- 拖动到远处时间点后，如果首包长时间不出来，后端会在首包前主动重建输入代理和 ffmpeg。
- 后端会对远程输入的 HTTP Range 做小型内存缓存，复用 MKV 索引和相邻 seek 的原始字节片段；缓存有上限且不落盘。缓存按资源归属清理：同一 `session_id` 通过 history 切到其他资源后，如果旧资源没有其他活跃观看会话，后端会清掉旧资源缓存。
- 后端默认启用 ffmpeg `-re` 输入限速，优先保护原始视频直链，避免音频转码从同一个远端原片过度预读。转码音频 seek 后可能需要稍等首包，前端不要因此频繁重建 audio。
- DELETE 接口可主动停止会话，供页面卸载、切换资源、销毁播放器时调用。
- 转码流启动后必须持续提交 `POST /api/v1/user/history`；默认超过 `180` 秒未收到对应 `resource_id` 的进度提交时，后端 watchdog 会主动停止 ffmpeg。
- 输出走 stdout pipe，不写转码文件；响应头包含 `Cache-Control: no-store`。

## 前端必须遵守

1. 每个播放器实例生成一个稳定 `session_id`，播放同一资源期间不要变化。
2. 同一播放器只保留一个隐藏 `audio` 元素，不要为重试、seek、预加载创建多个 audio。
3. 使用后端音频转码时，原始 `video` 必须静音：`video.muted = true`。
4. 不要给转码音频设置 `preload="auto"`；只在用户真正播放时设置 `audio.src`。
5. seek 时只在 `seeked` 后重建音频流，不要在 `timeupdate`、拖动过程或 slider input 中频繁请求。
6. 重建前先释放旧 audio：`pause()`、`removeAttribute("src")`、`load()`。
7. 页面卸载、切换影片、关闭播放器时调用 DELETE 停止接口。
8. 播放时按现有历史策略持续提交 `POST /api/v1/user/history`，建议带上同一个 `session_id`。
9. 首包等待期间不要因为 `waiting`、`stalled`、`loadedmetadata` 未触发就重建 `audio.src`；后端会处理上游重连。
10. 收到 `429` 时不要立即循环重试，按 `Retry-After` 或至少 5 秒后再试。
11. 收到 `503` 时回退为原始视频静音提示或建议外部播放器，不要重试轰炸。

## 推荐流程

```js
const sessionId = crypto.randomUUID();
let audioStart = 0;

function buildAudioUrl(endpoint, resourceId, start) {
  const url = new URL(endpoint, window.location.origin);
  url.searchParams.set("start", Math.max(0, start).toFixed(3));
  url.searchParams.set("audio_track", "0");
  url.searchParams.set("format", "mp3");
  url.searchParams.set("session_id", sessionId);
  return url.toString();
}

function releaseAudio(audio) {
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

async function attachTranscodedAudio(video, audio, endpoint) {
  video.muted = true;
  releaseAudio(audio);
  audioStart = video.currentTime || 0;
  audio.preload = "none";
  audio.src = buildAudioUrl(endpoint, video.dataset.resourceId, audioStart);
  audio.currentTime = 0;
  await audio.play();
}

async function reportHistory(resourceId, positionSec, totalDuration) {
  await fetch("/api/v1/user/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resource_id: resourceId,
      position_sec: Math.floor(positionSec),
      total_duration: Math.floor(totalDuration || 0),
      session_id: sessionId
    })
  });
}

function findBufferedAudioOffset(audio, targetVideoTime) {
  const targetAudioTime = targetVideoTime - audioStart;
  if (targetAudioTime < 0) return null;
  for (let i = 0; i < audio.buffered.length; i += 1) {
    const start = audio.buffered.start(i);
    const end = audio.buffered.end(i);
    if (targetAudioTime >= start && targetAudioTime <= end) {
      return targetAudioTime;
    }
  }
  return null;
}

async function syncAfterSeek(video, audio, endpoint) {
  const targetVideoTime = video.currentTime || 0;
  const bufferedOffset = findBufferedAudioOffset(audio, targetVideoTime);
  if (bufferedOffset !== null) {
    audio.currentTime = bufferedOffset;
    if (!video.paused) await audio.play();
    return;
  }

  releaseAudio(audio);
  audioStart = targetVideoTime;
  audio.src = buildAudioUrl(endpoint, video.dataset.resourceId, audioStart);
  await audio.play();
}

function cleanupAudio(resourceId, audio) {
  releaseAudio(audio);
  fetch(
    `/api/v1/resources/${resourceId}/audio-transcode?session_id=${encodeURIComponent(sessionId)}`,
    { method: "DELETE", keepalive: true }
  ).catch(() => {});
}
```

## 同步策略

- 以 `video.currentTime` 为主时钟。
- audio 流是 forward-only：从 `audioStart=start` 开始向后连续缓冲，audio 自己从 `0` 播放。
- seek 后先判断目标时间是否落在 `audio.buffered` 内；命中时只设置 `audio.currentTime = video.currentTime - audioStart`，不要重建后端流。
- 只有目标时间超出当前 audio 缓冲区时，才释放旧 audio 并用新的 `start=video.currentTime` 重建。
- 播放中如果 `Math.abs((audio.currentTime + audioStart) - video.currentTime) > 0.5`，先按上述 buffered 策略校正；仍不在缓冲区时再重建。
- `pause` 时同时 pause video 和 audio；`play` 时先 video，再重建或恢复 audio。
- 后端默认 `180` 秒没有看到该资源的 history 提交就会停止转码；前端不需要为了音频转码额外高频上报，继续使用现有播放进度上报节奏即可。

## 联调限制

前端联调阶段建议：

- 只开一个浏览器标签测试音频转码。
- 不做自动化并发压测。
- 不在列表页、详情页 hover、预览卡片里自动请求转码音频。
- 只在用户点击播放后请求音频转码。
