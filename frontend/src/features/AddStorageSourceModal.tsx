import React, { useState, useEffect, useRef } from 'react';
import { X, Server, HardDrive, Box, Globe, Network, ChevronLeft, ChevronRight, Cloud, Check, Loader2, Terminal, FolderSearch, FolderTree, FileText, AlertTriangle, Smartphone, KeyRound, RefreshCw, QrCode, ExternalLink, Eye, EyeOff } from 'lucide-react';
import { storageService } from '../api';
import { toast } from '../utils';
import { shellOpen } from '../platform';

interface AddStorageSourceModalProps {
  providerTypes: import('../types').StorageProviderType[];
  onClose: () => void;
  onSuccess: () => void;
}

export const AddStorageSourceModal: React.FC<AddStorageSourceModalProps> = ({ providerTypes, onClose, onSuccess }) => {
  const [selectedProtocol, setSelectedProtocol] = useState<import('../types').StorageProviderType | null>(null);
  const [newSourceName, setNewSourceName] = useState('');
  const [newSourceConfig, setNewSourceConfig] = useState<Record<string, any>>({});
  const [revealedFields, setRevealedFields] = useState<Record<string, boolean>>({});

  const [isPreviewing, setIsPreviewing] = useState(false);
  const [previewData, setPreviewData] = useState<any[] | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewPath, setPreviewPath] = useState<string>('/');

  // ─── 托管光鸭 SMS 登录 state ───
  // 这条路径独立于通用 alist/webdav 表单：用户填手机号 → 后端发短信 →
  // 用户填验证码 → 后端 verify 后挂载完成。中间任何错误都允许用户在第二步
  // 重试或退回第一步重发码。
  const [smsStep, setSmsStep] = useState<'phone' | 'code'>('phone');
  const [smsName, setSmsName] = useState('光鸭云盘');
  const [smsPhone, setSmsPhone] = useState('+86');
  const [smsRootPath, setSmsRootPath] = useState('');
  const [smsSourceId, setSmsSourceId] = useState<number | null>(null);
  const [smsMaskedPhone, setSmsMaskedPhone] = useState<string>('');
  const [smsCode, setSmsCode] = useState('');
  const [smsBusy, setSmsBusy] = useState(false);
  const isManagedGuangyapan = selectedProtocol?.type === 'guangyapan';

  // ─── 托管二维码登录 state（天翼 / 夸克 / UC / 115 / 阿里 共用） ───
  // 全部走完全一样的两步流程：start → 轮询 poll，差别仅在路径前缀（provider slug）
  // 和 quarktv/uctv 多一个 link_method 字段（默认 download）。整套 state 抽公用。
  const [tyQrName, setTyQrName] = useState('');
  const [tyQrSourceId, setTyQrSourceId] = useState<number | null>(null);
  const [tyQrDataUrl, setTyQrDataUrl] = useState<string>('');
  const [tyQrBusy, setTyQrBusy] = useState(false);
  const [tyQrPolling, setTyQrPolling] = useState(false);
  const [tyQrPendingMsg, setTyQrPendingMsg] = useState<string>('');
  const tyQrPollTimer = useRef<number | null>(null);
  // 115cloud 专属：扫码端类型。空字符串 = 不传，由后端兜底（默认 wechatmini）。
  // 其他 provider 不读这个 state。
  const [tyQrCodeSource, setTyQrCodeSource] = useState<string>('');
  const [tyQrShowAdvanced, setTyQrShowAdvanced] = useState(false);
  const QR_PROVIDER_SLUGS = new Set(['tianyicloud', 'quarktv', 'uctv', '115cloud', 'aliyundrive']);
  const isManagedQrProvider =
    !!selectedProtocol?.type && QR_PROVIDER_SLUGS.has(selectedProtocol.type);

  // ─── 托管 OAuth 登录 state（百度网盘） ───
  // 走完全独立的两步流程：start 拿 authorization_url → 浏览器跳转 → poll 状态机
  // (oauth_pending → ready | oauth_failed)。前端不解析回调 URL，回调由后端处理，
  // 前端只轮询状态。
  const OAUTH_PROVIDER_SLUGS = new Set(['baidunetdisk']);
  const isManagedOauthProvider =
    !!selectedProtocol?.type && OAUTH_PROVIDER_SLUGS.has(selectedProtocol.type);
  const [oauthName, setOauthName] = useState('');
  const [oauthSourceId, setOauthSourceId] = useState<number | null>(null);
  const [oauthAuthUrl, setOauthAuthUrl] = useState<string>('');
  const [oauthBusy, setOauthBusy] = useState(false);
  const [oauthPolling, setOauthPolling] = useState(false);
  const [oauthPendingMsg, setOauthPendingMsg] = useState<string>('');
  const oauthPollTimer = useRef<number | null>(null);

  // 卸载时清掉轮询定时器，避免组件 unmount 后还在 setState
  useEffect(() => {
    return () => {
      if (tyQrPollTimer.current !== null) {
        window.clearTimeout(tyQrPollTimer.current);
        tyQrPollTimer.current = null;
      }
      if (oauthPollTimer.current !== null) {
        window.clearTimeout(oauthPollTimer.current);
        oauthPollTimer.current = null;
      }
    };
  }, []);

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
    // 切到光鸭走 SMS 流程；任何切换都重置 SMS state，否则切回去能看到上一次
    // 残留的 sourceId（已经被后端挂载了，走 verify 会撞）。
    setSmsStep('phone');
    setSmsCode('');
    setSmsSourceId(null);
    setSmsMaskedPhone('');
    setSmsBusy(false);
    if (protocol.type === 'guangyapan') {
      setSmsName(protocol.display_name || '光鸭云盘');
    }
    // 切到托管二维码（天翼/夸克/UC）也得清掉上一次的二维码 state，否则换 protocol 还显示旧码
    if (tyQrPollTimer.current !== null) {
      window.clearTimeout(tyQrPollTimer.current);
      tyQrPollTimer.current = null;
    }
    setTyQrSourceId(null);
    setTyQrDataUrl('');
    setTyQrPolling(false);
    setTyQrPendingMsg('');
    setTyQrBusy(false);
    setTyQrCodeSource('');
    setTyQrShowAdvanced(false);
    if (QR_PROVIDER_SLUGS.has(protocol.type)) {
      setTyQrName(protocol.display_name || protocol.type);
    }
    // 切到托管 OAuth（百度网盘）也清理一次。
    if (oauthPollTimer.current !== null) {
      window.clearTimeout(oauthPollTimer.current);
      oauthPollTimer.current = null;
    }
    setOauthSourceId(null);
    setOauthAuthUrl('');
    setOauthPolling(false);
    setOauthPendingMsg('');
    setOauthBusy(false);
    if (OAUTH_PROVIDER_SLUGS.has(protocol.type)) {
      setOauthName(protocol.display_name || protocol.type);
    }
  };

  // ─── 托管光鸭：发码 ───
  const handleSendGuangyapanSms = async () => {
    const phone = smsPhone.trim();
    if (!phone || phone === '+86') {
      toast.error('请填写手机号');
      return;
    }
    setSmsBusy(true);
    try {
      const res = await storageService.startGuangyapanSms({
        phone_number: phone,
        name: smsName.trim() || '光鸭云盘',
        root_path: smsRootPath.trim(),
      });
      if (!res.ok) {
        toast.error(res.msg || '发送验证码失败');
        return;
      }
      const id = res.data?.source?.id;
      if (typeof id !== 'number') {
        toast.error('后端未返回 source id');
        return;
      }
      setSmsSourceId(id);
      setSmsMaskedPhone(res.data?.source?.config?.phone_number_masked || phone);
      setSmsStep('code');
      toast.success('验证码已发送');
    } finally {
      setSmsBusy(false);
    }
  };

  // ─── 托管光鸭：校验 ───
  const handleVerifyGuangyapanSms = async () => {
    if (smsSourceId === null) {
      toast.error('未拿到 source id，请退回上一步重新发送验证码');
      return;
    }
    const code = smsCode.trim();
    if (!code) {
      toast.error('请填写验证码');
      return;
    }
    setSmsBusy(true);
    try {
      const res = await storageService.verifyGuangyapanSms(smsSourceId, code);
      if (!res.ok) {
        toast.error(res.msg || '验证码校验失败');
        return;
      }
      const authState = res.data?.auth_state;
      if (authState !== 'ready') {
        toast.error(`挂载未就绪 (${authState ?? 'unknown'})`);
        return;
      }
      toast.success('光鸭云盘挂载成功');
      onSuccess();
    } finally {
      setSmsBusy(false);
    }
  };

  // ─── 托管二维码：发起（天翼 / 夸克 / UC 共用） ───
  // start 成功后立刻把 source.id 落进 state 并启动轮询。
  // QuarkTV / UCTV 多带一个 link_method=download（文档建议联调期默认值）。
  const handleStartTianyicloudQr = async () => {
    if (!selectedProtocol) return;
    const slug = selectedProtocol.type;
    const params: { name?: string; link_method?: 'download' | 'streaming'; qrcode_source?: any } = {
      name: tyQrName.trim() || selectedProtocol.display_name || slug,
    };
    if (slug === 'quarktv' || slug === 'uctv') {
      params.link_method = 'download';
    }
    if (slug === '115cloud' && tyQrCodeSource) {
      params.qrcode_source = tyQrCodeSource;
    }
    setTyQrBusy(true);
    try {
      const res = await storageService.startManagedQrLogin(slug, params);
      if (!res.ok) {
        toast.error(res.msg || '生成二维码失败');
        return;
      }
      const sid = res.data?.source?.id;
      const dataUrl = res.data?.qr_code_data_url || '';
      if (typeof sid !== 'number' || !dataUrl) {
        toast.error('后端响应缺少 source.id 或 qr_code_data_url');
        return;
      }
      setTyQrSourceId(sid);
      setTyQrDataUrl(dataUrl);
      setTyQrPendingMsg(`请用 ${selectedProtocol.display_name || slug} App 扫码并在手机上确认`);
      setTyQrPolling(true);
      // 2.5s 一次轮询，跟文档建议的 2-3s 节流。
      tyQrPollTimer.current = window.setTimeout(() => pollTianyicloudQrLoop(sid), 2500);
    } finally {
      setTyQrBusy(false);
    }
  };

  // ─── 托管二维码：轮询（天翼 / 夸克 / UC 共用） ───
  // 三种结果：authenticated=true → ready，关弹窗；authenticated=false → 继续轮询；
  // 后端返回新的 qr_code_data_url → 替换图片（OpenList 侧二维码刷新了）。
  const pollTianyicloudQrLoop = async (sid: number) => {
    if (!selectedProtocol) return;
    const slug = selectedProtocol.type;
    const res = await storageService.pollManagedQrLogin(slug, sid);
    if (!res.ok) {
      // 单次失败不打断轮询；后端可能瞬时抖动。但要 surface 给用户。
      setTyQrPendingMsg(res.msg || '轮询失败，正在重试');
      tyQrPollTimer.current = window.setTimeout(() => pollTianyicloudQrLoop(sid), 2500);
      return;
    }
    const data = res.data || {};
    if (data.authenticated === true && data.auth_state === 'ready') {
      setTyQrPolling(false);
      setTyQrPendingMsg('');
      tyQrPollTimer.current = null;
      toast.success(`${selectedProtocol.display_name || slug} 挂载成功`);
      onSuccess();
      return;
    }
    // 终态：二维码过期 / 用户取消。停止轮询，提示用户点「重新生成」。
    // 文档明确这两种业务码仍为 200，不能当错误丢，但要把图变灰、停掉 timer。
    if (data.auth_state === 'qr_expired' || data.auth_state === 'qr_canceled') {
      setTyQrPolling(false);
      tyQrPollTimer.current = null;
      const reason = data.auth_state === 'qr_expired'
        ? '二维码已过期，请点击「重新生成」'
        : '登录已取消，请点击「重新生成」';
      setTyQrPendingMsg(reason);
      toast.error(reason);
      return;
    }
    // 未完成时如果后端给了新二维码，替换之
    const newDataUrl: string | undefined = data.qr_code_data_url;
    if (newDataUrl && newDataUrl !== tyQrDataUrl) {
      setTyQrDataUrl(newDataUrl);
    }
    const reason = data.pending_reason || '';
    if (reason === 'waiting_for_scan') {
      setTyQrPendingMsg('等待扫码…');
    } else if (reason === 'waiting_for_confirm') {
      setTyQrPendingMsg('已扫码，请在 App 内确认登录');
    } else if (reason) {
      setTyQrPendingMsg(`等待中：${reason}`);
    }
    tyQrPollTimer.current = window.setTimeout(() => pollTianyicloudQrLoop(sid), 2500);
  };

  // ─── 托管 OAuth：发起（百度网盘） ───
  // start 成功后拿到 authorization_url，立刻用平台 shellOpen 打开浏览器跳转，
  // 同时把 source.id 落进 state 并启动轮询。OAuth 没有"重新生成"的概念，
  // 用户取消授权或失败后通过「重新授权」按钮再发一次 start。
  const handleStartBaiduOauth = async () => {
    if (!selectedProtocol) return;
    const slug = selectedProtocol.type;
    setOauthBusy(true);
    try {
      const res = await storageService.startManagedOauthLogin(slug, {
        name: oauthName.trim() || selectedProtocol.display_name || slug,
      });
      if (!res.ok) {
        toast.error(res.msg || '启动 OAuth 授权失败');
        return;
      }
      const sid = res.data?.source?.id;
      const authUrl = res.data?.authorization_url || '';
      if (typeof sid !== 'number' || !authUrl) {
        toast.error('后端响应缺少 source.id 或 authorization_url');
        return;
      }
      setOauthSourceId(sid);
      setOauthAuthUrl(authUrl);
      setOauthPendingMsg(`已打开浏览器，请在 ${selectedProtocol.display_name || slug} 完成授权`);
      setOauthPolling(true);
      try {
        await shellOpen(authUrl);
      } catch (e: any) {
        // 打开浏览器失败不阻断流程，给个手动复制兜底
        console.warn('[oauth] shellOpen failed', e);
        toast.info('未能自动打开浏览器，请手动点击下方链接');
      }
      // 2.5s 一次轮询，跟 QR 同节流。
      oauthPollTimer.current = window.setTimeout(() => pollBaiduOauthLoop(sid), 2500);
    } finally {
      setOauthBusy(false);
    }
  };

  // ─── 托管 OAuth：轮询（百度网盘） ───
  // 三种结果：authenticated=true && auth_state=ready → 关弹窗；
  // auth_state=oauth_failed → 停止轮询提示重试；其他 → 继续轮询。
  const pollBaiduOauthLoop = async (sid: number) => {
    if (!selectedProtocol) return;
    const slug = selectedProtocol.type;
    const res = await storageService.pollManagedOauthLogin(slug, sid);
    if (!res.ok) {
      setOauthPendingMsg(res.msg || '轮询失败，正在重试');
      oauthPollTimer.current = window.setTimeout(() => pollBaiduOauthLoop(sid), 2500);
      return;
    }
    const data = res.data || {};
    if (data.authenticated === true && data.auth_state === 'ready') {
      setOauthPolling(false);
      setOauthPendingMsg('');
      oauthPollTimer.current = null;
      toast.success(`${selectedProtocol.display_name || slug} 挂载成功`);
      onSuccess();
      return;
    }
    if (data.auth_state === 'oauth_failed') {
      setOauthPolling(false);
      oauthPollTimer.current = null;
      const reason = data.error_message
        ? `授权失败：${data.error_message}`
        : '授权失败，请点击「重新授权」';
      setOauthPendingMsg(reason);
      toast.error(reason);
      return;
    }
    const reason = data.pending_reason || '';
    if (reason === 'waiting_for_authorization') {
      setOauthPendingMsg('请在浏览器中完成百度网盘授权…');
    } else if (reason) {
      setOauthPendingMsg(`等待中：${reason}`);
    }
    oauthPollTimer.current = window.setTimeout(() => pollBaiduOauthLoop(sid), 2500);
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
    const pathField = selectedProtocol.config_fields?.find((f: any) => f.name === 'root' || f.name === 'path' || f.name === 'folder');
    if (previewPath && previewPath !== "/") {
      if (pathField) {
        finalConfig[pathField.name] = previewPath;
      }
    }

    if (pathField) {
      const filledPath = (finalConfig[pathField.name] || '').trim();
      if (!filledPath) {
        toast.error("请先填写路径，或点击「连通测试与预览」选择目录后再挂载");
        return;
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
          (() => {
            // 分两类：基础协议（local/alist/openlist/webdav/smb/ftp 等"自架/裸协议"）
            // 和 网盘（托管型云盘：guangyapan/tianyicloud/quarktv/uctv/115cloud/aliyundrive/baidunetdisk）。
            // 网盘的硬编码白名单 = QR_PROVIDER_SLUGS ∪ OAUTH_PROVIDER_SLUGS ∪ {guangyapan}；其余都归基础协议。
            const CLOUD_DRIVE_TYPES = new Set([
              ...QR_PROVIDER_SLUGS,
              ...OAUTH_PROVIDER_SLUGS,
              'guangyapan',
            ]);
            const baseProtocols = providerTypes.filter((p) => !CLOUD_DRIVE_TYPES.has(p.type));
            const cloudDrives = providerTypes.filter((p) => CLOUD_DRIVE_TYPES.has(p.type));

            const renderCard = (p: import('../types').StorageProviderType) => (
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
                    ) : p.type === "guangyapan" ? (
                      <Smartphone size={20} />
                    ) : p.type === "tianyicloud" || p.type === "quarktv" || p.type === "uctv" || p.type === "115cloud" || p.type === "aliyundrive" ? (
                      <QrCode size={20} />
                    ) : p.type === "baidunetdisk" ? (
                      <KeyRound size={20} />
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
            );

            const renderSection = (
              title: string,
              subtitle: string,
              items: import('../types').StorageProviderType[],
            ) => (
              <div className="space-y-3">
                <div className="flex items-baseline gap-3 px-1">
                  <h4 className="text-xs font-['Orbitron'] tracking-[0.25em] text-primary uppercase">
                    {title}
                  </h4>
                  <span className="text-[10px] text-gray-500 font-['Rajdhani']">{subtitle}</span>
                  <div className="flex-1 h-[1px] bg-gradient-to-r from-primary/30 to-transparent"></div>
                  <span className="text-[10px] text-gray-600 font-mono">{items.length}</span>
                </div>
                {items.length > 0 ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
                    {items.map(renderCard)}
                  </div>
                ) : (
                  <div className="text-[11px] text-gray-600 font-['Rajdhani'] px-1">无可用项</div>
                )}
              </div>
            );

            return (
              <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300 overflow-y-auto custom-scrollbar pr-2 pb-2">
                {renderSection('基础协议', '本地 / 局域网 / 自架协议', baseProtocols)}
                {renderSection('网盘挂载', '托管登录，无需手动配置 OpenList / AList', cloudDrives)}
              </div>
            );
          })()
        ) : isManagedGuangyapan ? (
          // ─── 托管光鸭 SMS 登录 ───
          // 跟普通存储源完全分开：用户不接触 alist 内部参数。
          <div className="flex flex-col flex-1 overflow-y-auto custom-scrollbar pr-2 pb-2 max-w-2xl mx-auto w-full animate-in fade-in slide-in-from-right-4 duration-300">
            <div className="flex items-center gap-3 font-['Orbitron'] border-b border-white/10 pb-4 mb-6">
              <button
                onClick={() => setSelectedProtocol(null)}
                className="text-gray-400 hover:text-white transition-colors p-1.5 hover:bg-white/5 rounded-lg"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-primary font-bold flex items-center gap-2 drop-shadow-[0_0_8px_var(--color-primary)] text-lg">
                <Smartphone size={20} />
                {selectedProtocol.display_name}
              </span>
              <span className="ml-auto text-[10px] text-gray-500 font-['Rajdhani']">
                {smsStep === 'phone' ? '步骤 1 / 2 · 发送验证码' : '步骤 2 / 2 · 输入验证码'}
              </span>
            </div>

            {smsStep === 'phone' ? (
              <div className="space-y-5">
                <div>
                  <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase">
                    名称
                  </label>
                  <input
                    type="text"
                    value={smsName}
                    onChange={(e) => setSmsName(e.target.value)}
                    placeholder="光鸭云盘"
                    className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-sm text-white focus:outline-none transition-all"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase">
                    手机号 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="tel"
                    value={smsPhone}
                    onChange={(e) => setSmsPhone(e.target.value)}
                    placeholder="+8613800001234"
                    className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-sm text-white focus:outline-none transition-all font-mono"
                  />
                  <p className="mt-1.5 text-[10px] text-gray-600 font-['Rajdhani']">
                    建议带 +86 国家码；后端会发送光鸭云盘短信验证码到此号码
                  </p>
                </div>
                <div>
                  <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase">
                    云盘根路径（可选）
                  </label>
                  <input
                    type="text"
                    value={smsRootPath}
                    onChange={(e) => setSmsRootPath(e.target.value)}
                    placeholder="留空 = 整个云盘根目录"
                    className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-sm text-white focus:outline-none transition-all font-mono"
                  />
                </div>
                <div className="text-[11px] text-gray-500 font-['Rajdhani'] bg-white/[0.02] border border-white/5 rounded-lg p-3 leading-relaxed">
                  CyberStream 自动管理 AList，无需手动填写地址或账号。短信由光鸭云盘官方下发，发送后请在 60 秒内完成验证。
                </div>
                <button
                  onClick={handleSendGuangyapanSms}
                  disabled={smsBusy}
                  className="w-full py-2.5 rounded-lg bg-primary/20 border border-primary text-primary hover:bg-primary hover:text-black hover:shadow-[0_0_20px_var(--color-primary)] text-sm font-['Orbitron'] font-bold transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {smsBusy ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <Smartphone size={16} />
                  )}
                  发送验证码
                </button>
              </div>
            ) : (
              <div className="space-y-5">
                <div className="text-xs text-primary/80 bg-primary/5 border border-primary/20 rounded-lg p-3 flex items-center gap-2">
                  <Check size={14} />
                  验证码已发送至 <span className="font-mono font-bold">{smsMaskedPhone}</span>
                </div>
                <div>
                  <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase">
                    验证码 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={smsCode}
                    onChange={(e) => setSmsCode(e.target.value.replace(/\s+/g, ''))}
                    placeholder="收到的验证码"
                    autoFocus
                    inputMode="numeric"
                    className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-base text-white focus:outline-none transition-all font-mono tracking-[0.3em] text-center"
                  />
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      setSmsStep('phone');
                      setSmsCode('');
                      setSmsSourceId(null);
                    }}
                    disabled={smsBusy}
                    className="px-4 py-2.5 rounded-lg bg-[#0a0a12] border border-white/10 text-gray-400 hover:bg-white/5 hover:text-white transition-all text-xs font-['Orbitron'] disabled:opacity-50"
                  >
                    重新发送
                  </button>
                  <button
                    onClick={handleVerifyGuangyapanSms}
                    disabled={smsBusy}
                    className="flex-1 py-2.5 rounded-lg bg-primary/20 border border-primary text-primary hover:bg-primary hover:text-black hover:shadow-[0_0_20px_var(--color-primary)] text-sm font-['Orbitron'] font-bold transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {smsBusy ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <KeyRound size={16} />
                    )}
                    验证并完成挂载
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : isManagedQrProvider ? (
          // ─── 托管二维码登录（天翼 / 夸克 / UC 共用） ───
          // 用户不接触 OpenList 内部参数。点「生成二维码」拿到 base64 图片，
          // 旁边轮询状态；扫码确认后自动关弹窗。
          <div className="flex flex-col flex-1 overflow-y-auto custom-scrollbar pr-2 pb-2 max-w-2xl mx-auto w-full animate-in fade-in slide-in-from-right-4 duration-300">
            <div className="flex items-center gap-3 font-['Orbitron'] border-b border-white/10 pb-4 mb-6">
              <button
                onClick={() => {
                  if (tyQrPollTimer.current !== null) {
                    window.clearTimeout(tyQrPollTimer.current);
                    tyQrPollTimer.current = null;
                  }
                  setTyQrPolling(false);
                  setSelectedProtocol(null);
                }}
                className="text-gray-400 hover:text-white transition-colors p-1.5 hover:bg-white/5 rounded-lg"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-primary font-bold flex items-center gap-2 drop-shadow-[0_0_8px_var(--color-primary)] text-lg">
                <QrCode size={20} />
                {selectedProtocol.display_name}
              </span>
              <span className="ml-auto text-[10px] text-gray-500 font-['Rajdhani']">
                {tyQrSourceId === null ? '步骤 1 / 2 · 生成二维码' : '步骤 2 / 2 · 等待扫码'}
              </span>
            </div>

            {tyQrSourceId === null ? (
              <div className="space-y-5">
                <div>
                  <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase">
                    名称
                  </label>
                  <input
                    type="text"
                    value={tyQrName}
                    onChange={(e) => setTyQrName(e.target.value)}
                    placeholder={selectedProtocol.display_name || selectedProtocol.type}
                    className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-sm text-white focus:outline-none transition-all"
                  />
                </div>
                <div className="text-[11px] text-gray-500 font-['Rajdhani'] bg-white/[0.02] border border-white/5 rounded-lg p-3 leading-relaxed">
                  CyberStream 自动管理 OpenList，无需手动填写地址或账号。点击下方按钮生成 {selectedProtocol.display_name || selectedProtocol.type} 官方扫码登录二维码。
                </div>
                {selectedProtocol.type === 'aliyundrive' && (
                  <div className="text-[11px] text-amber-400/90 font-['Rajdhani'] bg-amber-400/5 border border-amber-400/20 rounded-lg p-3 leading-relaxed flex items-start gap-2">
                    <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                    <span>
                      阿里云盘需要拉取官方公共工具链（api.oplist.org），首次生成二维码可能需要 20-30 秒，请耐心等待。
                    </span>
                  </div>
                )}
                {selectedProtocol.type === '115cloud' && (
                  <div className="border border-white/5 rounded-lg overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setTyQrShowAdvanced((v) => !v)}
                      className="w-full flex items-center justify-between px-3 py-2 bg-black/30 hover:bg-white/5 transition-colors text-[11px] font-['Orbitron'] tracking-widest text-gray-400 uppercase"
                    >
                      <span>高级设置</span>
                      <ChevronRight
                        size={14}
                        className={`transition-transform ${tyQrShowAdvanced ? 'rotate-90' : ''}`}
                      />
                    </button>
                    {tyQrShowAdvanced && (
                      <div className="px-3 py-3 bg-black/20 space-y-2">
                        <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 uppercase">
                          扫码端类型
                        </label>
                        <select
                          value={tyQrCodeSource}
                          onChange={(e) => setTyQrCodeSource(e.target.value)}
                          className="w-full bg-black/40 border border-white/10 hover:border-white/20 focus:border-primary/50 rounded-lg p-2 text-sm text-white focus:outline-none transition-all font-mono"
                        >
                          <option value="">默认（微信小程序）</option>
                          <option value="wechatmini">微信小程序 wechatmini</option>
                          <option value="alipaymini">支付宝小程序 alipaymini</option>
                          <option value="web">网页 web</option>
                          <option value="android">安卓 android</option>
                          <option value="ios">iOS ios</option>
                          <option value="tv">电视 tv</option>
                          <option value="qandroid">QQ 安卓 qandroid</option>
                        </select>
                        <p className="text-[10px] text-gray-600 font-['Rajdhani'] leading-relaxed">
                          多数情况下保持默认即可。仅在常用扫码方式失败时切换其他端排障。
                        </p>
                      </div>
                    )}
                  </div>
                )}
                <button
                  onClick={handleStartTianyicloudQr}
                  disabled={tyQrBusy}
                  className="w-full py-2.5 rounded-lg bg-primary/20 border border-primary text-primary hover:bg-primary hover:text-black hover:shadow-[0_0_20px_var(--color-primary)] text-sm font-['Orbitron'] font-bold transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {tyQrBusy ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <QrCode size={16} />
                  )}
                  生成二维码
                </button>
              </div>
            ) : (
              <div className="space-y-5">
                <div className="flex flex-col items-center gap-3">
                  <div className="bg-white p-3 rounded-lg shadow-[0_0_30px_var(--color-primary)]">
                    {tyQrDataUrl ? (
                      <img
                        src={tyQrDataUrl}
                        alt={`${selectedProtocol.display_name || selectedProtocol.type} 登录二维码`}
                        className="w-56 h-56 block"
                      />
                    ) : (
                      <div className="w-56 h-56 flex items-center justify-center text-gray-400">
                        <Loader2 size={32} className="animate-spin" />
                      </div>
                    )}
                  </div>
                  <div className="text-xs text-primary/80 bg-primary/5 border border-primary/20 rounded-lg px-3 py-2 flex items-center gap-2">
                    {tyQrPolling ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Check size={14} />
                    )}
                    {tyQrPendingMsg || `请用 ${selectedProtocol.display_name || selectedProtocol.type} App 扫码登录`}
                  </div>
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      if (tyQrPollTimer.current !== null) {
                        window.clearTimeout(tyQrPollTimer.current);
                        tyQrPollTimer.current = null;
                      }
                      setTyQrSourceId(null);
                      setTyQrDataUrl('');
                      setTyQrPolling(false);
                      setTyQrPendingMsg('');
                    }}
                    className="px-4 py-2.5 rounded-lg bg-[#0a0a12] border border-white/10 text-gray-400 hover:bg-white/5 hover:text-white transition-all text-xs font-['Orbitron']"
                  >
                    重新生成
                  </button>
                  <button
                    onClick={() => {
                      if (tyQrSourceId !== null) pollTianyicloudQrLoop(tyQrSourceId);
                    }}
                    className="flex-1 py-2.5 rounded-lg bg-primary/20 border border-primary text-primary hover:bg-primary hover:text-black hover:shadow-[0_0_20px_var(--color-primary)] text-sm font-['Orbitron'] font-bold transition-all flex items-center justify-center gap-2"
                  >
                    <RefreshCw size={16} />
                    立即检查状态
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : isManagedOauthProvider ? (
          // ─── 托管 OAuth 登录（百度网盘） ───
          // 用户不接触 OpenList 内部参数。点「开始授权」拿到 authorization_url，
          // 自动打开浏览器跳转，旁边轮询状态；授权确认后自动关弹窗。
          <div className="flex flex-col flex-1 overflow-y-auto custom-scrollbar pr-2 pb-2 max-w-2xl mx-auto w-full animate-in fade-in slide-in-from-right-4 duration-300">
            <div className="flex items-center gap-3 font-['Orbitron'] border-b border-white/10 pb-4 mb-6">
              <button
                onClick={() => {
                  if (oauthPollTimer.current !== null) {
                    window.clearTimeout(oauthPollTimer.current);
                    oauthPollTimer.current = null;
                  }
                  setOauthPolling(false);
                  setSelectedProtocol(null);
                }}
                className="text-gray-400 hover:text-white transition-colors p-1.5 hover:bg-white/5 rounded-lg"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-primary font-bold flex items-center gap-2 drop-shadow-[0_0_8px_var(--color-primary)] text-lg">
                <KeyRound size={20} />
                {selectedProtocol.display_name}
              </span>
              <span className="ml-auto text-[10px] text-gray-500 font-['Rajdhani']">
                {oauthSourceId === null ? '步骤 1 / 2 · 启动授权' : '步骤 2 / 2 · 等待授权'}
              </span>
            </div>

            {oauthSourceId === null ? (
              <div className="space-y-5">
                <div>
                  <label className="block text-[10px] font-['Orbitron'] tracking-widest text-gray-500 mb-1.5 uppercase">
                    名称
                  </label>
                  <input
                    type="text"
                    value={oauthName}
                    onChange={(e) => setOauthName(e.target.value)}
                    placeholder={selectedProtocol.display_name || selectedProtocol.type}
                    className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 text-sm text-white focus:outline-none transition-all"
                  />
                </div>
                <div className="text-[11px] text-gray-500 font-['Rajdhani'] bg-white/[0.02] border border-white/5 rounded-lg p-3 leading-relaxed">
                  CyberStream 自动管理 OpenList，无需手动填写地址或账号。点击下方按钮跳转到 {selectedProtocol.display_name || selectedProtocol.type} 官方授权页面完成登录。
                </div>
                <button
                  onClick={handleStartBaiduOauth}
                  disabled={oauthBusy}
                  className="w-full py-2.5 rounded-lg bg-primary/20 border border-primary text-primary hover:bg-primary hover:text-black hover:shadow-[0_0_20px_var(--color-primary)] text-sm font-['Orbitron'] font-bold transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {oauthBusy ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <ExternalLink size={16} />
                  )}
                  开始授权
                </button>
              </div>
            ) : (
              <div className="space-y-5">
                <div className="flex flex-col items-center gap-4 py-4">
                  <div className="w-20 h-20 rounded-full bg-primary/10 border border-primary/30 flex items-center justify-center shadow-[0_0_30px_var(--color-primary)]">
                    {oauthPolling ? (
                      <Loader2 size={32} className="animate-spin text-primary" />
                    ) : (
                      <KeyRound size={32} className="text-primary" />
                    )}
                  </div>
                  <div className="text-xs text-primary/80 bg-primary/5 border border-primary/20 rounded-lg px-3 py-2 flex items-center gap-2 max-w-md text-center">
                    {oauthPolling ? (
                      <Loader2 size={14} className="animate-spin shrink-0" />
                    ) : (
                      <Check size={14} className="shrink-0" />
                    )}
                    {oauthPendingMsg || `请在浏览器中完成 ${selectedProtocol.display_name || selectedProtocol.type} 授权`}
                  </div>
                  {oauthAuthUrl && (
                    <button
                      onClick={() => shellOpen(oauthAuthUrl).catch(() => toast.error('未能打开浏览器'))}
                      className="text-[11px] text-primary/70 hover:text-primary underline font-['Rajdhani'] flex items-center gap-1.5 transition-colors"
                    >
                      <ExternalLink size={12} />
                      手动重新打开授权页面
                    </button>
                  )}
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      if (oauthPollTimer.current !== null) {
                        window.clearTimeout(oauthPollTimer.current);
                        oauthPollTimer.current = null;
                      }
                      setOauthSourceId(null);
                      setOauthAuthUrl('');
                      setOauthPolling(false);
                      setOauthPendingMsg('');
                    }}
                    className="px-4 py-2.5 rounded-lg bg-[#0a0a12] border border-white/10 text-gray-400 hover:bg-white/5 hover:text-white transition-all text-xs font-['Orbitron']"
                  >
                    重新授权
                  </button>
                  <button
                    onClick={() => {
                      if (oauthSourceId !== null) pollBaiduOauthLoop(oauthSourceId);
                    }}
                    className="flex-1 py-2.5 rounded-lg bg-primary/20 border border-primary text-primary hover:bg-primary hover:text-black hover:shadow-[0_0_20px_var(--color-primary)] text-sm font-['Orbitron'] font-bold transition-all flex items-center justify-center gap-2"
                  >
                    <RefreshCw size={16} />
                    立即检查状态
                  </button>
                </div>
              </div>
            )}
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
                      ) : field.type === "string" && field.name.includes("password") ? (
                        <div className="relative">
                          <input
                            type={revealedFields[field.name] ? "text" : "password"}
                            placeholder={field.description || `Input ${field.name}`}
                            value={newSourceConfig[field.name] || ""}
                            onChange={(e) =>
                              setNewSourceConfig({
                                ...newSourceConfig,
                                [field.name]: e.target.value,
                              })
                            }
                            className="w-full bg-black/40 border border-white/5 hover:border-white/20 focus:border-primary/50 focus:bg-black/60 rounded-lg p-2.5 pr-10 text-sm text-white focus:outline-none focus:shadow-[0_0_15px_rgba(var(--color-primary-rgb),0.1)] transition-all font-mono [&::-ms-reveal]:hidden [&::-webkit-credentials-auto-fill-button]:hidden"
                          />
                          <button
                            type="button"
                            onClick={() =>
                              setRevealedFields((prev) => ({
                                ...prev,
                                [field.name]: !prev[field.name],
                              }))
                            }
                            className="absolute inset-y-0 right-0 px-3 flex items-center text-primary-70 hover:text-primary transition-colors"
                            aria-label={revealedFields[field.name] ? "隐藏密码" : "显示密码"}
                          >
                            {revealedFields[field.name] ? <EyeOff size={16} /> : <Eye size={16} />}
                          </button>
                        </div>
                      ) : (
                        <input
                          type={
                            field.type === "number"
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
