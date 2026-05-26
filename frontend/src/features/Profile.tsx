import React, { useState, useEffect } from "react";
import {
  User,
  Shield,
  Trophy,
  Settings2,
  Hexagon,
  Lock,
  Terminal,
  Palette,
  Monitor,
  Zap,
  Check,
  Trash2,
  Save,
  Compass,
  Info,
  Github,
  ExternalLink,
} from "lucide-react";
import { MovieCard } from "../components/movies/Cards";
import { Movie, UserSettings, Achievement, AchievementSummary, HomepageUserPrefs, Library } from "../types";
import { THEMES, API_BASE, FILTERS } from "../constants";
import { formatBytes, toast } from "../utils";
import { platform } from "../platform";

import { ReviewWorkbench } from "./ReviewWorkbench";
import { ScanSourceModal } from "./ScanSourceModal";
import { AddStorageSourceModal } from "./AddStorageSourceModal";
import { HomepageEditor } from "./HomepageEditor";

const ACHIEVEMENT_ICONS: Record<string, LucideIcon> = {
  Trophy, User, Shield, Lock, Zap, Clock, Database,
  Moon, Eraser, Bookmark, Gauge, Waves, Brain, Infinity: InfinityIcon, Timer, Coffee,
  Library: LibraryIcon, Clapperboard, PartyPopper, Repeat2, Search,
  SkipForward, Captions, Languages, SlidersHorizontal,
  HardDrive, Sparkles, Image: ImageIcon, ClipboardCheck, Monitor, Film, Network,
  Pickaxe, MonitorPlay, Eye, Volume2, Laptop,
};

// 后端 icon 是 lucide 图标名字符串（如 "Trophy"）。映射不到时回落到通用图标。
function resolveAchievementIcon(name: string): LucideIcon {
  return ACHIEVEMENT_ICONS[name] || Trophy;
}

