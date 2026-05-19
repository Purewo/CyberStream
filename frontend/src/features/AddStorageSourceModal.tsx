import React, { useState } from 'react';
import { X, Server, HardDrive, Box, Globe, Network, ChevronLeft, ChevronRight, Cloud, Check, Loader2, Terminal, FolderSearch, FolderTree, FileText, AlertTriangle } from 'lucide-react';
import { storageService } from '../api';
import { toast } from '../utils';

interface AddStorageSourceModalProps {
  providerTypes: import('../types').StorageProviderType[];
  onClose: () => void;
  onSuccess: () => void;
}

export const AddStorageSourceModal: React.FC<AddStorageSourceModalProps> = ({ providerTypes, onClose, onSuccess }) => {
  const [selectedProtocol, setSelectedProtocol] = useState<import('../types').StorageProviderType | null>(null);
  const [newSourceName, setNewSourceName] = useState('');
  const [newSourceConfig, setNewSourceConfig] = useState<Record<string, any>>({});
  
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewData, setPreviewData] = useState<any[] | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewPath, setPreviewPath] = useState<string>('/');

  const handleSelectProtocol = (protocol: any) => {
    setSelectedProtocol(protocol);
    const defaultConfig: Record<string, any> = {};
    if (protocol.config_fields) {
      protocol.config_fields.forEach((field: any) => {
        if (field.default !== undefined) {
          defaultConfig[field.name] = field.default;
        } else if (field.type === "boolean") {
          defaultConfig[field.name] = true;
        }
      });
    }
    setNewSourceConfig(defaultConfig);
    setPreviewData(null);
    setPreviewError(null);
    setPreviewPath("/");
  };

  const handlePreviewDirectory = async (pathOverride?: string) => {
    if (!selectedProtocol) return;
    setIsPreviewing(true);
    setPreviewError(null);
    const targetPath = typeof pathOverride === "string" ? pathOverride : previewPath;
    try {
      const { items, error } = await storageService.previewStorage(
        selectedProtocol.type,
        newSourceConfig,
        targetPath,
      );
      if (items !== null) {
        setPreviewData(items);
        setPreviewPath(targetPath);
      } else {
        setPreviewError(error || "Preview failed");
        setPreviewData(null);
      }
    } catch (e: any) {
      setPreviewError(e.message || "Unknown error occurred");
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleNavigateDown = (folderName: string) => {
    const newPath = previewPath.endsWith("/")
      ? `${previewPath}${folderName}`
      : `${previewPath}/${folderName}`;
    handlePreviewDirectory(newPath);
  };

  const handleNavigateUp = () => {
    if (previewPath === "/") return;
    const parts = previewPath.split("/").filter(Boolean);
    parts.pop();
    const p = "/" + parts.join("/");
    handlePreviewDirectory(p);
  };

  const handleAddSource = async () => {
    if (!newSourceName || !selectedProtocol) return;

    let finalConfig = { ...newSourceConfig };
    if (previewPath && previewPath !== "/") {
      const pathField = selectedProtocol.config_fields?.find((f: any) => f.name === 'root' || f.name === 'path' || f.name === 'folder');
      if (pathField) {
        finalConfig[pathField.name] = previewPath;
      }
    }

    const success = await storageService.addSource(
      newSourceName,
      selectedProtocol.type,
      finalConfig,
    );
    if (success) {
      toast.success("存储节点已成功挂载");
      onSuccess();
    } else {
      toast.error("添加存储源失败");
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
      <div
        className="absolute inset-0 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={onClose}
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
            onClick={onClose}
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
                <div className="absolute inset-0 bg-gradient-to-br from-primary/20 via-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"></div>
                <div className="absolute inset-0 bg-[repeating-linear-gradient(45deg,transparent,transparent_2px,rgba(255,255,255,0.01)_2px,rgba(255,255,255,0.01)_4px)] pointer-events-none opacity-40 group-hover:opacity-80 transition-opacity duration-300"></div>
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

              <div className="pt-4 border-t border-white/10 flex flex-col gap-3 shrink-0">
                {previewPath && previewPath !== "/" && (
                  <div className="text-xs text-primary/70 bg-primary/5 px-3 py-2 rounded border border-primary/20 flex items-center gap-2">
                    <Check size={12} />
                    <span>挂载时将以当前预览目录 <strong>{previewPath}</strong> 作为根目录</span>
                  </div>
                )}
                <div className="flex justify-between gap-3 items-center">
                  <button
                    onClick={() => handlePreviewDirectory()}
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
            </div>

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
                            ? handleNavigateDown(item.name)
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
  );
};
