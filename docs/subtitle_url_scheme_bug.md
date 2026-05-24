# 字幕 URL scheme 与后端实际监听不一致 —— 请移除 PREFERRED_URL_SCHEME 强制改写

## 现象

PC 客户端（Tauri + libmpv 原生播放器）在后端切到 http 协议后，播放任何带绑定字幕的资源都会"音频先出，画面卡死 30+ 秒后才出现"。

mpv stderr 关键日志：

```
[mpv v stream_callback] Opening https://pioneer.fan:884/api/v1/resources/.../stream?subtitle_id=...
[mpv v vo/libmpv] mpv_render_context_render() not being called or stuck.   (× ~140 行)
[mpv error ffmpeg] tls: IO error: Error number -138 occurred
[mpv error stream] Failed to open https://pioneer.fan:884/...
```

视频流URL 是 `http://pioneer.fan:884/...`，能正常打开。但字幕 URL 是 `https://pioneer.fan:884/...` —— 同一个端口压根没监听 TLS，握手只能等到 mpv 的 `network-timeout`（默认 30s）才放弃。

PC 客户端这边我已经把 `sub-add` 派到独立线程，避免再阻塞 GL 主循环画面（之前画面冻结的根因），但**字幕加载本身仍然是失败的**——相当于绑定的字幕看似存在却实际上无法显示。

## 根因

`backend/app/services/urls.py` 的 `api_url_for()` 走了 `_normalize_external_url_scheme`：

```python
def _normalize_external_url_scheme(url):
    preferred_scheme = _preferred_external_scheme()
    if preferred_scheme != "https":
        return url
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.netloc or _is_local_netloc(parsed.netloc):
        return url
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))
```

只要 `PREFERRED_URL_SCHEME=https` 就把所有非本地的 http URL 改写成 https，无视后端真实是不是在跑 TLS。

字幕 URL 走的是 `api_url_for("player.stream_resource", ...)`（`subtitles.py:_subtitle_url`），所以被命中改写。视频流 URL 在前端是用 `resolveAssetUrl` 拼相对路径的，没经过这条路径，所以保留了 http —— 于是出现"视频 http、字幕 https"的分裂状态。

## 期望行为

后端在 `.env.local` 里填什么 scheme，对外就是什么 scheme。后端是 https 就返回 https URL，是 http 就返回 http URL。**不要**用一个额外的环境变量去"强制升级"——这种隐式改写在 reverse proxy 配置不一致时只会制造非常难排查的 bug。

## 建议改动

1. 删除 `_normalize_external_url_scheme` 整个函数
2. `api_url_for` 直接用 `url_for(endpoint, _external=True, ...)` 或拼 `BACKEND_PUBLIC_BASE_URL + path`
3. 文档里 `PREFERRED_URL_SCHEME` 保留 Flask 自带语义（影响 `url_for(_external=True)` 时的默认 scheme），删掉"会强制 http→https 改写"的不直观行为
4. 如果想保留"在反代后面用"的能力，告知运维设置 `BACKEND_PUBLIC_BASE_URL=https://...` 即可——这个地址里的 scheme 自然就是用户想要的

## 临时绕过（用户侧）

把 `.env.local` 里 `PREFERRED_URL_SCHEME` 改成 http 或留空，重启后端即可。但建议从代码层面去掉强制改写。

## 关联前端修复（已合）

PC 客户端这边的画面冻结症状已通过把 mpv `sub-add` / `sub-remove` 派到独立线程解决（`pc/src-tauri/src/native_player/mod.rs`）。即使后端 URL 不可达，主循环也不会再卡。但根本上字幕能正常加载还是要后端把 URL scheme 修对。