// Helper icons needed for above constant if not imported:
import {
  Clock,
  Database,
  HardDrive,
  Plus,
  Globe,
  X,
  Server,
  Cloud,
  Network,
  Box,
  Eye,
  Play,
  FolderTree,
  PlaySquare,
  FolderSearch,
  FileText,
  ChevronRight,
  ChevronLeft,
  Loader2,
  AlertTriangle,
  ScanLine,
  RefreshCw,
  // 成就图标专用——lucide 里 Infinity 是关键字、Image 跟 DOM 全局重名，所以用别名导入
  Moon,
  Eraser,
  Bookmark,
  Gauge,
  Waves,
  Brain,
  Infinity as InfinityIcon,
  Timer,
  Coffee,
  Library as LibraryIcon,
  Clapperboard,
  PartyPopper,
  Repeat2,
  Search,
  SkipForward,
  Captions,
  Languages,
  SlidersHorizontal,
  Sparkles,
  Image as ImageIcon,
  ClipboardCheck,
  Film,
  EyeOff,
  Pickaxe,
  MonitorPlay,
  Volume2,
  Laptop,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const PROTOCOLS = [
  {
    id: "LOCAL",
    name: "本地存储 (Local)",
    icon: <HardDrive size={24} />,
    desc: "服务器本地挂载磁盘或直接挂载目录",
  },
  {
    id: "SMB",
    name: "SMB / CIFS",
    icon: <Network size={24} />,
    desc: "Windows / NAS 局域网共享文件系统",
  },
  {
    id: "WEBDAV",
    name: "WebDAV",
    icon: <Cloud size={24} />,
    desc: "支持标准 WebDAV 协议的网盘或远端卷",
  },
  {
    id: "FTP",
    name: "FTP / SFTP",
    icon: <Server size={24} />,
    desc: "标准文件传输协议与高安全性终端传输隧道",
  },
  {
    id: "ALIST",
    name: "AList / OpenList",
    icon: <Box size={24} />,
    desc: "整合多种网盘与云服务的聚合路由节点",
  },
];

const BackendServerCard: React.FC = () => {
  const isPc = platform().kind === 'pc';
  const [value, setValue] = useState<string>(() => platform().getApiBase());
  const [saving, setSaving] = useState(false);
  // The Web build's API_BASE is baked in at build time, so editing is meaningless;
  // we still render the card read-only so users know which host they're hitting.
  const persist = async (next: string) => {
    if (!isPc) return;
    const cleaned = next.trim().replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(cleaned)) {
      toast.error('请输入合法的 http(s) 地址');
      return;
    }
    setSaving(true);
    try {
      const mod = await import('../platform/pc');
      mod.setApiBase(cleaned);
      toast.success('已保存。即将刷新窗口…');
      // 改后端地址需要刷整个 SPA：home / library / 当前打开的播放器都缓存了
      // 旧 API_BASE 派生的 URL（封面、字幕、stream），就地刷新最干净。
      // 留 600ms 让 toast 显示完。
      setTimeout(() => {
        try { window.location.reload(); } catch { /* noop */ }
      }, 600);
    } catch (e) {
      console.error(e);
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
      <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-2 flex items-center gap-2">
        <Hexagon size={18} /> 后端服务器
      </h3>
      <p className="text-xs text-gray-500 font-['Rajdhani'] mb-5 leading-relaxed">
        {isPc
          ? 'PC 客户端连接的后端 API 地址。保存后窗口会自动刷新。例：https://nas.local:5004/api'
          : `当前 Web 构建固定连接：${API_BASE}（如需切换请在构建时修改 API_BASE）。`}
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={!isPc}
          spellCheck={false}
          autoComplete="off"
          className="flex-1 bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white focus:border-primary outline-none disabled:opacity-60"
        />
        {isPc && (
          <button
            type="button"
            onClick={() => persist(value)}
            disabled={saving || value.trim() === platform().getApiBase()}
            className="px-4 py-2 text-sm font-bold border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? '保存中…' : '保存'}
          </button>
        )}
      </div>
    </div>
  );
};

const ProxySettingsCard: React.FC = () => {
  const isPc = platform().kind === 'pc';
  // 加载状态：null = 还没拉到；ProxyConfig = 已就绪。两类代理的初始 mode
  // 由 URL 是否非空推导（有值即视为开启自定义）。
  const [appProxyEnabled, setAppProxyEnabled] = useState(false);
  const [appProxyUrl, setAppProxyUrl] = useState('');
  const [videoProxyEnabled, setVideoProxyEnabled] = useState(false);
  const [videoProxyUrl, setVideoProxyUrl] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  // 记下进入面板时的 app_proxy，保存时跟新值比对——只在它真变了的时候
  // 才提示重启。video_proxy 改完不用重启（mpv 下次开播自然取新值）。
  const [originalAppProxy, setOriginalAppProxy] = useState<string | null>(null);

  useEffect(() => {
    if (!isPc) return;
    let cancelled = false;
    (async () => {
      try {
        const mod = await import('../platform/pc');
        const cfg = await mod.getProxyConfig();
        if (cancelled) return;
        setAppProxyEnabled(!!cfg.app_proxy);
        setAppProxyUrl(cfg.app_proxy || '');
        setVideoProxyEnabled(!!cfg.video_proxy);
        setVideoProxyUrl(cfg.video_proxy || '');
        setOriginalAppProxy(cfg.app_proxy);
        setLoaded(true);
      } catch (e) {
        console.error('读取代理配置失败', e);
        setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [isPc]);

  if (!isPc) return null;

  const validateUrl = (s: string): boolean => /^(https?|socks5):\/\/.+/i.test(s.trim());

  const persist = async () => {
    const nextApp = appProxyEnabled ? appProxyUrl.trim() : '';
    const nextVideo = videoProxyEnabled ? videoProxyUrl.trim() : '';
    if (appProxyEnabled && !validateUrl(nextApp)) {
      toast.error('应用代理地址格式不对（http://、https:// 或 socks5://）');
      return;
    }
    if (videoProxyEnabled && !validateUrl(nextVideo)) {
      toast.error('视频流代理地址格式不对（http://、https:// 或 socks5://）');
      return;
    }
    setSaving(true);
    try {
      const mod = await import('../platform/pc');
      const saved = await mod.setProxyConfig({
        app_proxy: nextApp || null,
        video_proxy: nextVideo || null,
      });
      const appProxyChanged = (saved.app_proxy || null) !== (originalAppProxy || null);
      if (appProxyChanged) {
        toast.success('代理设置已保存。应用代理改动需要重启客户端才能生效');
      } else {
        toast.success('代理设置已保存');
      }
      setOriginalAppProxy(saved.app_proxy || null);
      // 暗网客成就：配置过任意一档自定义代理（应用代理或视频流代理）即解锁。
      if (saved.app_proxy || saved.video_proxy) {
        const { unlockBehaviorAchievement } = await import('../api');
        unlockBehaviorAchievement('dark_web');
      }
    } catch (e) {
      console.error(e);
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  // 子卡片：一个独立代理项（开关 + URL 输入）。
  const renderProxyBlock = (
    title: string,
    desc: string,
    enabled: boolean,
    setEnabled: (v: boolean) => void,
    url: string,
    setUrl: (v: string) => void,
    placeholder: string,
  ) => (
    <div className="border border-white/5 bg-black/30 p-4 rounded">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm font-['Orbitron'] text-white tracking-wider">{title}</div>
          <div className="text-[11px] text-gray-500 font-['Rajdhani'] mt-1 leading-relaxed">{desc}</div>
        </div>
        <button
          type="button"
          onClick={() => setEnabled(!enabled)}
          className={`shrink-0 w-10 h-5 rounded-full relative transition-colors ${enabled ? 'bg-primary' : 'bg-gray-700'}`}
        >
          <div className={`absolute top-1 w-3 h-3 bg-black rounded-full transition-all ${enabled ? 'left-6' : 'left-1'}`}></div>
        </button>
      </div>
      {enabled && (
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder={placeholder}
          spellCheck={false}
          autoComplete="off"
          className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white focus:border-primary outline-none"
        />
      )}
    </div>
  );

  return (
    <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
      <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-2 flex items-center gap-2">
        <Globe size={18} /> 代理设置
      </h3>
      <p className="text-xs text-gray-500 font-['Rajdhani'] mb-5 leading-relaxed">
        应用代理与视频流代理独立配置。改完后保存，应用代理变更需重启客户端才能生效；视频流代理下一次播放自动应用。
      </p>
      {!loaded ? (
        <div className="text-xs text-gray-500 font-['Rajdhani']">加载中…</div>
      ) : (
        <div className="space-y-3">
          {renderProxyBlock(
            '应用代理 · API 与静态资源',
            '电影列表、播放历史、封面图、字幕等所有 API 与图片请求。改动需重启客户端。',
            appProxyEnabled,
            setAppProxyEnabled,
            appProxyUrl,
            setAppProxyUrl,
            'http://127.0.0.1:7890',
          )}
          {renderProxyBlock(
            '视频流代理 · 内置播放器',
            '原生播放器拉流时使用。下次开始播放即生效。多数局域网/直连场景无需开启。',
            videoProxyEnabled,
            setVideoProxyEnabled,
            videoProxyUrl,
            setVideoProxyUrl,
            'socks5://127.0.0.1:1080',
          )}
        </div>
      )}
      <div className="mt-5">
        <button
          type="button"
          onClick={persist}
          disabled={saving || !loaded}
          className="px-4 py-2 text-sm font-bold border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </div>
  );
};

const TmdbSettingsCard: React.FC = () => {
  // TMDB 配置面板：必须配 token 才能正经刮削；代理可选但国内基本必走代理
  // 才能稳定访问 image.tmdb.org / api.themoviedb.org。
  //
  // 前后端只走 .env.local 这一个真值入口；UI 永远不显示明文 token，
  // 后端 GET 也只回 token_set:bool。token 输入框 placeholder 在 token_set
  // 时显示「已配置（输入新值可覆盖）」，避免用户以为没配。
  const [tokenInput, setTokenInput] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [tokenSet, setTokenSet] = useState(false);
  const [proxyEnabled, setProxyEnabled] = useState(true);
  const [proxyUrl, setProxyUrl] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { systemService } = await import("../api");
        const cfg = await systemService.getTmdbConfig();
        if (cancelled) return;
        if (cfg) {
          setTokenSet(!!cfg.token_set);
          setProxyEnabled(!!cfg.proxy_enabled);
          setProxyUrl(cfg.proxy_url || "");
        }
        setLoaded(true);
      } catch (e) {
        console.error("读取 TMDB 配置失败", e);
        setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const validateUrl = (s: string): boolean => /^(https?|socks5):\/\/.+/i.test(s.trim());

  const persist = async () => {
    // token 提交规则：只在用户真输入了新值时才带上 token 字段，否则保留
    // 后端原值（避免空字符串误清空已配置的 token）。
    const patch: any = {};
    const newToken = tokenInput.trim();
    if (newToken) {
      patch.token = newToken;
    }
    patch.proxy_enabled = proxyEnabled;
    if (proxyEnabled) {
      const url = proxyUrl.trim();
      if (!validateUrl(url)) {
        toast.error("代理地址格式不对（应以 http://、https:// 或 socks5:// 开头）");
        return;
      }
      patch.proxy_url = url;
    }

    setSaving(true);
    try {
      const { systemService } = await import("../api");
      const res = await systemService.setTmdbConfig(patch);
      if (!res.ok) {
        toast.error(res.msg || "保存失败");
        return;
      }
      const data = res.data || {};
      if (data.token_set !== undefined) setTokenSet(!!data.token_set);
      setTokenInput("");
      toast.success("TMDB 配置已保存（下次扫描立刻生效）");
    } catch (e) {
      console.error(e);
      toast.error("保存失败");
    } finally {
      setSaving(false);
    }
  };

  const clearToken = async () => {
    setSaving(true);
    try {
      const { systemService } = await import("../api");
      const res = await systemService.setTmdbConfig({ token: null });
      if (!res.ok) {
        toast.error(res.msg || "清除失败");
        return;
      }
      setTokenSet(false);
      setTokenInput("");
      toast.success("TMDB token 已清除");
    } catch (e) {
      console.error(e);
      toast.error("清除失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
      <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-2 flex items-center gap-2">
        <Film size={18} /> TMDB 元数据
      </h3>
      <p className="text-xs text-gray-500 font-['Rajdhani'] mb-5 leading-relaxed">
        TMDB 是影视刮削的主力数据源。必须配置 v4 Bearer Token 才能拿到海报、
        简介、评分；国内访问 themoviedb.org 一般要走代理。配置写入
        .env.local，下次扫描立刻生效。
      </p>

      {/* Token */}
      <div className="border border-white/5 bg-black/30 p-4 rounded mb-3">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-['Orbitron'] text-white tracking-wider">
              TMDB Token
              {tokenSet && !tokenInput && (
                <span className="ml-2 text-[10px] text-primary font-['Rajdhani'] tracking-widest">
                  ● 已配置
                </span>
              )}
            </div>
            <div className="text-[11px] text-gray-500 font-['Rajdhani'] mt-1 leading-relaxed">
              themoviedb.org → 设置 → API → API Read Access Token (v4)
            </div>
          </div>
          {tokenSet && !tokenInput && (
            <button
              type="button"
              onClick={clearToken}
              disabled={saving}
              className="shrink-0 px-2 py-1 text-[11px] font-['Rajdhani'] tracking-widest border border-red-500/40 text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-40"
            >
              清除
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <input
            type={showToken ? "text" : "password"}
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder={tokenSet ? "已配置（输入新值可覆盖）" : "粘贴你的 v4 Bearer Token…"}
            spellCheck={false}
            autoComplete="off"
            className="flex-1 bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white focus:border-primary outline-none"
          />
          <button
            type="button"
            onClick={() => setShowToken(!showToken)}
            className="px-3 border border-white/10 text-gray-400 hover:text-white hover:border-white/30 transition-colors"
            title={showToken ? "隐藏" : "显示"}
          >
            {showToken ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </div>

      {/* Proxy */}
      <div className="border border-white/5 bg-black/30 p-4 rounded mb-4">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-['Orbitron'] text-white tracking-wider">TMDB 代理</div>
            <div className="text-[11px] text-gray-500 font-['Rajdhani'] mt-1 leading-relaxed">
              访问 themoviedb.org 用的代理。不影响其他流量，仅 TMDB API + 海报下载。
            </div>
          </div>
          <button
            type="button"
            onClick={() => setProxyEnabled(!proxyEnabled)}
            className={`shrink-0 w-10 h-5 rounded-full relative transition-colors ${
              proxyEnabled ? "bg-primary" : "bg-gray-700"
            }`}
          >
            <div
              className={`absolute top-1 w-3 h-3 bg-black rounded-full transition-all ${
                proxyEnabled ? "left-6" : "left-1"
              }`}
            ></div>
          </button>
        </div>
        {proxyEnabled && (
          <input
            type="text"
            value={proxyUrl}
            onChange={(e) => setProxyUrl(e.target.value)}
            placeholder="http://127.0.0.1:10808 / socks5://127.0.0.1:10808"
            spellCheck={false}
            autoComplete="off"
            className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white focus:border-primary outline-none"
          />
        )}
      </div>

      <button
        type="button"
        onClick={persist}
        disabled={!loaded || saving}
        className="w-full px-4 py-2 text-sm font-bold border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {saving ? "保存中…" : "保存"}
      </button>
    </div>
  );
};

// 前端发布版本：跟 frontend/package.json 的 version 字段保持一致。后端无对应
// 构建注入字段，所以这里硬编码；下次发版时一并更新。
const FRONTEND_VERSION = '1.21.1';
const REPO_URL = 'https://github.com/Purewo/CyberStream';
const RELEASES_URL = 'https://github.com/Purewo/CyberStream/releases';
const ISSUES_URL = 'https://github.com/Purewo/CyberStream/issues';

const AboutCard: React.FC = () => {
  const [backendVersion, setBackendVersion] = useState<string | null>(null);
  const [openapiVersion, setOpenapiVersion] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 后端官方更新检查结果。null = 还没查 / 不可用；对象 = 拿到了响应。
  const [updateInfo, setUpdateInfo] = useState<import('../api/system').UpdateCheckResponse | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [pcRelease, setPcRelease] = useState<string | null>(null);
  const isPc = platform().kind === 'pc';

  useEffect(() => {
    if (!isPc) return;
    let cancelled = false;
    import('../platform/pc').then(({ getPcRelease }) => {
      if (!cancelled) setPcRelease(getPcRelease());
    }).catch(() => { /* web 模式动态 import 失败，忽略 */ });
    return () => { cancelled = true; };
  }, [isPc]);

  const fetchBackend = async () => {
    setChecking(true);
    setError(null);
    setUpdateError(null);
    try {
      const { systemService } = await import('../api');
      const info = await systemService.getDocsInfo();
      if (info && info.version) {
        setBackendVersion(info.version);
        setOpenapiVersion(info.openapi_version || null);
      } else {
        setError('未能获取后端版本');
      }
      // 顺带拉一次后端官方"是否有更新"。失败不阻塞前后端版本对比展示。
      // current_release 仅 PC 有意义，web 端不传走 web 默认。
      try {
        let currentRelease: string | undefined;
        if (isPc) {
          const { getPcRelease } = await import('../platform/pc');
          currentRelease = getPcRelease();
        }
        const upd = await systemService.checkUpdate({
          currentVersion: FRONTEND_VERSION,
          currentRelease,
          platform: isPc ? 'windows' : undefined,
          arch: isPc ? 'x64' : undefined,
        });
        if (upd) {
          setUpdateInfo(upd);
        } else {
          setUpdateError('后端未返回更新检查结果');
        }
      } catch (e) {
        console.warn('checkUpdate failed', e);
        setUpdateError('更新检查失败');
      }
    } catch (e) {
      console.error(e);
      setError('网络异常，无法连接后端');
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    fetchBackend();
  }, []);

  // 简单语义化对比：相同视为同步；不同就提示。这是前端 vs 当前连接的后端，
  // 不是和上游 GitHub 比；GitHub 那边的对比由 updateInfo 单独显示。
  const inSync = backendVersion !== null && backendVersion === FRONTEND_VERSION;

  const openExternal = async (url: string) => {
    try {
      const { platform: p } = await import('../platform');
      if (p().kind === 'pc') {
        const mod = await import('@tauri-apps/plugin-shell');
        await mod.open(url);
        return;
      }
    } catch (e) {
      // fallthrough to window.open
    }
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  const downloadUpdate = async () => {
    const dl = updateInfo?.selected_download;
    if (!dl?.url) {
      toast.error('当前没有推荐的下载项');
      return;
    }
    await openExternal(dl.url);
  };

  // 后端不直接返 update_available，靠 current.release vs latest.release 判定。
  // 两者都缺时退回 version 比较；都缺就当作"无信息可判断"，按最新处理。
  const updateAvailable = (() => {
    if (!updateInfo?.latest) return false;
    const cur = updateInfo.current?.release || updateInfo.current?.version;
    const lat = updateInfo.latest.release || updateInfo.latest.version;
    if (!cur || !lat) return false;
    return cur !== lat;
  })();

  return (
    <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
      <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-2 flex items-center gap-2">
        <Info size={18} /> 关于 CyberStream
      </h3>
      <p className="text-xs text-gray-500 font-['Rajdhani'] mb-5 leading-relaxed">
        个人媒体库系统，开源协议见仓库。GitHub 在国内访问可能不稳定，建议自备代理。
      </p>

      {/* 版本信息 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-5">
        <div className="border border-white/5 bg-black/30 px-4 py-3 rounded">
          <div className="text-[10px] text-gray-500 font-['Orbitron'] tracking-widest mb-1">前端版本</div>
          <div className="font-mono text-base text-white">{FRONTEND_VERSION}</div>
        </div>
        <div className="border border-white/5 bg-black/30 px-4 py-3 rounded">
          <div className="text-[10px] text-gray-500 font-['Orbitron'] tracking-widest mb-1 flex items-center justify-between">
            <span>后端版本</span>
            {openapiVersion && (
              <span className="text-[9px] text-gray-600 font-['Rajdhani']">OpenAPI {openapiVersion}</span>
            )}
          </div>
          <div className="font-mono text-base text-white">
            {checking && backendVersion === null ? (
              <span className="text-gray-500 text-sm">检测中…</span>
            ) : backendVersion ? (
              backendVersion
            ) : (
              <span className="text-red-400 text-sm">未连接</span>
            )}
          </div>
        </div>
      </div>

      {/* 同步状态横幅 */}
      <div
        className={`text-xs px-3 py-2 rounded mb-4 border flex items-center gap-2 ${
          backendVersion === null
            ? 'border-white/10 bg-black/30 text-gray-400'
            : inSync
              ? 'border-green-500/30 bg-green-500/5 text-green-400'
              : 'border-amber-500/30 bg-amber-500/5 text-amber-400'
        }`}
      >
        {backendVersion === null ? (
          error || '正在检测后端连接…'
        ) : inSync ? (
          <>
            <Check size={14} /> 前后端版本一致，运行环境同步
          </>
        ) : (
          <>
            <Info size={14} />
            前端 {FRONTEND_VERSION} ≠ 后端 {backendVersion}，建议升级到一致版本
          </>
        )}
      </div>

      {/* 操作按钮 */}
      <div className="flex flex-wrap gap-2 mb-5">
        <button
          type="button"
          onClick={fetchBackend}
          disabled={checking}
          className="px-4 py-2 text-xs font-bold border border-primary/50 text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
          {checking ? '检测中…' : '检查更新'}
        </button>
        {updateAvailable && updateInfo?.selected_download?.url && (
          <button
            type="button"
            onClick={downloadUpdate}
            className="px-4 py-2 text-xs font-bold border border-amber-400 bg-amber-400/10 text-amber-300 hover:bg-amber-400 hover:text-black transition-colors flex items-center gap-2"
          >
            <ExternalLink size={14} /> 下载新版本
            {updateInfo.latest?.release || updateInfo.latest?.version
              ? ` ${updateInfo.latest.release || updateInfo.latest.version}`
              : ''}
          </button>
        )}
        <button
          type="button"
          onClick={() => openExternal(RELEASES_URL)}
          className="px-4 py-2 text-xs font-bold border border-white/10 text-gray-300 hover:bg-white/10 transition-colors flex items-center gap-2"
        >
          <ExternalLink size={14} /> 发布列表
        </button>
        <button
          type="button"
          onClick={() => openExternal(REPO_URL)}
          className="px-4 py-2 text-xs font-bold border border-white/10 text-gray-300 hover:bg-white/10 transition-colors flex items-center gap-2"
        >
          <Github size={14} /> 开源仓库
        </button>
        <button
          type="button"
          onClick={() => openExternal(ISSUES_URL)}
          className="px-4 py-2 text-xs font-bold border border-white/10 text-gray-300 hover:bg-white/10 transition-colors flex items-center gap-2"
        >
          <ExternalLink size={14} /> 问题反馈
        </button>
      </div>

      {/* 后端官方更新检查结果 —— 后端发布系统只回认可的 CDN 地址，前端不再自拼 */}
      {updateInfo && (
        <div
          className={`text-xs px-3 py-2 rounded mb-4 border ${
            updateAvailable
              ? 'border-amber-500/30 bg-amber-500/5 text-amber-300'
              : 'border-green-500/30 bg-green-500/5 text-green-400'
          }`}
        >
          <div className="flex items-center gap-2 mb-1">
            {updateAvailable ? (
              <>
                <Info size={14} />
                <span>
                  发现新版本：{updateInfo.latest?.release || updateInfo.latest?.version}
                  {updateInfo.latest?.released_at && (
                    <span className="ml-2 text-[10px] text-gray-500">
                      （{new Date(updateInfo.latest.released_at).toLocaleDateString('zh-CN')}）
                    </span>
                  )}
                </span>
              </>
            ) : (
              <>
                <Check size={14} /> 当前已是最新版本
              </>
            )}
          </div>
          {updateAvailable && updateInfo.selected_download && (
            <div className="text-[10px] text-gray-500 font-['Rajdhani'] leading-relaxed">
              推荐下载：{updateInfo.selected_download.label || updateInfo.selected_download.variant} ·{' '}
              {updateInfo.selected_download.name || updateInfo.selected_download.url}
              {updateInfo.selected_download.size && (
                <span className="ml-1">（{formatBytes(updateInfo.selected_download.size)}）</span>
              )}
            </div>
          )}
          {updateAvailable && updateInfo.latest?.notes && (
            <div className="text-[10px] text-gray-500 font-['Rajdhani'] mt-1 leading-relaxed">
              {updateInfo.latest.notes}
            </div>
          )}
          {updateInfo.warnings && updateInfo.warnings.length > 0 && (
            <div className="text-[10px] text-gray-500 font-['Rajdhani'] mt-1">
              {updateInfo.warnings.map((w, i) => (
                <div key={i}>· {w}</div>
              ))}
            </div>
          )}
        </div>
      )}
      {!updateInfo && updateError && (
        <div className="text-[11px] text-gray-500 font-['Rajdhani'] mb-4">
          {updateError}（仅前后端版本对比可用）
        </div>
      )}

      <div className="mt-5 pt-4 border-t border-white/5 text-[11px] text-gray-500 font-['Rajdhani'] leading-relaxed">
          {isPc ? (
            <>当前 PC 发行：{pcRelease || FRONTEND_VERSION}。下载链接由后端发布系统筛选，仅返回认可的 CDN 安装包地址。</>
          ) : (
            <>新版本发布后请到「发布列表」手动下载替换，或自行从仓库拉取构建。</>
          )}
      </div>
    </div>
  );
};

// ─── 保险库面板 ───
//
// 后端把"收藏 = 保险库"，访问受 PIN 保护：
//   1. configured=false  → 必须先设置 6 位 PIN
//   2. configured=true && unlocked=false → 用 PIN 解锁
//   3. unlocked=true     → 显示真实收藏列表
//   4. locked=true       → 24h 改 PIN 限额耗尽，整个保险库被锁
//
// 状态由 useUserData.vaultState 提供；本组件负责 PIN 输入 / 调接口 /
// 解锁后拉真实 favorites。
interface VaultPanelProps {
  favorites: Movie[];
  onMovieSelect: (m: Movie) => void;
  onToggleFavorite: (m: Movie) => void;
  vaultState: import('../api/user').VaultAccessState | null;
  onRefreshVaultStatus: () => Promise<import('../api/user').VaultAccessState | null>;
  onRefreshFavorites: () => Promise<void>;
}

const VaultPanel: React.FC<VaultPanelProps> = ({
  favorites,
  onMovieSelect,
  onToggleFavorite,
  vaultState,
  onRefreshVaultStatus,
  onRefreshFavorites,
}) => {
  // PIN 输入态：setup（首次/重设）/ unlock（已配置则解锁）。
  const [pin, setPin] = useState('');
  const [pin2, setPin2] = useState('');
  const [currentPin, setCurrentPin] = useState('');
  const [busy, setBusy] = useState(false);
  // 用户主动点了「修改 PIN」时切到 setup 流程（已 unlocked 状态下）
  const [changing, setChanging] = useState(false);

  if (!vaultState) {
    // 没权限（普通用户）或还没拉到——给个无干扰提示
    return (
      <div className="animate-in slide-in-from-right-4 fade-in duration-300">
        <div className="h-64 border border-white/10 bg-[#0a0a12]/40 flex flex-col items-center justify-center text-gray-600 gap-4">
          <Shield size={48} className="opacity-20" />
          <span className="font-['Orbitron'] tracking-widest">数据保险库不可用</span>
          <span className="text-xs text-gray-500">请使用管理员账户登录后访问</span>
        </div>
      </div>
    );
  }

  const validPin = (s: string) => /^\d{6}$/.test(s);

  const submitSetup = async () => {
    if (!validPin(pin)) {
      toast.error('PIN 必须是 6 位数字');
      return;
    }
    if (pin !== pin2) {
      toast.error('两次输入的 PIN 不一致');
      return;
    }
    if (changing && !validPin(currentPin)) {
      toast.error('请输入当前 PIN');
      return;
    }
    setBusy(true);
    try {
      const { userService } = await import('../api');
      await userService.setVaultPin({
        newPin: pin,
        currentPin: changing ? currentPin : undefined,
      });
      toast.success(changing ? '已更新 PIN，保险库已解锁' : '已设置 PIN，保险库已解锁');
      setPin(''); setPin2(''); setCurrentPin(''); setChanging(false);
      await onRefreshVaultStatus();
      await onRefreshFavorites();
    } catch (e: any) {
      // 后端 400/403/423 都用同一文案场景区分
      const http = e?.http;
      const msg: string = e?.message || '';
      if (http === 423) {
        toast.error('保险库已锁定，请稍后再试');
      } else if (http === 400 && /password|登录密码/i.test(msg)) {
        toast.error('PIN 不能与登录密码相同');
      } else if (http === 400 && /current/i.test(msg)) {
        toast.error('当前 PIN 不正确');
      } else {
        toast.error(msg || '设置 PIN 失败');
      }
      // 限额计数可能因失败也走了一次，刷一下
      onRefreshVaultStatus();
    } finally {
      setBusy(false);
    }
  };

  const submitUnlock = async () => {
    if (!validPin(pin)) {
      toast.error('PIN 必须是 6 位数字');
      return;
    }
    setBusy(true);
    try {
      const { userService } = await import('../api');
      await userService.unlockVault(pin);
      toast.success('保险库已解锁');
      setPin('');
      await onRefreshVaultStatus();
      await onRefreshFavorites();
    } catch (e: any) {
      if (e?.http === 423) toast.error('保险库已锁定，请稍后再试');
      else toast.error('PIN 不正确');
    } finally {
      setBusy(false);
    }
  };

  const lockNow = async () => {
    setBusy(true);
    try {
      const { userService } = await import('../api');
      await userService.lockVault();
      toast.success('保险库已锁定');
      await onRefreshVaultStatus();
    } finally {
      setBusy(false);
    }
  };

  // ─── 渲染 ───
  return (
    <div className="space-y-6 animate-in slide-in-from-right-4 fade-in duration-300">
      <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
        <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-2 flex items-center gap-2">
          <Shield size={18} /> 数据保险库
        </h3>
        <p className="text-xs text-gray-500 font-['Rajdhani'] mb-5 leading-relaxed">
          收藏夹由 6 位数字 PIN 保护。每 24 小时最多修改 {vaultState.pin_change_limit_per_day} 次 PIN，
          超限将临时锁定。
        </p>

        {vaultState.locked ? (
          <div className="border border-red-500/30 bg-red-500/5 p-4 rounded text-sm text-red-300">
            保险库已被锁定（PIN 修改超限）。
            {vaultState.locked_until && (
              <> 解锁时间：{new Date(vaultState.locked_until).toLocaleString()}</>
            )}
          </div>
        ) : !vaultState.configured ? (
          // 首次设置 PIN
          <div className="space-y-3">
            <p className="text-xs text-gray-400">首次使用，请设置 6 位数字 PIN：</p>
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
              placeholder="6 位数字 PIN"
              className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white tracking-[0.5em] focus:border-primary outline-none"
            />
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              value={pin2}
              onChange={(e) => setPin2(e.target.value.replace(/\D/g, ''))}
              placeholder="再输一次 PIN 确认"
              className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white tracking-[0.5em] focus:border-primary outline-none"
            />
            <button
              onClick={submitSetup}
              disabled={busy}
              className="px-4 py-2 text-sm font-bold border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-40"
            >
              {busy ? '设置中…' : '设置 PIN'}
            </button>
          </div>
        ) : !vaultState.unlocked ? (
          // 已配置但未解锁
          <div className="space-y-3">
            <p className="text-xs text-gray-400">输入 6 位数字 PIN 解锁：</p>
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
              onKeyDown={(e) => { if (e.key === 'Enter') submitUnlock(); }}
              placeholder="PIN"
              className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white tracking-[0.5em] focus:border-primary outline-none"
            />
            <button
              onClick={submitUnlock}
              disabled={busy}
              className="px-4 py-2 text-sm font-bold border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-40"
            >
              {busy ? '解锁中…' : '解锁'}
            </button>
          </div>
        ) : changing ? (
          // 已解锁，正在改 PIN
          <div className="space-y-3">
            <p className="text-xs text-gray-400">
              修改 PIN（今日剩余 {vaultState.pin_changes_remaining_today} 次）：
            </p>
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              value={currentPin}
              onChange={(e) => setCurrentPin(e.target.value.replace(/\D/g, ''))}
              placeholder="当前 PIN"
              className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white tracking-[0.5em] focus:border-primary outline-none"
            />
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
              placeholder="新 PIN"
              className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white tracking-[0.5em] focus:border-primary outline-none"
            />
            <input
              type="password"
              inputMode="numeric"
              maxLength={6}
              value={pin2}
              onChange={(e) => setPin2(e.target.value.replace(/\D/g, ''))}
              placeholder="再输一次确认"
              className="w-full bg-black/40 border border-white/10 px-3 py-2 text-sm font-mono text-white tracking-[0.5em] focus:border-primary outline-none"
            />
            <div className="flex gap-2">
              <button
                onClick={submitSetup}
                disabled={busy}
                className="px-4 py-2 text-sm font-bold border border-primary text-primary hover:bg-primary hover:text-black transition-colors disabled:opacity-40"
              >
                {busy ? '保存中…' : '保存新 PIN'}
              </button>
              <button
                onClick={() => { setChanging(false); setPin(''); setPin2(''); setCurrentPin(''); }}
                className="px-4 py-2 text-sm border border-white/10 text-gray-400 hover:bg-white/5"
              >
                取消
              </button>
            </div>
          </div>
        ) : (
          // 已解锁
          <div className="flex items-center gap-3 text-sm">
            <div className="px-2 py-0.5 border border-green-500/30 bg-green-500/10 text-green-400 text-xs font-mono">
              已解锁
            </div>
            <button
              onClick={() => setChanging(true)}
              className="px-3 py-1.5 text-xs border border-white/10 text-gray-300 hover:bg-white/5"
            >
              修改 PIN
            </button>
            <button
              onClick={lockNow}
              disabled={busy}
              className="px-3 py-1.5 text-xs border border-white/10 text-gray-300 hover:bg-white/5 disabled:opacity-40"
            >
              立即锁定
            </button>
          </div>
        )}
      </div>

      {/* 解锁后展示真实收藏列表 */}
      {vaultState.unlocked && !changing && (
        favorites.length === 0 ? (
          <div className="h-64 border border-white/10 bg-[#0a0a12]/40 flex flex-col items-center justify-center text-gray-600 gap-4">
            <Shield size={48} className="opacity-20" />
            <span className="font-['Orbitron'] tracking-widest">还没有收藏</span>
            <span className="text-xs text-gray-500">在影片详情页点击红心即可收藏</span>
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] md:grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4 md:gap-6 justify-center">
            {favorites.map((movie) => (
              <div key={movie.id} className="relative group">
                <MovieCard
                  movie={movie}
                  category={{ colorClass: "border-white/20" }}
                  onClick={onMovieSelect}
                />
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleFavorite(movie);
                  }}
                  className="absolute top-2 right-2 p-2 bg-black/80 border border-red-500 text-red-500 opacity-0 group-hover:opacity-100 transition-opacity z-30 hover:bg-red-500 hover:text-black"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
};

const PersonalPreferencesCard: React.FC<{
  settings: UserSettings;
  setSettings: (s: UserSettings) => void;
  libraries: Library[];
}> = ({ settings, setSettings, libraries }) => {
  const prefs: HomepageUserPrefs = settings.homepage || {};
  const update = (patch: Partial<HomepageUserPrefs>) => {
    setSettings({ ...settings, homepage: { ...prefs, ...patch } });
  };
  const updateLibraryDefaults = (
    patch: Partial<NonNullable<HomepageUserPrefs['libraryDefaults']>>
  ) => {
    update({ libraryDefaults: { ...(prefs.libraryDefaults || {}), ...patch } });
  };

  // 启动入口下拉值。`library:<id>` 字符串编码到 select.value 里。
  const landingValue: string = prefs.defaultLanding || 'home';

  return (
    <div className="bg-[#0a0a12]/80 border border-white/10 p-6 space-y-5">
      <h3 className="text-lg font-['Orbitron'] font-bold text-white flex items-center gap-2">
        <Compass size={18} /> 个人偏好
      </h3>
      <p className="text-xs text-gray-500 leading-relaxed">
        仅影响本机本人。和上方"首屏大海报 / 首页分类"那两个全局配置是两件事。
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
        {/* 启动默认进入 */}
        <label className="flex flex-col gap-1.5">
          <span className="text-gray-400">启动默认进入</span>
          <select
            value={landingValue}
            onChange={(e) => {
              const v = e.target.value;
              if (v === 'home' || v === 'library') {
                update({ defaultLanding: v });
              } else if (v.startsWith('library:')) {
                update({ defaultLanding: v as `library:${number}` });
              }
            }}
            className="bg-black/40 border border-white/10 px-2 py-1.5 text-white outline-none"
          >
            <option value="home">首页</option>
            <option value="library">媒体库（全部）</option>
            {libraries.map((lib) => (
              <option key={lib.id} value={`library:${lib.id}`}>
                库 · {lib.name}
              </option>
            ))}
          </select>
        </label>

        {/* 库默认类型 */}
        <label className="flex flex-col gap-1.5">
          <span className="text-gray-400">库默认类型</span>
          <input
            type="text"
            value={prefs.libraryDefaults?.type || ''}
            onChange={(e) => updateLibraryDefaults({ type: e.target.value })}
            placeholder="留空=全部类型"
            className="bg-black/40 border border-white/10 px-2 py-1.5 text-white outline-none"
          />
        </label>

        {/* 库默认排序 */}
        <label className="flex flex-col gap-1.5">
          <span className="text-gray-400">库默认排序</span>
          <select
            value={prefs.libraryDefaults?.sort || 'update_time'}
            onChange={(e) => updateLibraryDefaults({ sort: e.target.value })}
            className="bg-black/40 border border-white/10 px-2 py-1.5 text-white outline-none"
          >
            {FILTERS.sorts.map((s: { id: string; label: string }) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
};

interface ProfilePageProps {
  settings: UserSettings;
  setSettings: (s: UserSettings) => void;
  favorites: Movie[];
  onMovieSelect: (m: Movie) => void;
  onToggleFavorite: (m: Movie) => void;
  currentTheme: string;
  setTheme: (t: string) => void;
  libraries?: import("../types").Library[];
  onRefreshLibraries?: () => Promise<void>;
  initialTab?: string;
  // 保险库会话态。整个 app 共享，从 useUserData 透传过来
  vaultState?: import('../api/user').VaultAccessState | null;
  onRefreshVaultStatus?: () => Promise<import('../api/user').VaultAccessState | null>;
  onRefreshFavorites?: () => Promise<void>;
}

export const ProfilePage: React.FC<ProfilePageProps> = ({
  settings,
  setSettings,
  favorites,
  onMovieSelect,
  onToggleFavorite,
  currentTheme,
  setTheme,
  libraries = [],
  onRefreshLibraries = async () => {},
  initialTab = "IDENTITY",
  vaultState = null,
  onRefreshVaultStatus = async () => null,
  onRefreshFavorites = async () => {},
}) => {
  const [activeTab, setActiveTab] = useState(initialTab);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  const [scanningSource, setScanningSource] = useState<{ id: number; name: string } | null>(null);

  // 成就：进 MEDALS tab 时按需加载，POST /unlock 后 dirty 标记触发刷新
  const [achievements, setAchievements] = useState<Achievement[]>([]);
  const [achievementSummary, setAchievementSummary] = useState<AchievementSummary | null>(null);
  const [achievementsLoading, setAchievementsLoading] = useState(false);
  useEffect(() => {
    if (activeTab !== 'MEDALS') return;
    let cancelled = false;
    (async () => {
      setAchievementsLoading(true);
      try {
        const { userService } = await import('../api');
        const { items, summary } = await userService.getAchievements();
        if (cancelled) return;
        setAchievements(items);
        setAchievementSummary(summary);
      } finally {
        if (!cancelled) setAchievementsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [activeTab]);

  const [confirmAction, setConfirmAction] = useState<{
    message: string;
    desc?: string;
    onConfirm: () => void;
  } | null>(null);
  const [providerTypes, setProviderTypes] = useState<
    import("../types").StorageProviderType[]
  >([]);
  const [storageSources, setStorageSources] = useState<
    import("../types").StorageSource[]
  >([]);
  const [isAddingResource, setIsAddingResource] = useState(false);
  const [selectedProtocol, setSelectedProtocol] = useState<
    import("../types").StorageProviderType | null
  >(null);

  const [newSourceName, setNewSourceName] = useState("");
  const [newSourceConfig, setNewSourceConfig] = useState<Record<string, any>>(
    {},
  );

  const [isAddingLibrary, setIsAddingLibrary] = useState(false);
  const [newLibraryName, setNewLibraryName] = useState("");
  const [newLibraryDescription, setNewLibraryDescription] = useState("");

  const [editingLibraryId, setEditingLibraryId] = useState<number | null>(null);
  const [editingLibraryName, setEditingLibraryName] = useState("");
  const [editingLibraryDescription, setEditingLibraryDescription] =
    useState("");

  const [bindingLibraryId, setBindingLibraryId] = useState<number | null>(null);
  const [bindingSourceId, setBindingSourceId] = useState<number | null>(null);

  const [libraryBindings, setLibraryBindings] = useState<
    Record<number, import("../types").LibrarySourceBinding[]>
  >({});
  const [bindBrowseData, setBindBrowseData] = useState<
    import("../types").FileItem[] | null
  >(null);
  const [bindBrowsePath, setBindBrowsePath] = useState<string>("/");
  const [isBindBrowsing, setIsBindBrowsing] = useState(false);
  const [bindError, setBindError] = useState<string | null>(null);

  // General source preview state
  const [previewingSourceId, setPreviewingSourceId] = useState<number | null>(
    null,
  );
  const [previewingSourceName, setPreviewingSourceName] = useState<string>("");

  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewData, setPreviewData] = useState<
    import("../types").FileItem[] | null
  >(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewPath, setPreviewPath] = useState<string>("/");

  const loadResources = async () => {
    try {
      const { storageService } = await import("../api");
      const [ptypes, sources] = await Promise.all([
        storageService.getProviderTypes(),
        storageService.getSources(),
      ]);
      setProviderTypes(ptypes);

      // Initialize sources in checking state
      setStorageSources(
        sources.map((s: any) => ({
          ...s,
          health: { status: "checking", reason: "连接测试中..." },
        })),
      );

      // Fire independent background health checks
      sources.forEach((source: any) => {
        storageService
          .checkHealth(source.id)
          .then((health) => {
            setStorageSources((prev) =>
              prev.map((s: any) =>
                s.id === source.id
                  ? {
                      ...s,
                      health: health || {
                        status: "offline",
                        reason: "Timeout",
                      },
                    }
                  : s,
              ),
            );
          })
          .catch(() => {
            setStorageSources((prev) =>
              prev.map((s: any) =>
                s.id === source.id
                  ? {
                      ...s,
                      health: { status: "offline", reason: "Error connecting" },
                    }
                  : s,
              ),
            );
          });
      });
    } catch (e) {
      console.error("Failed to load storage resources", e);
    }
  };

  const loadBindings = async () => {
    const { libraryService } = await import("../api");
    const newBindings: Record<
      number,
      import("../types").LibrarySourceBinding[]
    > = {};
    for (const lib of libraries) {
      const sources = await libraryService.getLibrarySources(lib.id);
      newBindings[lib.id] = sources;
    }
    setLibraryBindings(newBindings);
  };

  useEffect(() => {
    window.scrollTo(0, 0);
    if (activeTab === "RESOURCES") {
      loadResources();
    }
    if (activeTab === "LIBRARIES") {
      loadBindings();
      loadResources();
    }
  }, [activeTab, libraries]);

  // Listen for scan completion to automatically refresh resource counts
  useEffect(() => {
    const handleScanComplete = () => {
      // Refresh resources if we are currently on the RESOURCES tab
      // Otherwise, the Next time we switch to it, it will load anyway
      if (activeTab === "RESOURCES") {
        loadResources();
      }
    };

    window.addEventListener("cyber:scan:completed", handleScanComplete);
    return () =>
      window.removeEventListener("cyber:scan:completed", handleScanComplete);
  }, [activeTab]);

  const handleSelectProtocol = (protocol: any) => {
    setSelectedProtocol(protocol);
    // Initialize config with defaults
    const defaultConfig: Record<string, any> = {};
    if (protocol.config_fields) {
      protocol.config_fields.forEach((field: any) => {
        if (field.default !== undefined) {
          defaultConfig[field.name] = field.default;
        } else if (field.type === "boolean") {
          defaultConfig[field.name] = true; // sensible default if none provided
        }
      });
    }
    setNewSourceConfig(defaultConfig);
    setPreviewData(null);
    setPreviewError(null);
    setPreviewPath("/");
  };

  const closeAddModal = () => {
    setIsAddingResource(false);
    setTimeout(() => {
      setSelectedProtocol(null);
      setNewSourceName("");
      setNewSourceConfig({});
      setPreviewData(null);
      setPreviewError(null);
      setPreviewPath("/");
    }, 300);
  };

  const handlePreviewDirectory = async (
    pathOverride?: string | React.MouseEvent,
  ) => {
    if (!selectedProtocol) return;
    setIsPreviewing(true);
    setPreviewError(null);
    const targetPath =
      typeof pathOverride === "string" ? pathOverride : previewPath;
    try {
      const { storageService } = await import("../api");
      const { items, error } = await storageService.previewStorage(
        selectedProtocol.type,
        newSourceConfig,
        targetPath,
      );
      if (items !== null) {
        setPreviewData(items);
        if (typeof pathOverride === "string") setPreviewPath(pathOverride); // update state after success
      } else {
        setPreviewError(error || "连接失败或路径无效，请检查配置和凭证。");
      }
    } catch (e: any) {
      setPreviewError(e.message || "网络异常，无法连接后端进行预览测试。");
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleNavigateDown = (dirPath: string) => {
    handlePreviewDirectory(dirPath);
  };

  const handleNavigateUp = () => {
    if (previewPath === "/" || previewPath === "") return;
    const parts = previewPath.split("/").filter(Boolean);
    parts.pop();
    const p = parts.length === 0 ? "/" : "/" + parts.join("/");
    handlePreviewDirectory(p);
  };

  const handleAddSource = async () => {
    if (!newSourceName || !selectedProtocol) return;
    const { storageService } = await import("../api");
    const success = await storageService.addSource(
      newSourceName,
      selectedProtocol.type,
      newSourceConfig,
    );
    if (success) {
      await loadResources();
      // 存储建筑师：接入 ≥3 种不同协议时解锁。loadResources 已刷过 storageSources。
      const { unlockBehaviorAchievement } = await import('../api');
      const protocols = new Set(storageSources.map(s => (s.type || '').toLowerCase()).filter(Boolean));
      protocols.add(selectedProtocol.type.toLowerCase());
      if (protocols.size >= 3) {
        unlockBehaviorAchievement('storage_architect');
      }
      closeAddModal();
    } else {
      toast.error("添加存储源失败");
    }
  };

  const handleDeleteSource = (id: number) => {
    setConfirmAction({
      message: "Disconnect this source?",
      onConfirm: async () => {
        const { storageService } = await import("../api");
        const success = await storageService.deleteSource(id, true);
        if (success) {
          toast.success("存储源已断开连接");
          await loadResources();
        } else {
          toast.error("断开存储源失败");
        }
      },
    });
  };

  const handleScanSource = async (id: number) => {
    const { storageService } = await import("../api");
    const res = await storageService.scanSource(id);
    if (res.ok) {
      window.dispatchEvent(new CustomEvent("cyber:scan:started"));
      toast.success("全维度光学扫描已启动");
    } else {
      // 后端 40013 = 该存储源没被任何媒体库绑定，提示用户去绑定
      toast.error(res.msg || "触发扫描失败。");
    }
  };

  const handleScanLibrary = async (libraryId: number, libraryName: string) => {
    const { libraryService } = await import("../api");
    const res = await libraryService.scanLibrary(libraryId);
    if (res.ok) {
      window.dispatchEvent(new CustomEvent("cyber:scan:started"));
      toast.success(`《${libraryName}》刮削任务已下发`);
    } else {
      toast.error(res.msg || "扫描启动失败");
    }
  };

  const handleEditLibrarySubmit = async () => {
    if (!editingLibraryId) return;
    const { libraryService } = await import("../api");
    const success = await libraryService.updateLibrary(editingLibraryId, {
      name: editingLibraryName,
      description: editingLibraryDescription,
    });
    if (success) {
      toast.success("媒体库更新成功！");
      setEditingLibraryId(null);
      await onRefreshLibraries();
    } else {
      toast.error("更新失败，请检查填写信息与服务端状态。");
    }
  };

  const handleDeleteLibrary = (id: number) => {
    setConfirmAction({
      message: "确定要删除此媒体库吗？",
      desc: "这不会删除物理文件，但会清除其所有内容记录。",
      onConfirm: async () => {
        const { libraryService } = await import("../api");
        const success = await libraryService.deleteLibrary(id);
        if (success) {
          toast.success("媒体库已删除！");
          if (editingLibraryId === id) setEditingLibraryId(null);
          await onRefreshLibraries();
        } else {
          toast.error("删除失败，请检查系统状态。");
        }
      },
    });
  };

  const handleUnbindDirectory = (libraryId: number, bindingId: number) => {
    setConfirmAction({
      message: "确定要解绑此目录吗？",
      desc: "相关媒体资源将从媒体库中移除。",
      onConfirm: async () => {
        const { libraryService } = await import("../api");
        const success = await libraryService.unbindLibrarySource(
          libraryId,
          bindingId,
        );
        if (success) {
          toast.success("已解绑该目录，如需清除旧数据，请手动触发全量子扫描。");
          await loadBindings(); // reload bindings to update UI immediately
          await onRefreshLibraries();
        } else {
          toast.error("解绑失败，请重试。");
        }
      },
    });
  };

  const handleCreateLibrary = async () => {
    if (!newLibraryName.trim()) {
      toast.warning("请填写库名称");
      return;
    }
    const slug = newLibraryName.toLowerCase().replace(/\s+/g, "-");
    const { libraryService } = await import("../api");
    const id = await libraryService.createLibrary(
      newLibraryName,
      slug,
      newLibraryDescription,
    );
    if (id !== null) {
      toast.success("媒体库创建成功！");
      setIsAddingLibrary(false);
      setNewLibraryName("");
      setNewLibraryDescription("");
      await onRefreshLibraries();
      // 图书管理员：累计创建 ≥3 个媒体库。libraries 在 onRefreshLibraries 后由父
      // 组件刷新，但本地 prop 还是旧值；这里 +1 估算（包含刚创建的）。
      if (libraries.length + 1 >= 3) {
        const { unlockBehaviorAchievement } = await import("../api");
        unlockBehaviorAchievement('librarian');
      }
    } else {
      toast.error("创建失败，请检查填写信息与服务端状态。");
    }
  };

  const handleOpenPreviewSource = (id: number, name: string) => {
    setPreviewingSourceId(id);
    setPreviewingSourceName(name);
    // Reuse the binding browse state for generic browsing
    setBindingSourceId(id);
    setBindBrowsePath("/");
    setBindBrowseData(null);
    setBindError(null);
  };

  const closePreviewSourceModal = () => {
    setPreviewingSourceId(null);
    setPreviewingSourceName("");
    setBindingSourceId(null);
    setBindBrowseData(null);
    setBindBrowsePath("/");
  };

  const handleOpenBinding = (libraryId: number) => {
    setBindingLibraryId(libraryId);
    setBindingSourceId(storageSources.length > 0 ? storageSources[0].id : null);
    setBindBrowsePath("/");
    setBindBrowseData(null);
    setBindError(null);
    loadResources();
  };

  const closeBindingModal = () => {
    setBindingLibraryId(null);
    setBindingSourceId(null);
    setBindBrowseData(null);
    setBindBrowsePath("/");
  };

  const loadBindBrowse = async (path: string = "/") => {
    if (!bindingSourceId) return;
    setIsBindBrowsing(true);
    setBindError(null);
    try {
      const { storageService } = await import("../api");
      const { items, error } = await storageService.getSourceBrowse(
        bindingSourceId,
        path,
      );
      if (items !== null) {
        setBindBrowseData(items);
        setBindBrowsePath(path);
      } else {
        setBindError(error || "拉取目录失败");
      }
    } catch (e: any) {
      setBindError(e.message || "网络异常");
    } finally {
      setIsBindBrowsing(false);
    }
  };

  useEffect(() => {
    if (bindingSourceId) {
      loadBindBrowse("/");
    }
  }, [bindingSourceId]);

  useEffect(() => {
    if (storageSources.length > 0 && bindingLibraryId !== null && bindingSourceId === null) {
      setBindingSourceId(storageSources[0].id);
    }
  }, [storageSources, bindingLibraryId, bindingSourceId]);

  const handleBindDirectory = async (targetPath: string) => {
    if (!bindingLibraryId || !bindingSourceId) return;
    const { libraryService } = await import("../api");
    const success = await libraryService.bindLibrarySource(
      bindingLibraryId,
      bindingSourceId,
      targetPath,
    );
    if (success) {
      toast.success("目录绑定成功！");
      closeBindingModal();
      await loadBindings();
      await onRefreshLibraries();
    } else {
      toast.error("绑定失败，请检查是否已绑定配置或存在权限问题。");
    }
  };

  const renderContent = () => {
    switch (activeTab) {
      case "IDENTITY":
        return (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 animate-in slide-in-from-right-4 fade-in duration-300">
            <div className="space-y-6">
              <div className="bg-[#0a0a12]/80 border border-white/10 p-6 relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-20 h-20 bg-gradient-to-bl from-primary/20 to-transparent"></div>
                <div className="flex items-center gap-6 mb-6">
                  <div className="w-24 h-24 bg-black border-2 border-primary rounded-full flex items-center justify-center shadow-[0_0_15px_var(--color-primary)]">
                    {" "}
                    <User size={48} className="text-white" />{" "}
                  </div>
                  <div>
                    <div className="text-xs text-gray-500 font-['Orbitron'] tracking-widest">
                      网络骇客_ID
                    </div>
                    <div className="text-2xl font-['Rajdhani'] font-bold text-white">
                      V_077
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      {" "}
                      <span className="px-2 py-0.5 bg-secondary/20 text-secondary text-xs border border-secondary/30">
                        等级 50
                      </span>{" "}
                      <span className="px-2 py-0.5 bg-accent/20 text-accent text-xs border border-accent/30">
                        传奇
                      </span>{" "}
                    </div>
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex justify-between text-xs font-['Rajdhani'] text-gray-400">
                    {" "}
                    <span>街头声望</span> <span>8,942 / 10,000</span>{" "}
                  </div>
                  <div className="w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                    {" "}
                    <div className="h-full bg-gradient-to-r from-primary to-secondary w-[89%]"></div>{" "}
                  </div>
                </div>
              </div>
              <div className="bg-[#0a0a12]/80 border border-white/10 p-6 flex flex-col items-center">
                <h3 className="text-sm font-['Orbitron'] text-gray-500 tracking-widest mb-4 w-full text-left flex gap-2 items-center">
                  <Hexagon size={14} /> 神经同步率
                </h3>
                <div className="relative w-48 h-48 flex items-center justify-center">
                  <svg
                    viewBox="0 0 100 100"
                    className="w-full h-full drop-shadow-[0_0_10px_var(--color-primary)]"
                  >
                    <polygon
                      points="50,10 90,30 90,70 50,90 10,70 10,30"
                      fill="none"
                      stroke="#333"
                      strokeWidth="1"
                    />
                    <polygon
                      points="50,20 80,35 80,65 50,80 20,65 20,35"
                      fill="none"
                      stroke="#333"
                      strokeWidth="1"
                    />
                    <polygon
                      points="50,15 85,35 70,75 50,85 25,60 15,40"
                      fill="var(--color-primary)"
                      fillOpacity="0.3"
                      stroke="var(--color-primary)"
                      strokeWidth="2"
                    />
                  </svg>
                  <div className="absolute text-xs font-['Rajdhani'] text-primary font-bold">
                    89%
                  </div>
                </div>
              </div>
            </div>
            <div className="space-y-6">
              <div className="bg-[#0a0a12]/80 border border-white/10 p-6 h-full">
                <h3 className="text-sm font-['Orbitron'] text-gray-500 tracking-widest mb-4 flex gap-2 items-center">
                  <Terminal size={14} /> 活动日志
                </h3>
                <div className="space-y-2 font-mono text-xs text-gray-400 h-64 overflow-y-auto custom-scrollbar">
                  <p>
                    <span className="text-primary">10:42 AM</span> &gt;
                    系统登录成功
                  </p>
                  <p>
                    <span className="text-primary">10:45 AM</span> &gt;
                    已访问文件：新世纪福音战士
                  </p>
                  <p>
                    <span className="text-secondary">11:30 AM</span> &gt;
                    解锁成就：夜行者
                  </p>
                  <p>
                    <span className="text-primary">14:20 PM</span> &gt; 同步完成
                    (100%)
                  </p>
                  <p>
                    <span className="text-red-500">错误</span> &gt;
                    连接中断_节点_03
                  </p>
                  <p>
                    <span className="text-primary">14:21 PM</span> &gt;
                    正在重新路由流量... [成功]
                  </p>
                </div>
              </div>
            </div>
          </div>
        );
      case "REVIEW":
        return (
          <div className="animate-in slide-in-from-right-4 fade-in duration-300 -mt-24 -mx-4 md:-mx-12">
            <ReviewWorkbench />
          </div>
        );
      case "VAULT":
        return (
          <VaultPanel
            favorites={favorites}
            onMovieSelect={onMovieSelect}
            onToggleFavorite={onToggleFavorite}
            vaultState={vaultState}
            onRefreshVaultStatus={onRefreshVaultStatus}
            onRefreshFavorites={onRefreshFavorites}
          />
        );
      case "MEDALS": {
        const milestones = achievements.filter((a) => a.category === 'milestone');
        const behaviors = achievements.filter((a) => a.category === 'behavior');
        const unlockedCount = achievementSummary?.unlocked ?? achievements.filter((a) => a.unlocked).length;
        const total = achievementSummary?.total ?? achievements.length;
        const renderCard = (ach: Achievement) => {
          const Icon = resolveAchievementIcon(ach.icon);
          // milestone 未解锁但有进度 → 展示进度条；behavior 仅展示锁/解锁两态
          const showProgress = ach.category === 'milestone' && !ach.unlocked && ach.progress > 0;
          const targetValue = ach.trigger?.value;
          const currentValue = typeof targetValue === 'number'
            ? Math.min(targetValue, Math.round(ach.progress * targetValue))
            : null;
          return (
            <div
              key={ach.id}
              className={`border p-4 flex items-start gap-4 transition-colors ${
                ach.unlocked
                  ? 'border-accent bg-accent/5'
                  : 'border-white/10 bg-black/40 opacity-60'
              }`}
            >
              <div
                className={`p-3 rounded-full border-2 shrink-0 ${
                  ach.unlocked ? 'border-accent text-accent' : 'border-gray-600 text-gray-600'
                }`}
              >
                {ach.unlocked ? <Icon size={24} /> : <Lock size={24} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h4
                    className={`font-['Orbitron'] font-bold text-sm ${
                      ach.unlocked ? 'text-white' : 'text-gray-500'
                    }`}
                  >
                    {ach.title}
                  </h4>
                  <span
                    className={`text-[9px] px-1.5 py-0.5 border ${
                      ach.category === 'milestone'
                        ? 'border-cyan-500/40 text-cyan-400/80'
                        : 'border-white/10 text-gray-500'
                    }`}
                  >
                    {ach.category === 'milestone' ? '里程碑' : '行为'}
                  </span>
                </div>
                <p className="text-xs text-gray-400 font-sans mt-1">{ach.desc}</p>
                {showProgress && (
                  <div className="mt-2">
                    <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-cyan-500/60"
                        style={{ width: `${Math.round(ach.progress * 100)}%` }}
                      />
                    </div>
                    <div className="text-[10px] text-gray-500 mt-1 font-mono">
                      {currentValue !== null
                        ? `${currentValue} / ${targetValue}`
                        : `${Math.round(ach.progress * 100)}%`}
                    </div>
                  </div>
                )}
                {ach.unlocked && ach.unlockedAt && (
                  <div className="text-[10px] text-accent/70 mt-1 font-mono">
                    解锁于 {new Date(ach.unlockedAt).toLocaleDateString()}
                  </div>
                )}
              </div>
            </div>
          );
        };
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 fade-in duration-300">
            <div className="bg-[#0a0a12]/80 border border-white/10 p-5 flex items-center gap-4">
              <div className="p-3 rounded-full border-2 border-accent text-accent">
                <Trophy size={20} />
              </div>
              <div className="flex-1">
                <div className="text-xs text-gray-500 font-['Orbitron'] tracking-widest">解锁进度</div>
                <div className="text-xl font-['Rajdhani'] font-bold text-white">
                  {unlockedCount} <span className="text-gray-500 text-sm">/ {total}</span>
                </div>
              </div>
              {total > 0 && (
                <div className="w-32 h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-accent to-cyan-500"
                    style={{ width: `${Math.round((unlockedCount / total) * 100)}%` }}
                  />
                </div>
              )}
            </div>

            {achievementsLoading && achievements.length === 0 ? (
              <div className="h-32 flex items-center justify-center text-gray-500 font-['Orbitron'] tracking-widest">
                <Loader2 size={20} className="animate-spin mr-2" /> LOADING...
              </div>
            ) : (
              <>
                {milestones.length > 0 && (
                  <div>
                    <h3 className="text-xs font-['Orbitron'] text-gray-500 tracking-widest mb-3">里程碑</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {milestones.map(renderCard)}
                    </div>
                  </div>
                )}
                {behaviors.length > 0 && (
                  <div>
                    <h3 className="text-xs font-['Orbitron'] text-gray-500 tracking-widest mb-3">行为成就</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {behaviors.map(renderCard)}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        );
      }
      case "RESOURCES":
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 fade-in duration-300">
            <div className="flex justify-between items-center bg-[#0a0a12]/80 border border-white/10 p-6 rounded-2xl shadow-lg backdrop-blur-sm">
              <div>
                <h3 className="text-lg font-['Orbitron'] font-bold text-white flex items-center gap-2">
                  <HardDrive size={18} /> 资源接入与挂载
                </h3>
                <p className="text-xs text-gray-400 font-sans mt-1">
                  管理系统挂载的多媒体数据节点和外部网络来源
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setIsAddingResource(true)}
                  className="px-4 py-2 rounded-xl border border-primary/50 text-primary hover:bg-primary hover:text-black hover:border-primary hover:shadow-[0_0_15px_var(--color-primary)] flex items-center gap-2 text-sm font-['Orbitron'] transition-all"
                >
                  <Plus size={16} /> 接入新链路
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {storageSources.map((res) => (
                <div
                  key={res.id}
                  className="relative p-3 rounded-xl border border-white/10 bg-[#0a0a12]/80 hover:border-white/20 shadow-md hover:-translate-y-0.5 transition-all duration-300 group overflow-hidden flex flex-col min-h-[140px]"
                >
                  <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity"></div>

                  {/* Status Badge */}
                  {res.health?.status === "online" ? (
                    <div className="absolute top-2 right-2 text-[9px] text-green-500 flex items-center gap-1 font-['Rajdhani'] tracking-widest border border-green-500/30 bg-green-500/10 rounded-full px-2 py-0.5 shadow-[0_0_8px_rgba(34,197,94,0.2)] z-20">
                      <div className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse"></div>{" "}
                      在线
                    </div>
                  ) : res.health?.status === "offline" ? (
                    <div className="absolute top-2 right-2 text-[9px] text-red-500 flex items-center gap-1 font-['Rajdhani'] tracking-widest border border-red-500/30 bg-red-500/10 rounded-full px-2 py-0.5 shadow-[0_0_8px_rgba(239,68,68,0.2)] z-20">
                      <div className="w-1.5 h-1.5 bg-red-500 rounded-full"></div>{" "}
                      离线
                    </div>
                  ) : res.health?.status === "checking" ? (
                    <div className="absolute top-2 right-2 text-[9px] text-cyan-400 flex items-center gap-1 font-['Rajdhani'] tracking-widest border border-cyan-500/30 bg-cyan-500/10 rounded-full px-2 py-0.5 shadow-[0_0_8px_rgba(6,182,212,0.2)] z-20">
                      <Loader2 size={10} className="animate-spin" /> 检测中
                    </div>
                  ) : (
                    <div className="absolute top-2 right-2 text-[9px] text-gray-400 flex items-center gap-1 font-['Rajdhani'] tracking-widest border border-gray-500/30 bg-gray-500/10 rounded-full px-2 py-0.5 z-20">
                      <div className="w-1.5 h-1.5 bg-gray-400 rounded-full"></div>{" "}
                      {res.health?.status || "未验证"}
                    </div>
                  )}

                  <div className="flex gap-2 mb-2 relative z-10 items-start mt-1">
                    <div className="text-gray-500 group-hover:text-primary transition-colors p-1.5 bg-black/40 rounded-lg border border-white/5 group-hover:border-primary/30">
                      {res.type === "local" ? (
                        <HardDrive size={18} strokeWidth={1.5} />
                      ) : res.type === "alist" ? (
                        <Box size={18} strokeWidth={1.5} />
                      ) : res.type === "webdav" ? (
                        <Globe size={18} strokeWidth={1.5} />
                      ) : (
                        <Network size={18} strokeWidth={1.5} />
                      )}
                    </div>
                    <div className="flex-1 min-w-0 pr-10 text-left">
                      <h4 className="font-['Orbitron'] text-white font-bold tracking-widest mb-0.5 text-xs truncate flex items-center gap-1">
                        <span className="truncate" title={res.name || res.display_name}>
                          {res.name || res.display_name}
                        </span>
                        <div className="flex items-center gap-1 shrink-0 ml-1">
                          {res.capabilities?.direct_stream && (
                            <span
                              title="支持直连串流"
                              className="text-accent hover:scale-110 transition-transform"
                            >
                              <PlaySquare size={13} strokeWidth={1.5} />
                            </span>
                          )}
                          {res.capabilities?.vfs_mount && (
                            <span
                              title="支持虚拟文件系统挂载"
                              className="text-cyan-400 hover:scale-110 transition-transform"
                            >
                              <FolderTree size={14} strokeWidth={1.5} />
                            </span>
                          )}
                        </div>
                      </h4>
                      <div
                        className="font-mono text-[9px] text-gray-500 truncate w-full"
                        title={res.type || "UNKNOWN"}
                      >
                        [{(res.type || "UNKNOWN").toUpperCase()}]{" "}
                        {res.root_path || "云端映射"}
                      </div>
                    </div>
                  </div>

                  <div className="flex-1 relative z-10">
                    {res.health?.reason &&
                      res.health.status !== "online" &&
                      !["ok", "success"].includes(
                        res.health.reason.toLowerCase(),
                      ) && (
                        <div
                          className="text-[9px] text-red-500 mb-2 truncate bg-red-500/10 border border-red-500/20 px-1.5 py-1 rounded-md w-full font-['Rajdhani'] flex items-center gap-1"
                          title={res.health.reason}
                        >
                          <span className="shrink-0 w-2.5 h-2.5 rounded-full bg-red-500/20 border border-red-500/50 flex items-center justify-center text-[7px] font-bold">
                            !
                          </span>
                          <span className="truncate">{res.health.reason}</span>
                        </div>
                      )}

                    {res.config_error && (
                      <div
                        className="text-[9px] text-red-400 mb-2 truncate bg-red-500/10 border border-red-500/20 px-1.5 py-1 rounded-md w-full"
                        title={res.config_error}
                      >
                        ⚠ 配置异常: {res.config_error}
                      </div>
                    )}

                    {/* Usage stats from backend */}
                    <div className="grid grid-cols-2 gap-2 mb-2">
                      <div className="bg-black/40 border border-white/5 rounded-md px-2 py-1.5 flex justify-between items-center gap-2">
                        <div className="text-[9px] text-gray-500 font-['Orbitron'] tracking-widest shrink-0">
                          影视资产
                        </div>
                        <div className="text-sm text-gray-200 font-mono truncate">
                          {res.usage?.resource_count || 0}
                        </div>
                      </div>
                      <div className="bg-black/40 border border-white/5 rounded-md px-2 py-1.5 flex justify-between items-center gap-2">
                        <div className="text-[9px] text-gray-500 font-['Orbitron'] tracking-widest shrink-0">
                          关联库
                        </div>
                        <div className="text-sm text-gray-200 font-mono truncate">
                          {res.usage?.library_binding_count || 0}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Operational Toolbar */}
                  <div className="relative z-10 pt-3 border-t border-white/5 flex gap-2 justify-end items-center mt-auto">
                    {res.actions?.can_scan && (
                      <button
                        title="触发全量/增量扫描更新"
                        onClick={() => setScanningSource({ id: res.id, name: res.name })}
                        className="w-8 h-8 flex items-center justify-center rounded-lg bg-black/50 border border-white/5 hover:border-cyan-500/50 text-cyan-500/70 hover:text-cyan-400 hover:bg-cyan-500/10 hover:shadow-[0_0_15px_rgba(6,182,212,0.4)] transition-all duration-300 group/btn"
                      >
                        <Zap
                          size={14}
                          className="group-hover/btn:scale-110 transition-transform"
                        />
                      </button>
                    )}
                    {res.actions?.can_preview && (
                      <button
                        title="预览此资源的目录结构"
                        onClick={() =>
                          handleOpenPreviewSource(res.id, res.name)
                        }
                        className="w-8 h-8 flex items-center justify-center rounded-lg bg-black/50 border border-white/5 hover:border-fuchsia-500/50 text-fuchsia-500/70 hover:text-fuchsia-400 hover:bg-fuchsia-500/10 hover:shadow-[0_0_15px_rgba(217,70,239,0.4)] transition-all duration-300 group/btn"
                      >
                        <Eye
                          size={14}
                          className="group-hover/btn:scale-110 transition-transform"
                        />
                      </button>
                    )}
                    <div className="flex-1"></div>
                    {res.guards?.can_delete_directly === false ? (
                      <button
                        title="状态受保护：存在依赖项或系统默认节点，无法直接卸载"
                        className="w-8 h-8 flex items-center justify-center rounded-lg bg-black/50 border border-white/5 text-gray-600 cursor-not-allowed"
                      >
                        <Lock size={14} />
                      </button>
                    ) : (
                      <button
                        title="断开/卸载该节点"
                        onClick={() => handleDeleteSource(res.id)}
                        className="w-8 h-8 flex items-center justify-center rounded-lg bg-black/50 border border-white/5 hover:border-red-500/50 text-red-500/70 hover:text-red-400 hover:bg-red-500/10 hover:shadow-[0_0_15px_rgba(239,68,68,0.4)] transition-all duration-300 group/btn"
                      >
                        <Trash2
                          size={14}
                          className="group-hover/btn:scale-110 transition-transform"
                        />
                      </button>
                    )}
                  </div>
                </div>
              ))}

              <button
                onClick={() => setIsAddingResource(true)}
                className="rounded-xl border border-dashed border-white/20 hover:border-primary/40 bg-[#0a0a12]/40 hover:bg-primary/5 shadow-sm hover:shadow-lg hover:-translate-y-0.5 flex flex-col items-center justify-center p-4 transition-all duration-300 group min-h-[140px]"
              >
                <div className="w-10 h-10 rounded-full border border-white/20 group-hover:border-primary flex items-center justify-center text-gray-500 group-hover:text-primary transition-colors mb-2 group-hover:shadow-[0_0_15px_var(--color-primary)] bg-black/50">
                  <Plus size={20} />
                </div>
                <span className="font-['Orbitron'] text-xs tracking-widest text-gray-400 group-hover:text-primary transition-colors">
                  添加全新资源库
                </span>
              </button>
            </div>
          </div>
        );
      case "APPEARANCE":
        return (
          <div className="space-y-8 animate-in slide-in-from-right-4 fade-in duration-300 max-w-3xl">
            <HomepageEditor />
            <PersonalPreferencesCard
              settings={settings}
              setSettings={setSettings}
              libraries={libraries}
            />
            <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
              <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-6 flex items-center gap-2">
                <Settings2 size={18} /> 视觉特效
              </h3>
              <div className="space-y-6">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-gray-300 text-sm font-['Rajdhani']">
                    <Monitor size={16} /> 光学扫描线
                  </div>
                  <button
                    onClick={() =>
                      setSettings({
                        ...settings,
                        scanlines: !settings.scanlines,
                      })
                    }
                    className={`w-10 h-5 rounded-full relative transition-colors ${settings.scanlines ? "bg-primary" : "bg-gray-700"}`}
                  >
                    <div
                      className={`absolute top-1 w-3 h-3 bg-black rounded-full transition-all ${settings.scanlines ? "left-6" : "left-1"}`}
                    ></div>
                  </button>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-gray-300 text-sm font-['Rajdhani']">
                    <Zap size={16} /> 神经故障特效
                  </div>
                  <button
                    onClick={() =>
                      setSettings({ ...settings, glitch: !settings.glitch })
                    }
                    className={`w-10 h-5 rounded-full relative transition-colors ${settings.glitch ? "bg-red-500" : "bg-gray-700"}`}
                  >
                    <div
                      className={`absolute top-1 w-3 h-3 bg-black rounded-full transition-all ${settings.glitch ? "left-6" : "left-1"}`}
                    ></div>
                  </button>
                </div>
              </div>
            </div>
            <div className="bg-[#0a0a12]/80 border border-white/10 p-6">
              <h3 className="text-lg font-['Orbitron'] font-bold text-white mb-6 flex items-center gap-2">
                <Palette size={18} /> 界面主题
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {Object.keys(THEMES).map((themeKey) => (
                  <button
                    key={themeKey}
                    onClick={() => setTheme(themeKey)}
                    className={`p-4 border flex flex-col items-center gap-2 transition-all ${currentTheme === themeKey ? "border-white bg-white/10" : "border-white/10 hover:border-white/30"}`}
                  >
                    {" "}
                    <div className="flex gap-2">
                      {" "}
                      <div
                        className="w-4 h-4 rounded-full"
                        style={{ background: THEMES[themeKey].primary }}
                      ></div>{" "}
                      <div
                        className="w-4 h-4 rounded-full"
                        style={{ background: THEMES[themeKey].secondary }}
                      ></div>{" "}
                    </div>{" "}
                    <span className="text-xs font-['Orbitron'] text-white mt-1">
                      {themeKey}
                    </span>{" "}
                    {currentTheme === themeKey && (
                      <div className="text-[10px] text-primary flex items-center gap-1">
                        <Check size={10} /> 使用中
                      </div>
                    )}{" "}
                  </button>
                ))}
              </div>
            </div>
          </div>
        );
      case "SYSTEM":
        return (
          <div className="space-y-8 animate-in slide-in-from-right-4 fade-in duration-300 max-w-2xl">
            <BackendServerCard />
            <ProxySettingsCard />
            <TmdbSettingsCard />
          </div>
        );
      case "ABOUT":
        return (
          <div className="space-y-8 animate-in slide-in-from-right-4 fade-in duration-300 max-w-2xl">
            <AboutCard />
          </div>
        );
      case "LIBRARIES":
        return (
          <div className="space-y-6 animate-in slide-in-from-right-4 fade-in duration-300">
            <div className="flex justify-between items-center bg-[#0a0a12]/80 border border-white/10 p-6 rounded-2xl shadow-lg backdrop-blur-sm">
              <div>
                <h3 className="text-lg font-['Orbitron'] font-bold text-white flex items-center gap-2">
                  <Database size={18} /> 媒体库管理
                </h3>
                <p className="text-xs text-gray-400 font-sans mt-1">
                  创建逻辑分区，并将底层存储目录映射到媒体库
                </p>
              </div>
              <button
                onClick={() => setIsAddingLibrary(true)}
                className="px-4 py-2 rounded-xl border border-primary/50 text-primary hover:bg-primary hover:text-black hover:border-primary hover:shadow-[0_0_15px_var(--color-primary)] flex items-center gap-2 text-sm font-['Orbitron'] transition-all"
              >
                <Plus size={16} /> 创建新库
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {libraries && libraries.length > 0 ? (
                libraries.map((lib) => (
                  <div
                    key={lib.id}
                    className="border border-white/10 bg-[#0a0a12]/80 p-5 rounded-xl hover:border-primary/50 transition-colors"
                  >
                    <div className="flex justify-between items-start mb-4">
                      <h4 className="font-['Orbitron'] font-bold text-white text-lg">
                        {lib.name}
                      </h4>
                    </div>
                    <p className="text-sm text-gray-400 mb-4">
                      {lib.description || "无描述 / No description."}
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setEditingLibraryId(lib.id);
                          setEditingLibraryName(lib.name);
                          setEditingLibraryDescription(lib.description || "");
                        }}
                        className="text-xs bg-white/5 border border-white/10 hover:bg-white/10 px-3 py-1.5 rounded transition-colors text-white font-['Rajdhani']"
                      >
                        编辑设置
                      </button>
                      <button
                        onClick={() => handleOpenBinding(lib.id)}
                        className="text-xs bg-primary/20 border border-primary/30 hover:bg-primary/40 px-3 py-1.5 rounded transition-colors text-primary font-['Rajdhani']"
                      >
                        绑定目录
                      </button>
                      <button
                        onClick={() => handleScanLibrary(lib.id, lib.name)}
                        className="text-xs bg-secondary/15 border border-secondary/40 hover:bg-secondary/30 px-3 py-1.5 rounded transition-colors text-secondary font-['Rajdhani'] flex items-center gap-1"
                        title="扫描并刮削该媒体库已绑定的所有目录"
                      >
                        <ScanLine size={12} /> 扫描刮削
                      </button>
                    </div>
                    {libraryBindings[lib.id] &&
                      libraryBindings[lib.id].length > 0 && (
                        <div className="mt-4 pt-4 border-t border-white/5">
                          <div className="flex items-center justify-between mb-2">
                            <div className="text-[10px] text-gray-500 font-['Orbitron'] tracking-widest">
                              已绑定目录
                            </div>
                            <div className="text-[10px] bg-white/5 text-gray-400 px-1.5 py-0.5 rounded font-mono">
                              {libraryBindings[lib.id].length} TOTAL
                            </div>
                          </div>
                          <div className="space-y-2 max-h-[120px] overflow-y-auto custom-scrollbar pr-1">
                            {libraryBindings[lib.id].map((b) => (
                              <div
                                key={b.id}
                                className="flex flex-col bg-white/5 px-2 py-1.5 rounded border border-white/5 gap-1 group/binding transition-colors hover:bg-white/10"
                              >
                                <div className="flex justify-between items-center text-xs">
                                  <span
                                    className="text-primary truncate font-mono flex-1 mb-1"
                                    title={b.root_path}
                                  >
                                    {b.root_path}
                                  </span>
                                  <div className="flex items-center gap-2">
                                    <span className="text-gray-500 shrink-0 text-[10px] bg-black/50 px-1.5 py-0.5 rounded border border-white/5">
                                      {b.source?.name ||
                                        `Source #${b.source_id}`}
                                    </span>
                                    <button
                                      onClick={() =>
                                        handleUnbindDirectory(lib.id, b.id)
                                      }
                                      className="text-white/30 hover:text-red-500 hover:bg-red-500/10 p-1 rounded opacity-0 group-hover/binding:opacity-100 transition-all border border-transparent hover:border-red-500/30"
                                      title="解除绑定"
                                    >
                                      <Trash2 size={12} />
                                    </button>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                ))
              ) : (
                <div className="col-span-full h-48 border border-dashed border-white/20 flex flex-col items-center justify-center text-gray-500 rounded-xl">
                  <FolderTree size={32} className="mb-2 opacity-50" />
                  <p className="font-['Orbitron'] text-xs">
                    还未创建任何媒体库分区
                  </p>
                </div>
              )}
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen w-full pt-24 px-4 md:px-12 pb-12">
      <div className="max-w-7xl mx-auto">
      <div className="flex items-center gap-4 mb-8">
        <div className="p-2 border border-primary text-primary shadow-[0_0_10px_var(--color-primary)]">
          <User className="w-6 h-6" />
        </div>
        <h1 className="text-3xl font-['Orbitron'] font-bold text-white tracking-widest">
          神经接口 <span className="text-primary">// 用户中心</span>
        </h1>
        <div className="flex-grow h-[1px] bg-gradient-to-r from-primary/50 to-transparent"></div>
      </div>
      <div className="flex flex-col md:flex-row gap-8">
        <div className="w-full md:w-64 flex flex-col gap-2 shrink-0">
          {" "}
          {[
            { id: "APPEARANCE", icon: <Palette size={18} />, label: "主页设置" },
            { id: "IDENTITY", icon: <User size={18} />, label: "身份信息" },
            { id: "VAULT", icon: <Shield size={18} />, label: "数据保险库" },
            { id: "MEDALS", icon: <Trophy size={18} />, label: "成就奖章" },
            {
              id: "LIBRARIES",
              icon: <Database size={18} />,
              label: "媒体库管理",
            },
            {
              id: "RESOURCES",
              icon: <HardDrive size={18} />,
              label: "存储资源池",
            },
            { id: "REVIEW", icon: <Check size={18} />, label: "审查工作台" },
            { id: "SYSTEM", icon: <Settings2 size={18} />, label: "系统配置" },
            { id: "ABOUT", icon: <Info size={18} />, label: "关于" },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`flex items-center gap-3 px-4 py-3 text-sm font-['Orbitron'] border-l-2 transition-all ${activeTab === item.id ? "border-primary bg-primary/10 text-primary drop-shadow-[0_0_8px_var(--color-primary)]" : "border-transparent text-gray-500 hover:text-gray-300 hover:bg-white/5"}`}
            >
              {" "}
              {item.icon} {item.label}{" "}
            </button>
          ))}{" "}
        </div>
        <div className="flex-1 min-w-0"> {renderContent()} </div>
      </div>
      </div>

      {confirmAction && (
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={() => setConfirmAction(null)}
          ></div>
          <div className="relative bg-[#0a0a12] border border-white/10 rounded-2xl w-full max-w-sm shadow-[0_0_50px_rgba(0,0,0,0.8)] p-6 md:p-8 animate-in zoom-in-95 duration-200 transition-all border-t-2 border-t-red-500/50">
            <h3 className="text-xl font-['Orbitron'] font-bold text-white mb-2 flex items-center gap-3">
              <AlertTriangle className="text-red-500" size={24} />
              确认执行
            </h3>
            <p className="text-gray-300 font-['Rajdhani'] mt-4 text-base">
              {confirmAction.message}
            </p>
            {confirmAction.desc && (
              <p className="text-xs text-gray-500 font-sans mt-2">
                {confirmAction.desc}
              </p>
            )}
            <div className="mt-8 flex gap-4">
              <button
                onClick={() => setConfirmAction(null)}
                className="px-5 py-2.5 rounded-lg border border-white/10 text-gray-400 hover:bg-white/5 font-['Orbitron'] text-sm tracking-wider flex-1 transition-all"
              >
                ABORT
              </button>
              <button
                onClick={() => {
                  confirmAction.onConfirm();
                  setConfirmAction(null);
                }}
                className="px-5 py-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-500 hover:bg-red-500 hover:text-black font-['Orbitron'] text-sm tracking-wider transition-all flex items-center justify-center gap-2 flex-1"
              >
                PROCEED
              </button>
            </div>
          </div>
        </div>
      )}

      {isAddingLibrary && (
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={() => setIsAddingLibrary(false)}
          ></div>
          <div className="relative bg-[#0a0a12] border border-white/10 rounded-2xl w-full max-w-lg shadow-[0_0_50px_rgba(0,0,0,0.8)] p-6 md:p-8 animate-in zoom-in-95 duration-200 transition-all">
            <div className="flex justify-between items-center mb-8 border-b border-white/5 pb-4">
              <h3 className="text-xl font-['Orbitron'] font-bold text-white flex items-center gap-3">
                <div className="p-2 bg-primary/10 text-primary rounded-lg shadow-[0_0_15px_var(--color-primary)]">
                  <Database size={20} />
                </div>
                创建新媒体分类库
              </h3>
              <button
                onClick={() => setIsAddingLibrary(false)}
                className="text-gray-500 hover:text-red-500 hover:bg-red-500/10 p-2 rounded-xl transition-all"
              >
                <X size={20} />
              </button>
            </div>
            <div className="space-y-6">
              <div>
                <label className="block text-xs font-['Orbitron'] text-gray-500 tracking-widest mb-2">
                  库名称 IDENTIFIER
                </label>
                <input
                  type="text"
                  placeholder="例如: 电影"
                  value={newLibraryName}
                  onChange={(e) => setNewLibraryName(e.target.value)}
                  className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 text-white font-['Rajdhani'] focus:outline-none focus:border-primary focus:shadow-[0_0_15px_rgba(0,243,255,0.2)] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-['Orbitron'] text-gray-500 tracking-widest mb-2">
                  描述信息 DESCRIPTION
                </label>
                <textarea
                  value={newLibraryDescription}
                  onChange={(e) => setNewLibraryDescription(e.target.value)}
                  placeholder="记录此媒体库的用途与特性..."
                  className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 text-white font-['Rajdhani'] focus:outline-none focus:border-primary focus:shadow-[0_0_15px_rgba(0,243,255,0.2)] transition-all h-24 custom-scrollbar resize-none"
                ></textarea>
              </div>
              <div className="pt-4 border-t border-white/5 flex gap-4">
                <button
                  onClick={() => setIsAddingLibrary(false)}
                  className="px-6 py-3 rounded-lg border border-white/10 text-gray-400 hover:bg-white/5 font-['Orbitron'] text-sm tracking-wider flex-1 transition-all"
                >
                  ABORT
                </button>
                <button
                  onClick={handleCreateLibrary}
                  className="px-6 py-3 rounded-lg bg-primary/10 border border-primary/50 text-primary hover:bg-primary hover:text-black font-['Orbitron'] text-sm tracking-wider transition-all flex items-center justify-center gap-2 flex-1 shadow-[0_0_20px_rgba(0,243,255,0.15)]"
                >
                  <Save size={16} /> CREATE
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {editingLibraryId !== null && (
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={() => setEditingLibraryId(null)}
          ></div>
          <div className="relative bg-[#0a0a12] border border-white/10 rounded-2xl w-full max-w-lg shadow-[0_0_50px_rgba(0,0,0,0.8)] p-6 md:p-8 animate-in zoom-in-95 duration-200 transition-all">
            <div className="flex justify-between items-center mb-8 border-b border-white/5 pb-4">
              <h3 className="text-xl font-['Orbitron'] font-bold text-white flex items-center gap-3">
                <div className="p-2 bg-primary/10 text-primary rounded-lg shadow-[0_0_15px_var(--color-primary)]">
                  <Database size={20} />
                </div>
                修改媒体分类库
              </h3>
              <button
                onClick={() => setEditingLibraryId(null)}
                className="text-gray-500 hover:text-red-500 hover:bg-red-500/10 p-2 rounded-xl transition-all"
              >
                <X size={20} />
              </button>
            </div>
            <div className="space-y-6">
              <div>
                <label className="block text-xs font-['Orbitron'] text-gray-500 tracking-widest mb-2">
                  库名称 IDENTIFIER
                </label>
                <input
                  type="text"
                  placeholder="例如: 电影"
                  value={editingLibraryName}
                  onChange={(e) => setEditingLibraryName(e.target.value)}
                  className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 text-white font-['Rajdhani'] focus:outline-none focus:border-primary focus:shadow-[0_0_15px_rgba(0,243,255,0.2)] transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-['Orbitron'] text-gray-500 tracking-widest mb-2">
                  描述信息 DESCRIPTION
                </label>
                <textarea
                  value={editingLibraryDescription}
                  onChange={(e) => setEditingLibraryDescription(e.target.value)}
                  placeholder="记录此媒体库的用途与特性..."
                  className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-3 text-white font-['Rajdhani'] focus:outline-none focus:border-primary focus:shadow-[0_0_15px_rgba(0,243,255,0.2)] transition-all h-24 custom-scrollbar resize-none"
                ></textarea>
              </div>
              <div className="pt-4 border-t border-white/5 flex gap-4">
                <button
                  onClick={() => setEditingLibraryId(null)}
                  className="px-5 py-3 rounded-lg border border-white/10 text-gray-400 hover:bg-white/5 font-['Orbitron'] text-sm tracking-wider transition-all"
                >
                  ABORT
                </button>
                <button
                  onClick={() =>
                    editingLibraryId && handleDeleteLibrary(editingLibraryId)
                  }
                  className="px-5 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-500 hover:bg-red-500 hover:text-black font-['Orbitron'] text-sm tracking-wider transition-all flex items-center justify-center gap-2"
                >
                  <Trash2 size={16} /> DELETE
                </button>
                <div className="flex-1"></div>
                <button
                  onClick={handleEditLibrarySubmit}
                  className="px-8 py-3 rounded-lg bg-primary/10 border border-primary/50 text-primary hover:bg-primary hover:text-black font-['Orbitron'] text-sm tracking-wider transition-all flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(0,243,255,0.15)]"
                >
                  <Save size={16} /> SAVE
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {previewingSourceId && (
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={closePreviewSourceModal}
          ></div>
          <div className="relative bg-[#0a0a12] border border-white/10 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-[0_0_50px_rgba(0,0,0,0.8)] p-6 md:p-8 animate-in zoom-in-95 duration-200 transition-all">
            <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4 shrink-0">
              <h3 className="text-xl font-['Orbitron'] font-bold text-white flex items-center gap-3">
                <div className="p-2 bg-primary/10 text-primary rounded-lg shadow-[0_0_15px_var(--color-primary)]">
                  <FolderSearch size={20} />
                </div>
                浏览节点目录: {previewingSourceName}
              </h3>
              <button
                onClick={closePreviewSourceModal}
                className="text-gray-500 hover:text-red-500 hover:bg-red-500/10 p-2 rounded-xl transition-all"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex-1 overflow-hidden border border-white/10 rounded-xl bg-black/40 relative flex flex-col min-h-[400px]">
              <div className="px-4 py-3 border-b border-white/5 bg-white/5 flex items-center gap-2 shrink-0">
                <span className="text-gray-400 text-sm">Path:</span>
                <span className="text-primary font-mono text-sm flex-1 truncate">
                  {bindBrowsePath}
                </span>
                {bindBrowsePath !== "/" && bindBrowsePath !== "" && (
                  <button
                    onClick={() => {
                      const isAbsolute = bindBrowsePath.startsWith("/");
                      const parts = bindBrowsePath.split("/").filter(Boolean);
                      parts.pop();
                      const parentPath =
                        parts.length === 0
                          ? "/"
                          : (isAbsolute ? "/" : "") + parts.join("/");
                      loadBindBrowse(parentPath === "" ? "/" : parentPath);
                    }}
                    className="ml-auto px-2 py-0.5 rounded bg-white/10 hover:bg-primary/20 hover:text-primary transition-colors border border-white/5 hover:border-primary text-[10px] text-white"
                  >
                    UP DIR
                  </button>
                )}
              </div>
              <div className="flex-1 overflow-y-auto custom-scrollbar p-2 relative">
                {isBindBrowsing && (
                  <div className="absolute inset-0 bg-black/50 backdrop-blur-sm z-10 flex flex-col items-center justify-center text-primary font-['Orbitron'] gap-2">
                    <Loader2 size={24} className="animate-spin" />
                    <span className="text-[10px] tracking-widest">
                      LOADING DIRECTORIES...
                    </span>
                  </div>
                )}
                {bindError && (
                  <div className="p-4 text-red-500 text-sm text-center bg-red-500/10 rounded border border-red-500/20">
                    {bindError}
                  </div>
                )}
                {!bindError &&
                  bindBrowseData &&
                  bindBrowseData.length === 0 && (
                    <div className="text-gray-600 text-center py-6 text-xs bg-black/20 rounded">
                      目录为空 (EMPTY DIRECTORY)
                    </div>
                  )}
                {bindBrowseData &&
                  bindBrowseData.map((item, idx) => (
                    <div
                      key={idx}
                      className="flex items-center gap-2 py-2 px-3 rounded group text-gray-300 hover:bg-white/5 border border-transparent transition-colors justify-between"
                    >
                      <div
                        className="flex items-center gap-2 truncate cursor-pointer flex-1"
                        onClick={() => {
                          if (item.type === "dir") {
                            loadBindBrowse(item.path);
                          }
                        }}
                      >
                        {item.type === "dir" ? (
                          <FolderTree
                            size={14}
                            className="text-blue-400 group-hover:scale-110 transition-transform"
                          />
                        ) : (
                          <FileText size={14} className="text-gray-600" />
                        )}
                        <span
                          className={`truncate ${item.type === "dir" ? "group-hover:text-white" : ""}`}
                        >
                          {item.name}
                        </span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {bindingLibraryId && (
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={closeBindingModal}
          ></div>
          <div className="relative bg-[#0a0a12] border border-white/10 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-[0_0_50px_rgba(0,0,0,0.8)] p-6 md:p-8 animate-in zoom-in-95 duration-200 transition-all">
            <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4 shrink-0">
              <h3 className="text-xl font-['Orbitron'] font-bold text-white flex items-center gap-3">
                <div className="p-2 bg-primary/10 text-primary rounded-lg shadow-[0_0_15px_var(--color-primary)]">
                  <Database size={20} />
                </div>
                绑定媒体目录
              </h3>
              <button
                onClick={closeBindingModal}
                className="text-gray-500 hover:text-red-500 hover:bg-red-500/10 p-2 rounded-xl transition-all"
              >
                <X size={20} />
              </button>
            </div>

            <div className="flex gap-4 mb-4 shrink-0">
              <div className="flex-1">
                <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-2 uppercase">
                  Select Storage Node
                </label>
                <select
                  value={bindingSourceId || ""}
                  onChange={(e) => setBindingSourceId(Number(e.target.value))}
                  className="w-full bg-black/50 border border-white/10 rounded-lg px-4 py-2.5 text-white font-['Rajdhani'] focus:outline-none focus:border-primary focus:shadow-[0_0_15px_rgba(0,243,255,0.2)] transition-all appearance-none cursor-pointer"
                >
                  {storageSources.length === 0 && (
                    <option value="" disabled>
                      无可用存储节点，请先在资源池挂载
                    </option>
                  )}
                  {storageSources.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name} ({s.type})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="flex-1 overflow-hidden border border-white/10 rounded-xl bg-black/40 relative flex flex-col min-h-[300px]">
              {storageSources.length === 0 ? (
                <div className="m-auto text-gray-500 text-sm font-['Orbitron'] flex items-center justify-center flex-col gap-3">
                  <AlertTriangle size={32} className="opacity-50" />
                  请先切换到「存储资源池」挂载基础存储链路
                </div>
              ) : (
                <>
                  <div className="px-4 py-3 border-b border-white/5 bg-white/5 flex items-center gap-2 shrink-0">
                    <span className="text-gray-400 text-sm">Path:</span>
                    <span className="text-primary font-mono text-sm flex-1 truncate">
                      {bindBrowsePath}
                    </span>
                    {bindBrowsePath !== "/" && bindBrowsePath !== "" && (
                      <button
                        onClick={() => {
                          const isAbsolute = bindBrowsePath.startsWith("/");
                          const parts = bindBrowsePath
                            .split("/")
                            .filter(Boolean);
                          parts.pop();
                          const parentPath =
                            parts.length === 0
                              ? "/"
                              : (isAbsolute ? "/" : "") + parts.join("/");
                          loadBindBrowse(parentPath === "" ? "/" : parentPath);
                        }}
                        className="ml-auto px-2 py-0.5 rounded bg-white/10 hover:bg-primary/20 hover:text-primary transition-colors border border-white/5 hover:border-primary text-[10px] text-white"
                      >
                        UP DIR
                      </button>
                    )}
                  </div>
                  <div className="flex-1 overflow-y-auto custom-scrollbar p-2 relative">
                    {isBindBrowsing && (
                      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm z-10 flex flex-col items-center justify-center text-primary font-['Orbitron'] gap-2">
                        <Loader2 size={24} className="animate-spin" />
                        <span className="text-[10px] tracking-widest">
                          LOADING DIRECTORIES...
                        </span>
                      </div>
                    )}
                    {bindError && (
                      <div className="p-4 text-red-500 text-sm text-center bg-red-500/10 rounded border border-red-500/20">
                        {bindError}
                      </div>
                    )}
                    {!bindError &&
                      bindBrowseData &&
                      bindBrowseData.length === 0 && (
                        <div className="text-gray-600 text-center py-6 text-xs bg-black/20 rounded">
                          目录为空 (EMPTY DIRECTORY)
                        </div>
                      )}
                    {bindBrowseData &&
                      bindBrowseData.map((item, idx) => (
                        <div
                          key={idx}
                          className="flex items-center gap-2 py-2 px-3 rounded group text-gray-300 hover:bg-white/5 border border-transparent transition-colors justify-between"
                        >
                          <div
                            className="flex items-center gap-2 truncate cursor-pointer flex-1"
                            onClick={() => {
                              if (item.type === "dir") {
                                loadBindBrowse(item.path);
                              }
                            }}
                          >
                            {item.type === "dir" ? (
                              <FolderTree
                                size={14}
                                className="text-blue-400 group-hover:scale-110 transition-transform"
                              />
                            ) : (
                              <FileText size={14} className="text-gray-600" />
                            )}
                            <span
                              className={`truncate ${item.type === "dir" ? "group-hover:text-white" : ""}`}
                            >
                              {item.name}
                            </span>
                          </div>
                        </div>
                      ))}
                  </div>
                  <div className="p-3 border-t border-white/5 flex justify-end shrink-0">
                    <button
                      onClick={() => handleBindDirectory(bindBrowsePath)}
                      className="px-5 py-2 bg-primary/20 hover:bg-primary/40 text-primary hover:text-white hover:shadow-[0_0_15px_var(--color-primary)] transition-all rounded text-sm font-['Orbitron'] font-bold border border-primary/50 hover:border-primary"
                    >
                      绑定当前目录 (BIND CURRENT)
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {isAddingResource && (
        <AddStorageSourceModal
          providerTypes={providerTypes}
          onClose={closeAddModal}
          onSuccess={async () => {
             closeAddModal();
             await loadResources();
          }}
        />
      )}

      {scanningSource && (
        <ScanSourceModal 
          sourceId={scanningSource.id}
          sourceName={scanningSource.name}
          onClose={() => setScanningSource(null)}
        />
      )}
    </div>
  );
};
