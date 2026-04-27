# 测试与验收清单

本文档用于赛博影视后端的日常改动验收，目标是：

- 每次修改后都有最小可执行检查项
- 降低“改一处，坏一片”但没及时发现的风险
- 方便任何接手者快速完成回归

---

## 1. 验收原则

1. 先做本地验收，再做公网验收
2. 每次改动至少覆盖与改动直接相关的模块
3. 涉及扫描、播放、存储源时，必须做针对性回归
4. 修改文档、注释、纯展示文本时，可走简化验收

---

## 2. 基础启动验收（每次改动后建议执行）

### 2.1 启动服务
推荐：

```bash
cd /home/pureworld/赛博影视
/home/pureworld/赛博影视/.venv/bin/python -m backend.run
```

兼容：

```bash
/home/pureworld/赛博影视/.venv/bin/python backend/run.py
```

### 2.2 端口监听检查

```bash
ss -ltnp | grep ':5004 '
```

预期：
- 存在 Python 进程监听 `5004`

### 2.3 本地健康检查

```bash
curl -i http://127.0.0.1:5004/
```

预期：
- HTTP 200
- 返回 JSON
- `data.status = up`

### 2.4 公网健康检查

```bash
curl -i http://pw.pioneer.fan:84/
curl -k -i https://pw.pioneer.fan:84/
```

预期：
- HTTP/HTTPS 均能返回 200
- 返回健康检查 JSON

---

## 3. 接口级基础回归

以下建议在修改 API、模型、配置、启动逻辑后执行。

### 3.1 获取扫描状态

```bash
curl -s http://127.0.0.1:5004/api/v1/scan
```

预期：
- 返回标准 JSON
- 包含 `status`、`phase` 等字段

### 3.2 获取存储源列表

```bash
curl -s http://127.0.0.1:5004/api/v1/storage/sources
```

预期：
- 返回数组或空数组
- 不报 500

### 3.3 获取电影列表

```bash
curl -s "http://127.0.0.1:5004/api/v1/movies?page=1&page_size=5"
```

预期：
- 返回分页结构
- 包含 `items` 与 `pagination`
- 默认不包含 `needs_attention=true` 的 raw/占位/缺海报影片；如需检查处理队列，使用 `?needs_attention=true`

### 3.4 获取筛选项

```bash
curl -s "http://127.0.0.1:5004/api/v1/filters?include=genres,years,countries"
```

预期：
- 返回 `genres` / `years` / `countries`
- 不统计需要人工处理的 raw/占位/缺海报影片
- 没有 500 错误

### 3.5 获取推荐内容

```bash
curl -s "http://127.0.0.1:5004/api/v1/recommendations?limit=3"
```

预期：
- 返回数组
- 不报错

### 3.6 获取首页 featured

```bash
curl -s http://127.0.0.1:5004/api/v1/featured
```

预期：
- 返回数组
- 即使条目为空也不应 500

### 3.7 获取首页门户聚合数据

```bash
curl -s http://127.0.0.1:5004/api/v1/homepage
curl -s http://127.0.0.1:5004/api/v1/homepage/config
```

预期：
- 返回 `hero` 与 `sections`
- 默认分类包含 `科幻` / `动作` / `剧情` / `动画`
- 分类区块之间不重复影片

---

## 4. 存储源相关回归

以下在修改 provider、存储源接口、配置结构时必须执行。

### 4.1 存储源预览
使用一个已知可用的本地或 WebDAV 配置请求：

```bash
curl -s -X POST http://127.0.0.1:5004/api/v1/storage/preview \
  -H 'Content-Type: application/json' \
  -d '{"type":"local","config":{"root_path":"/tmp"},"target_path":"/"}'
```

预期：
- 返回目录项数组或空数组
- 不报 500

### 4.2 存储源新增/修改/删除
如有前端配合或测试数据环境，可做完整 CRUD 回归。

重点关注：
- `name`
- `type`
- `config`
- 删除时 `keep_metadata` 行为

---

## 5. 扫描相关回归

以下在修改扫描器、TMDB、路径解析逻辑时必须执行。

### 5.1 触发扫描

```bash
curl -i -X POST http://127.0.0.1:5004/api/v1/scan
```

预期：
- 返回 `202` 或成功受理状态
- 扫描状态变为 scanning
- 如果已有扫描任务在运行，应返回 `429`，不能并发启动第二个扫描

