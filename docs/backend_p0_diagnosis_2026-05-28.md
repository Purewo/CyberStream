# CyberStream 后端 P0 事故诊断报告

> **撰写背景**：用户在 PC full 包真实使用中触发了一组数据完整性事故，链路如下：
> 改 TMDB 配置不生效 → 重启 sidecar → 替换云盘文件后重扫 → 产生幽灵 movie → 从审查工作台手动 match TMDB → 撞 UNIQUE 约束失败。
> 前端只能做兜底（toast 改文案、SQL 手动救火），三个根因都在后端。本报告只列**根因 + 证据 + 最小修复方向**，不附补丁，留给后端组拍板。
>
> 所有路径以仓库根 `G:\AI\AI_private\Cluade_code_projects\CyberStream-repo\` 为基准。

---

## P0-1 · TMDB 配置热重载失效

**现象**：`/v1/system/tmdb-config` PUT 写完 `.env.local` + `os.environ` + `backend_config.TMDB_TOKEN` + `current_app.config`，但实际请求 TMDB 时仍用旧 token / 旧 proxies，必须 kill sidecar 进程才生效。

**根因**：模块级单例 `TMDBScraper` 在 `__init__` 时把 token 和 proxies **快照到实例字段** `self.headers["Authorization"]` / `self.proxies`，之后所有调用走 `self.*` 不再回看 `config.*`。`_refresh_runtime_config()` 重写模块属性对它没影响。

**证据**

`backend/app/services/tmdb.py:11-18` 构造期快照：
```python
def __init__(self):
    self.headers = {
        "Authorization": f"Bearer {config.TMDB_TOKEN}", ...
    }
    self.session = requests.Session()
    self.session.trust_env = False
    self.proxies = getattr(config, "TMDB_PROXIES", None)
```

`backend/app/services/tmdb.py:177-183` 每次请求用 `self.*`：
```python
response = self.session.get(url, headers=self.headers,
                            params=params, proxies=self.proxies, timeout=10)
```
（注意 `tmdb.py:171` 的 `if not config.TMDB_TOKEN` guard 只能拦"清空 token"动作，**改 token / 改 proxy 都不会生效**。）

`backend/app/services/tmdb.py:445` 进程级单例：
```python
scraper = TMDBScraper()
```

被 `library_routes.py:66`、`metadata/scraper.py:5`、`metadata/nfo.py:5`、`metadata_providers/tmdb.py:6` 全部 import 复用。

**修复方向**

最小改动：`_refresh_runtime_config()` 末尾追加单例重置——
```python
from backend.app.services import tmdb as _tmdb_module
_tmdb_module.scraper.headers["Authorization"] = f"Bearer {token}"
_tmdb_module.scraper.proxies = proxies
_tmdb_module.scraper.session = requests.Session()  # 丢掉旧连接池
_tmdb_module.scraper.session.trust_env = False
```

更干净：把 `__init__` 里的快照拆到 `_get()` 方法里**每次现读 `config.*`**。session 保留即可（session 对象本身不绑 token / proxy）。

---

## P0-2 · 替换底层文件后重扫产生幽灵 movie + 死链残留

**现象**：用户云盘里把豺狼的日子整套 mkv 文件从 AMZN.WEB-DL 改名替换成 NOW.WEB-DL（**目录名不变**），重新扫描后：
- 原 movie `559e1b17` 的 10 条 `media_resources` 记录**完全没动**——path 还指向已不存在的 AMZN 文件名
- **新建了两条幽灵 movie**（`4160bbf9` / `7da5bfef`），都进了剧集审查工作台，issue 标记 `season_metadata_missing`
- 用户从 UI 没法删掉这两条幽灵

**根因**：扫描器有两个互相叠加的设计漏洞——

1. **dedup 键是 `tmdb_id`，不是 path / dir**。当外部 provider（TMDB / AniList / Bangumi）miss 时，scraper 回落到本地 fallback `loc-md5(title|year|content_type)[:12]`，title 字符串差一个 token 就生成不同 `loc-` id，每次都新建 Movie。两条幽灵的 title 分别是从脏目录名清洗失败的长版/短版（"高清剧集网发布 www TTHDTT com 豺狼的日子 全10集..." vs "...豺狼的日子"），所以产出**两个不同 loc- id**。

2. **scanner 没有 sweep stale resource 的步骤**。`scan_source` 单向 upsert，老 movie 上挂的死链 resource 没人清，UNIQUE(source_id, path) 也允许它跟新条目并存。

**证据**

`backend/app/db/database.py:91` dedup 键 = tmdb_id：
```python
movie = Movie.query.filter_by(tmdb_id=tmdb_id).first()
```

`backend/app/services/scanner.py:413` 跳过键 = 完整 path（路径变就走完整管线）：
```python
if db.is_file_processed(source_id, path):
    continue
