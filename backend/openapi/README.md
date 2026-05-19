# OpenAPI Version Layout

`backend/openapi/` 目录按版本号分目录管理，后续每次接口联调或发布都沿用同一结构，避免文档散落在 `docs/` 和版本目录之间。

## 目录约定

每个版本目录统一使用：

```text
backend/openapi/
  openapi-<version>/
    openapi-<version>.json
    release-notes-<version>.md
```

当前版本：

```text
backend/openapi/openapi-1.21.0-beta/
  openapi-1.21.0-beta.json
  release-notes-1.21.0-beta.md
```

## 约定说明

- `openapi-<version>.json`
  - 当前版本的 OpenAPI 定义
- `release-notes-<version>.md`
  - 当前版本对应的接口更新说明、前后端联调说明、字段变化说明

## 使用原则

- 新版本只增不改旧目录，保持历史可追溯
- 某一版的接口说明必须和该版 OpenAPI 放在同一目录
- 通用设计文档、架构文档、运行文档继续放在 `docs/`
- 面向某一具体版本的联调说明，不再单独散落到 `docs/`

## 运行时入口

前端联调时可直接从后端读取当前契约：

- `GET /api/v1/docs`：文档索引
- `GET /api/v1/openapi.json`：当前 OpenAPI JSON 原文
- `GET /api/v1/docs/openapi.json`：OpenAPI JSON 别名
- `GET /api/v1/docs/<doc_key>`：白名单 Markdown 文档原文

这些接口返回的是固定文档文件，不支持任意路径读取。
