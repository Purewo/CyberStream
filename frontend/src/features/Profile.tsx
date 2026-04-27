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
} from "lucide-react";
import { MovieCard } from "../components/movies/Cards";
import { Movie, UserSettings, Achievement } from "../types";
import { THEMES } from "../constants";
import { formatBytes, toast } from "../utils";

import { HistoryPage } from "./History";
import { Leaderboard } from "./Leaderboard";
import { ReviewWorkbench } from "./ReviewWorkbench";

const ACHIEVEMENTS: Achievement[] = [
  {
    id: "a1",
    title: "夜行者",
    desc: "在 02:00 - 05:00 之间观看内容",
    icon: <Clock size={24} />,
    unlocked: true,
  },
  {
    id: "a2",
    title: "数据矿工",
    desc: "浏览片库超过 2 小时",
    icon: <Database size={24} />,
    unlocked: true,
  },
  {
    id: "a3",
    title: "网络传奇",
    desc: "看完 100 部影片",
    icon: <Trophy size={24} />,
    unlocked: false,
  },
  {
    id: "a4",
    title: "幽灵",
    desc: "清除观看历史",
    icon: <User size={24} />,
    unlocked: false,
  },
  {
    id: "a5",
    title: "收藏家",
    desc: "保存 50 个项目到保险库",
    icon: <Shield size={24} />,
    unlocked: true,
  },
  {
    id: "a6",
    title: "超频",
    desc: "以 2.0 倍速观看",
    icon: <Zap size={24} />,
    unlocked: false,
  },
];

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
} from "lucide-react";

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

