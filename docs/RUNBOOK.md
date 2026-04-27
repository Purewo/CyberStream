# 运行与排障手册

## 1. 启动

项目根目录：

```bash
cd /home/pureworld/赛博影视
```

使用虚拟环境启动：

```bash
/home/pureworld/赛博影视/.venv/bin/python -m backend.run
```

后台启动：

```bash
nohup /home/pureworld/赛博影视/.venv/bin/python -m backend.run > /home/pureworld/赛博影视/backend_server.log 2>&1 &
```

## 2. 停止

查找 5004 端口对应进程：

```bash
ss -ltnp | grep ':5004 '
```

按 PID 结束：

```bash
kill <PID>
```

## 3. 验收

### 本地验收

```bash
curl -i http://127.0.0.1:5004/
```

预期返回 `200` 与健康检查 JSON（`data.version` 应等于 `APP_VERSION`，当前为 `1.17.0`）。

### 公网验收

```bash
curl -i http://pw.pioneer.fan:84/
curl -k -i https://pw.pioneer.fan:84/
```

## 4. 当前已知运行事实

- Lucky 已将公网 `84` 端口映射到本机 `5004`
- 本项目当前运行在 Flask 开发服务器上
- 不建议直接用 `python backend/run.py`
- 当前 `main` 是唯一主干分支，`1.17.0` 是当前运行版本；`1.16.0` 保留为历史稳定标签

## 5. 常见问题

### 5.1 `ModuleNotFoundError: No module named 'backend'`
旧版本可能因直接执行 `backend/run.py` 而报错。

当前已兼容以下两种启动方式：

```bash
python -m backend.run
python backend/run.py
```

但长期维护仍建议优先使用模块方式：

```bash
python -m backend.run
```

### 5.2 公网返回 502
重点排查：

1. 本地 `5004` 是否已启动
2. Lucky 是否正常运行
3. Lucky 的 `84 -> 5004` 映射是否还在

### 5.3 WebDAV 无法播放
重点排查：

1. 存储源配置是否正确
2. WebDAV 凭证是否失效
3. 上游是否返回 302 直链
4. 目标链接是否被鉴权或过期

## 6. 推荐联动文档

- 配置说明：`docs/CONFIG_REFERENCE.md`
- 测试清单：`docs/TEST_CHECKLIST.md`
- 版本规范：`docs/VERSIONING.md`
- 存储源配置流：`docs/STORAGE_CONFIG_FLOW.md`
- 维护优先级：`docs/MAINTENANCE_TODO.md`

## 7. 当前运行文件

- 数据库：`cyber_library.db`
- 日志：`backend_server.log`
- 核心配置：`backend/config.py`