```

`backend/app/services/metadata_scraper.py:210` fallback id 生成：
```python
return "loc-" + hashlib.md5(raw.encode()).hexdigest()[:12]
```

`backend/app/models.py:1008` issue 是**读时计算**的，不是扫描时写：
```python
if diagnostics["season_resource_count"] > 0 and not diagnostics["has_season_metadata"]:
    add_issue("season_metadata_missing", ...)
```
所以幽灵 movie 一进剧集审查工作台就挂这个 code。

**修复方向**

1. **扫描会话引入 sweep**：本次扫到的 `(source_id, parent_dir)` 下未再次出现的 `media_resources` 视作 stale，要么删除、要么 re-attach 到本轮新 movie（按 dir + season + episode 匹配）。
2. **fallback 不应直接入库**：`loc-` id 进库就是污染源。要么放隔离区让用户审 review，要么在 movie 复用时除 tmdb_id 外加 `(source_id, parent_dir, episode)` 兜底匹配。
3. **UI 侧补"幽灵 movie 强制删除"入口**：剧集审查工作台目前没有删除单条 review item 的 action（`/v1/movies/{id}` 只暴露 `OPTIONS HEAD GET PATCH`，DELETE 405）。前端 `movie.delete()` 是死代码，请求过去就 405。

**遗留未确认**

- 同一 AMZN 父目录、同一组新 NOW 文件为何会被切成两个不同 cleaned title 进入 entities——`scanner.py:461-510` 的 `_optimize_entities` / `cleaner.repair_group_title` 行为未读全。可能 filename 里"全10集 简繁英字幕"段被部分文件保留、部分剥掉，导致 phase2 分组键就裂成两个。需 cleaner 单测验证。
- 没看到 path-or-dir 级 dedup，理论上同一目录被切成 N 份就会产 N 条 loc- movie。

---

## P0-3 · 审查工作台 match_metadata 撞 TMDB UNIQUE 不会降级合并

**现象**：两条幽灵 movie 进剧集审查工作台后，用户对其中一条选「手动匹配」选了正确的 TMDB ID → 后端尝试覆写元数据 → 撞 UNIQUE 约束失败 → 弹 toast "Match failed / 不匹配"。**而普通扫描遇到同 TMDB ID 命中是会作为多 source 合并到同一个 movie 实体的**——两条路径在"目标 movie 已存在"这一步就分叉了。

**根因**：`match_metadata` apply 分支直接 `movie.tmdb_id = ...` + `commit()`，没有"目标 TMDB ID 已被其他 movie 占用"的预检；UNIQUE 约束触发 `IntegrityError` 后被宽泛 except 捕获，统一降级 `code=50010 msg="Match failed"`，**没有降级到"合并到既有 movie + 删 orphan"分支**。

**证据**

`backend/app/db/database.py:91-120` 普通扫描合并入口（dedup-by-tmdb_id + 多 source 共享 movie）：
```python
movie = Movie.query.filter_by(tmdb_id=tmdb_id).first()
if not movie:
    ...   # 新建
else:
    self._apply_movie_metadata(movie, meta_data, overwrite=False)