### 5.2 观察扫描状态变化

```bash
curl -s http://127.0.0.1:5004/api/v1/scan
```

预期：
- `status` / `phase` / `processed_items` 有合理变化

### 5.3 扫描结果抽查
检查：
- 新资源是否入库
- 标题是否异常
- 电影/剧集识别是否错乱
- 季集标签是否合理

---

## 6. 播放链路回归

以下在修改 `/resources/<id>/stream`、provider 流式读取、WebDAV 鉴权逻辑时必须执行。

### 6.1 获取某个资源详情
先从电影详情中拿一个 `resource.id`。

### 6.2 直接请求播放接口

```bash
curl -i "http://127.0.0.1:5004/api/v1/resources/<resource_id>/stream"
```

预期之一：
- 200 / 206 流式响应
- 或 302 跳转到上游播放地址
- 代理流的 `Content-Type` 应匹配资源扩展名，例如 `.mp4` 为 `video/mp4`、`.mkv` 为 `video/x-matroska`、`.ts/.m2ts` 为 `video/mp2t`

### 6.3 Range 请求验证

```bash
curl -i -H 'Range: bytes=0-1023' "http://127.0.0.1:5004/api/v1/resources/<resource_id>/stream"
```

预期：
- 返回 206
- 存在 `Content-Range`
- `Content-Type` 与直接请求保持一致

### 6.4 前端实际点播验证
如果有前端页面，应至少实际播放一次，确认：
- 能起播
- 不秒退
- 拖动进度条基本正常

---

## 7. 历史记录回归

以下在修改历史记录、播放心跳、设备字段时必须执行。

### 7.1 上报进度

```bash
curl -i -X POST http://127.0.0.1:5004/api/v1/user/history \
  -H 'Content-Type: application/json' \
  -d '{"resource_id":"<resource_id>","position_sec":120,"total_duration":3600,"device_id":"test-device","device_name":"Test Device"}'
```

预期：
- 返回成功 JSON

### 7.2 获取历史列表

```bash
curl -s http://127.0.0.1:5004/api/v1/user/history
```

预期：
- 能看到对应记录
- `device_name`、`progress` 字段正常

---

## 8. 文档改动的最小验收

如果本次只修改文档或注释，至少检查：

- 文档路径是否正确
- 文档索引（如 README）是否同步更新
- 文档内容与当前实际行为一致
- OpenAPI release notes 是否同步标记版本状态

---

## 9. 1.16.0 收口验收基线

截至 2026-04-25，`1.16.0` 已作为稳定联调基线收口，最后确认项：

- OpenAPI JSON 可解析校验通过
- OpenAPI path/method 与运行时路由对齐：`59/59`
- 全量 unittest：`126 tests OK`
- 本地健康检查 `GET http://127.0.0.1:5004/` 返回 `200`
- 小流量推荐接口 `GET /api/v1/recommendations?limit=1` 返回 `200`
- 资源库分页接口 `GET /api/v1/libraries/1/movies?page=1&page_size=1` 返回 `200`，包含 `pagination`
- Avatar 资源接口已验证可返回 `UHD Blu-ray Remux`、`HDR10`、`Dolby TrueHD 7.1 Atmos`、`HEVC` 等技术字段

该基线作为历史回归参考保留。当前主干版本为 `1.17.0`，发布前仍应优先执行本清单中的健康检查、OpenAPI 校验与全量 unittest。

---

## 10. 每次发布前建议人工确认的问题

1. 本地 5004 是否正常
2. 公网 84 HTTP/HTTPS 是否正常
3. 扫描状态接口是否正常
4. 电影列表是否正常
5. 至少一个资源是否能播放
6. 本次修改涉及的文档是否同步更新

---

## 11. 当前已确认通过的基础项（接手阶段）

截至 2026-04-02，已确认：

- 服务可在本地 `5004` 启动
- `GET /` 本地访问正常
- `GET /` 公网 HTTP 访问正常：`http://pw.pioneer.fan:84`
- `GET /` 公网 HTTPS 访问正常：`https://pw.pioneer.fan:84`
- Lucky 已将公网 `84` 端口映射到本机 `5004`
- `backend/run.py` 已兼容直接执行，不再因包导入路径报错

后续每次功能开发后，应在本文件中按需补充新的已验证项。