interface ProfilePageProps {
  settings: UserSettings;
  setSettings: (s: UserSettings) => void;
  favorites: Movie[];
  onMovieSelect: (m: Movie) => void;
  onToggleFavorite: (m: Movie) => void;
  currentTheme: string;
  setTheme: (t: string) => void;
  libraries?: import("../types").Library[];
  history?: any[];
  onClearHistory?: () => void;
  onDeleteHistoryItem?: (id: string) => void;
  onRefreshLibraries?: () => Promise<void>;
  initialTab?: string;
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
  history = [],
  onClearHistory = () => {},
  onDeleteHistoryItem = () => {},
  onRefreshLibraries = async () => {},
  initialTab = "IDENTITY",
}) => {
  const [activeTab, setActiveTab] = useState(initialTab);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

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
    const success = await storageService.scanSource(id);
    if (success) {
      window.dispatchEvent(new CustomEvent("cyber:scan:started"));
      toast.success("全维度光学扫描已启动");
    } else {
      toast.error("触发扫描失败。");
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
      case "HISTORY":
        return (
          <div className="animate-in slide-in-from-right-4 fade-in duration-300 -mt-24 -mx-4 md:-mx-12">
            <HistoryPage
              history={history}
              onMovieSelect={onMovieSelect}
              onClearHistory={onClearHistory}
              onDeleteHistoryItem={onDeleteHistoryItem}
            />
          </div>
        );
      case "LEADERBOARD":
        return (
          <div className="animate-in slide-in-from-right-4 fade-in duration-300 -mt-24 -mx-4 md:-mx-12">
            <Leaderboard onMovieSelect={onMovieSelect} />
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
          <div className="animate-in slide-in-from-right-4 fade-in duration-300">
            {favorites.length === 0 ? (
              <div className="h-64 border border-white/10 bg-[#0a0a12]/40 flex flex-col items-center justify-center text-gray-600 gap-4">
                {" "}
                <Shield size={48} className="opacity-20" />{" "}
                <span className="font-['Orbitron'] tracking-widest">
                  保险库为空
                </span>{" "}
              </div>
            ) : (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] md:grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-4 md:gap-6 justify-center">
                {" "}
                {favorites.map((movie) => (
                  <div key={movie.id} className="relative group">
                    {" "}
                    <MovieCard
                      movie={movie}
                      category={{ colorClass: "border-white/20" }}
                      onClick={onMovieSelect}
                    />{" "}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleFavorite(movie);
                      }}
                      className="absolute top-2 right-2 p-2 bg-black/80 border border-red-500 text-red-500 opacity-0 group-hover:opacity-100 transition-opacity z-30 hover:bg-red-500 hover:text-black"
                    >
                      <Trash2 size={14} />
                    </button>{" "}
                  </div>
                ))}{" "}
              </div>
            )}
          </div>
        );
      case "MEDALS":
        return (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-in slide-in-from-right-4 fade-in duration-300">
            {ACHIEVEMENTS.map((ach) => (
              <div
                key={ach.id}
                className={`border p-4 flex items-center gap-4 ${ach.unlocked ? "border-accent bg-accent/5" : "border-white/10 bg-black/40 opacity-50 grayscale"}`}
              >
                {" "}
                <div
                  className={`p-3 rounded-full border-2 ${ach.unlocked ? "border-accent text-accent" : "border-gray-600 text-gray-600"}`}
                >
                  {" "}
                  {ach.unlocked ? ach.icon : <Lock size={24} />}{" "}
                </div>{" "}
                <div>
                  {" "}
                  <h4
                    className={`font-['Orbitron'] font-bold text-sm ${ach.unlocked ? "text-white" : "text-gray-500"}`}
                  >
                    {ach.title}
                  </h4>{" "}
                  <p className="text-xs text-gray-400 font-sans mt-1">
                    {ach.desc}
                  </p>{" "}
                </div>{" "}
              </div>
            ))}
          </div>
        );
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
                        <span className="truncate">
                          {res.display_name || res.name}
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
                        onClick={() => handleScanSource(res.id)}
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
      case "SYSTEM":
        return (
          <div className="space-y-8 animate-in slide-in-from-right-4 fade-in duration-300 max-w-2xl">
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
            { id: "IDENTITY", icon: <User size={18} />, label: "身份信息" },
            { id: "HISTORY", icon: <Clock size={18} />, label: "播放历史" },
            { id: "VAULT", icon: <Shield size={18} />, label: "数据保险库" },
            {
              id: "LEADERBOARD",
              icon: <Trophy size={18} />,
              label: "综合排行榜",
            },
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
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
          <div
            className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={closeAddModal}
          ></div>
          <div
            className={`relative bg-[#0a0a12] border border-white/10 rounded-2xl w-full ${selectedProtocol ? "max-w-5xl max-h-[90vh]" : "max-w-4xl max-h-[90vh]"} flex flex-col shadow-[0_0_50px_rgba(0,0,0,0.8)] p-6 md:p-8 animate-in zoom-in-95 duration-200 transition-all`}
          >
            <div className="flex justify-between items-center mb-6 border-b border-white/5 pb-4 shrink-0">
              <h3 className="text-xl font-['Orbitron'] font-bold text-white flex items-center gap-3">
                <div className="p-2 bg-primary/10 text-primary rounded-lg shadow-[0_0_15px_var(--color-primary)]">
                  <Server size={20} />
                </div>
                接入新链路协议
              </h3>
              <button
                onClick={closeAddModal}
                className="text-gray-500 hover:text-red-500 hover:bg-red-500/10 p-2 rounded-xl transition-all"
              >
                <X size={20} />
              </button>
            </div>

            {!selectedProtocol ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 animate-in fade-in slide-in-from-bottom-4 duration-300 overflow-y-auto custom-scrollbar pr-2 pb-2">
                {providerTypes.map((p) => (
                  <button
                    key={p.type}
                    onClick={() => handleSelectProtocol(p)}
                    className="group relative overflow-hidden rounded-2xl bg-black/40 border border-white/10 hover:border-primary/50 hover:shadow-[0_8px_30px_-10px_var(--color-primary)] hover:-translate-y-1 transition-all duration-300 text-left p-5 min-h-[140px] flex flex-col justify-between"
                  >
                    {/* Vibrant dynamic gradient on hover */}
                    <div className="absolute inset-0 bg-gradient-to-br from-primary/20 via-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"></div>

                    {/* Background scanlines - subtly softened */}
                    <div className="absolute inset-0 bg-[repeating-linear-gradient(45deg,transparent,transparent_2px,rgba(255,255,255,0.01)_2px,rgba(255,255,255,0.01)_4px)] pointer-events-none opacity-40 group-hover:opacity-80 transition-opacity duration-300"></div>

                    {/* Inner glowing halo */}
                    <div className="absolute inset-0 rounded-2xl border-2 border-primary/0 group-hover:border-primary/10 bg-blend-overlay transition-colors pointer-events-none drop-shadow-[inset_0_0_15px_var(--color-primary)] opacity-0 group-hover:opacity-100"></div>

                    <div className="relative z-10 flex items-start justify-between">
                      <div className="text-gray-400 group-hover:text-primary transition-all duration-300 bg-white/5 group-hover:bg-primary/10 p-2.5 rounded-xl group-hover:drop-shadow-[0_0_12px_var(--color-primary)] group-hover:scale-110">
                        {p.type === "local" ? (
                          <HardDrive size={20} />
                        ) : p.type === "alist" ? (
                          <Box size={20} />
                        ) : p.type === "webdav" ? (
                          <Globe size={20} />
                        ) : (
                          <Network size={20} />
                        )}
                      </div>

                      {p.status !== "stable" && (
                        <div className="px-2 py-0.5 rounded-sm bg-orange-500/10 border border-orange-500/20 text-[9px] text-orange-400 font-['Orbitron'] tracking-wider">
                          BETA
                        </div>
                      )}
                    </div>

                    <div className="relative z-10 mt-5">
                      <div className="font-['Orbitron'] font-bold text-gray-300 group-hover:text-white transition-colors tracking-wide text-sm">
                        {p.display_name}
                      </div>

                      <div className="flex gap-1.5 mt-3 flex-wrap">
                        {p.capabilities?.stream && (
                          <span className="text-[9px] font-mono px-1.5 py-0.5 bg-green-500/10 text-green-400 border border-green-500/20 rounded-sm">
                            STRM
                          </span>
                        )}
                        {p.capabilities?.health_check && (
                          <span className="text-[9px] font-mono px-1.5 py-0.5 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-sm">
                            HLTH
                          </span>
                        )}
                        {p.capabilities?.scan && (
                          <span className="text-[9px] font-mono px-1.5 py-0.5 bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 rounded-sm">
                            SCAN
                          </span>
                        )}
                        {p.capabilities?.preview && (
                          <span className="text-[9px] font-mono px-1.5 py-0.5 bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded-sm">
                            PRVW
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 animate-in fade-in slide-in-from-right-4 duration-300 flex-1 overflow-hidden min-h-0">
                {/* Left Column: Form */}
                <div className="flex flex-col h-full overflow-hidden">
                  <div className="flex items-center justify-between font-['Orbitron'] border-b border-white/10 pb-4 shrink-0 mb-4">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setSelectedProtocol(null)}
                        className="text-gray-400 hover:text-white transition-colors p-1.5 hover:bg-white/5 rounded-lg"
                      >
                        <ChevronLeft size={18} />
                      </button>
                      <span className="text-primary font-bold flex items-center gap-2 drop-shadow-[0_0_8px_var(--color-primary)] text-lg">
                        <span className="opacity-90">
                          {selectedProtocol.type === "local" ? (
                            <HardDrive size={20} />
                          ) : (
                            <Cloud size={20} />
                          )}
                        </span>
                        {selectedProtocol.display_name}
                      </span>
                    </div>
                  </div>

                  <div className="space-y-5 flex-1 custom-scrollbar overflow-y-auto pr-2 pb-2">
                    <div>
                      <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase">
                        Alias <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="text"
                        value={newSourceName}
                        onChange={(e) => setNewSourceName(e.target.value)}
                        placeholder="例如：电影节点 Alpha"
                        className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:shadow-[0_0_15px_rgba(var(--color-primary-rgb),0.1)] transition-all font-sans"
                      />
                    </div>

                    <div className="grid grid-cols-1 gap-4">
                      {selectedProtocol.config_fields?.map((field) => (
                        <div key={field.name}>
                          <label
                            className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase"
                            title={field.description}
                          >
                            {field.name}{" "}
                            {field.required && (
                              <span className="text-red-500">*</span>
                            )}
                          </label>
                          {field.type === "boolean" ? (
                            <div className="flex items-center gap-4 bg-black/40 border border-white/5 rounded-lg p-2">
                              <button
                                type="button"
                                onClick={() =>
                                  setNewSourceConfig({
                                    ...newSourceConfig,
                                    [field.name]: true,
                                  })
                                }
                                className={`flex-1 flex justify-center items-center gap-2 py-1.5 rounded transition-all ${newSourceConfig[field.name] === true ? "bg-primary/20 text-primary shadow-[inset_0_0_8px_rgba(var(--color-primary-rgb),0.2)]" : "text-gray-500 hover:bg-white/5 hover:text-gray-300"}`}
                              >
                                <Check
                                  size={14}
                                  className={
                                    newSourceConfig[field.name] === true
                                      ? "opacity-100"
                                      : "opacity-0"
                                  }
                                />{" "}
                                Yes
                              </button>
                              <button
                                type="button"
                                onClick={() =>
                                  setNewSourceConfig({
                                    ...newSourceConfig,
                                    [field.name]: false,
                                  })
                                }
                                className={`flex-1 flex justify-center items-center gap-2 py-1.5 rounded transition-all ${newSourceConfig[field.name] === false || newSourceConfig[field.name] === undefined ? "bg-white/10 text-white shadow-[inset_0_0_8px_rgba(255,255,255,0.1)]" : "text-gray-500 hover:bg-white/5 hover:text-gray-300"}`}
                              >
                                <X
                                  size={14}
                                  className={
                                    newSourceConfig[field.name] === false ||
                                    newSourceConfig[field.name] === undefined
                                      ? "opacity-100"
                                      : "opacity-0"
                                  }
                                />{" "}
                                No
                              </button>
                            </div>
                          ) : (
                            <input
                              type={
                                field.type === "string" &&
                                field.name.includes("password")
                                  ? "password"
                                  : field.type === "number"
                                    ? "number"
                                    : "text"
                              }
                              placeholder={
                                field.description || `Input ${field.name}`
                              }
                              value={newSourceConfig[field.name] || ""}
                              onChange={(e) =>
                                setNewSourceConfig({
                                  ...newSourceConfig,
                                  [field.name]:
                                    e.target.type === "number"
                                      ? Number(e.target.value)
                                      : e.target.value,
                                })
                              }
                              className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-sm text-white focus:outline-none focus:shadow-[0_0_15px_rgba(var(--color-primary-rgb),0.1)] transition-all font-mono"
                            />
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="pt-4 border-t border-white/10 flex justify-between gap-3 items-center shrink-0">
                    <button
                      onClick={handlePreviewDirectory}
                      disabled={isPreviewing}
                      className="px-4 py-2 rounded-lg bg-[#0a0a12] border border-primary/30 text-primary hover:bg-primary/10 hover:border-primary transition-all flex items-center gap-2 text-xs font-['Orbitron'] disabled:opacity-50 min-w-[140px] justify-center group"
                    >
                      {isPreviewing ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : (
                        <FolderSearch
                          size={14}
                          className="group-hover:scale-110 transition-transform"
                        />
                      )}
                      连通测试与预览
                    </button>
                    <button
                      onClick={handleAddSource}
                      className="flex-1 py-2 rounded-lg bg-primary/20 border border-primary text-primary hover:bg-primary hover:text-black hover:shadow-[0_0_20px_var(--color-primary)] text-sm font-['Orbitron'] font-bold transition-all flex items-center justify-center gap-2 group"
                    >
                      <Check
                        size={16}
                        className="group-hover:scale-110 transition-transform"
                      />{" "}
                      挂载节点
                    </button>
                  </div>
                </div>

                {/* Right Column: Preview Panel */}
                <div className="border border-primary/20 bg-[#0a0a12] rounded-xl flex flex-col overflow-hidden relative shadow-[inset_0_0_20px_rgba(var(--color-primary-rgb),0.05)] h-full">
                  <div className="absolute inset-0 bg-[repeating-linear-gradient(0deg,transparent,transparent_2px,rgba(var(--color-primary-rgb),0.02)_2px,rgba(var(--color-primary-rgb),0.02)_4px)] pointer-events-none"></div>
                  <div className="absolute top-0 right-0 w-48 h-48 bg-gradient-to-bl from-primary/10 to-transparent pointer-events-none"></div>

                  <div className="px-4 py-3 border-b border-primary/20 flex items-center justify-between bg-primary/5 relative z-10">
                    <div className="flex items-center gap-2">
                      <Terminal size={14} className="text-primary" />
                      <span className="text-xs font-['Orbitron'] text-primary tracking-widest font-bold">
                        TERMINAL LINK / PREVIEW
                      </span>
                    </div>
                    <div className="flex gap-1">
                      <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></div>
                      <div className="w-1.5 h-1.5 rounded-full bg-primary/50"></div>
                      <div className="w-1.5 h-1.5 rounded-full bg-primary/20"></div>
                    </div>
                  </div>

                  <div className="flex-1 p-4 overflow-y-auto custom-scrollbar relative">
                    {isPreviewing && (
                      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm z-10 flex flex-col items-center justify-center text-primary font-['Orbitron'] gap-3">
                        <Loader2 size={32} className="animate-spin" />
                        <span className="text-sm tracking-widest animate-pulse">
                          ESTABLISHING UPLINK...
                        </span>
                      </div>
                    )}

                    {!previewData && !previewError && !isPreviewing && (
                      <div className="h-full flex flex-col items-center justify-center text-gray-600 gap-3">
                        <Box size={48} className="opacity-20" strokeWidth={1} />
                        <p className="text-xs font-['Orbitron'] tracking-wide">
                          填写左侧信息并进行连通测试
                        </p>
                      </div>
                    )}

                    {previewError && !isPreviewing && (
                      <div className="h-full flex flex-col items-center justify-center text-red-500/80 gap-3">
                        <AlertTriangle
                          size={48}
                          className="opacity-50"
                          strokeWidth={1}
                        />
                        <p className="text-xs text-center max-w-[80%]">
                          {previewError}
                        </p>
                      </div>
                    )}

                    {previewData && !isPreviewing && (
                      <div className="space-y-1 font-mono text-xs">
                        <div className="flex items-center gap-2 text-primary mb-3 pb-2 border-b border-white/5">
                          <FolderTree size={14} />
                          <span className="opacity-80 truncate flex-1">
                            CONNECTED: {previewPath}
                          </span>
                          {previewPath !== "/" && previewPath !== "" && (
                            <button
                              onClick={handleNavigateUp}
                              className="ml-auto px-2 py-0.5 rounded bg-white/10 hover:bg-primary/20 hover:text-primary transition-colors border border-white/5 hover:border-primary text-[10px] text-white"
                            >
                              UP DIR
                            </button>
                          )}
                        </div>
                        {previewData.map((item, idx) => (
                          <div
                            key={idx}
                            onClick={() =>
                              item.type === "dir"
                                ? handleNavigateDown(item.path)
                                : null
                            }
                            className={`flex items-center gap-2 py-1.5 px-2 rounded group text-gray-300 ${item.type === "dir" ? "hover:bg-primary/20 cursor-pointer pointer-events-auto border border-transparent hover:border-primary/30" : "hover:bg-white/5 border border-transparent"}`}
                          >
                            {item.type === "dir" ? (
                              <ChevronRight
                                size={12}
                                className="text-blue-400 opacity-50 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all"
                              />
                            ) : (
                              <div className="w-3"></div>
                            )}
                            {item.type === "dir" ? (
                              <FolderTree size={12} className="text-blue-400" />
                            ) : (
                              <FileText size={12} className="text-gray-500" />
                            )}
                            <span
                              className={`truncate flex-1 transition-colors ${item.type === "dir" ? "group-hover:text-primary font-bold" : "group-hover:text-white"}`}
                            >
                              {item.name}
                            </span>
                            {item.size != null && (
                              <span className="text-[10px] text-gray-600 group-hover:text-gray-400 shrink-0">
                                {Math.round(item.size / 1024)} KB
                              </span>
                            )}
                          </div>
                        ))}
                        {previewData.length === 0 && (
                          <div className="text-gray-600 text-center py-6 text-[10px] bg-black/20 rounded-lg border border-white/5">
                            目录为空 (EMPTY DIRECTORY)
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