...
resource = MediaResource(movie_id=movie.id, source_id=source_id, path=rel_path)
db.session.add(resource)
```

`backend/app/api/library_routes.py:5084-5105` 审查工作台 apply 分支（直接覆写 + 笼统 except）：
```python
movie.tmdb_id = meta_data.get('tmdb_id') or tmdb_id   # ← 直接覆写当前 orphan
updated_fields, _ = scanner_adapter.update_movie_metadata(movie, ...)
_sync_movie_season_metadata(movie, meta_data)
db.session.commit()   # ← 撞 unique 约束
...
except Exception as e:
    db.session.rollback()
    return api_error(code=50010, msg="Match failed", http_status=500)
```

`backend/app/db/database.py:162-190` `update_movie_metadata` 只 `setattr`，不查重、不 merge：
```python
def update_movie_metadata(self, movie, meta_data, ...):
    ...
    for k, v in fields.items():
        setattr(movie, k, v)
```

`backend/app/models.py:465` UNIQUE 约束源头：
```python
tmdb_id = db.Column(..., unique=True, ...)
```

**修复方向**

1. apply 前预检：
   ```python
   existing = Movie.query.filter_by(tmdb_id=target_id).filter(Movie.id != movie.id).first()
   if existing:
       # 走合并分支
   ```
   合并分支：把当前 orphan movie 的所有 `MediaResource` reparent 到 existing，迁移相关用户态，再 delete orphan，复用 `_apply_movie_metadata(existing, meta_data, overwrite=False)`。

2. 兜底捕获 `IntegrityError` 单独分支，降级合并而非笼统 500；`code=50010` 对用户没信息量。

3. 抽 helper：`database.py:91` 那段 dedup-by-tmdb_id 的逻辑独立成函数，让普通扫描和审查工作台两条路径共享同一入口，避免双实现漂移。

**遗留未确认**

reparent 时除 `MediaResource` 外还有这些表挂 `movie_id`，迁移策略需后端按完整外键清单评估：
- `MovieMetadataLock`
- `MovieSeasonMetadata`
- `library_movie_memberships`
- `user_favorites` / `user_history`（如存在）
- `homepage_settings.hero_movie_id`（已知 nullable）

---

## 三个 P0 的关联性

```
P0-2 (dedup 漏判)
   │
   │  制造出多条挂同一物理内容的幽灵 movie
   ▼
P0-3 (合并分支缺失)
   │
   │  用户从 review 工作台想合并 → 撞 UNIQUE → 失败
   ▼
   用户被迫手动 SQL 救火

P0-1 (热重载失效)
   │
   │  独立链路，但加剧用户痛感：
   │  改 token / proxy 后还得重启 sidecar，
   │  增加触发 P0-2 的频次（每次重启都可能重扫）
```

**优先级建议**：P0-3 > P0-2 > P0-1。

- **P0-3** 单点修，影响面小、修法明确（pre-check + IntegrityError 分支），用户立刻能用 UI 救火
- **P0-2** 改面更大（fallback 策略 + sweep 步骤），但 P0-3 修了之后用户至少能从 UI 收拾烂摊子，紧迫性下降
- **P0-1** 改动最小（4-5 行），但用户已知 workaround（重启 sidecar），影响面可控

---

## 已落地的前端兜底（已 commit + push 至 origin/main）

- `frontend/src/api/core.ts` ：启动后 8s 内的网络错误静默，不弹 toast。规避 sidecar 冷启动 3-5s 期间被刷"无法连接"。
- `frontend/src/features/Profile.tsx` ：TMDB 配置保存 / 清除的 toast 文案改成"PC 单机版 / 自部署后端需重启服务后才生效"，明确告知 P0-1 的 workaround。
  > **后端修完 P0-1 后**：这两条 toast 应改回"保存即生效"——前端组在后端确认 hot-reload 真正可用后会同步调整。

## 已落地的本机数据救火（用户云盘豺狼的日子）

- 删除两条幽灵 movie + 20 条孤儿 media_resources
- canonical movie 的 10 条 resource：filename + size 改写为云盘当前真实 NOW.WEB-DL 文件，path 父目录不动
- 用户播放历史完整保留
- DB 备份保留在 `%LOCALAPPDATA%\CyberStream\cyber_library.db.before-jackal-cleanup`，72 小时无问题后可删

— 完 —
