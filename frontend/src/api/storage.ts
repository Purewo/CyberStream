import { getApiBase } from '../platform';
import { fetchApi, fetchApiRaw, mapApiMovieToUi, mapSeasonCardToUi, getDeviceId, ApiPagination, ApiMovieSimple, ApiMovieDetailed, ApiResponse } from './core';
import { Movie, Episode, HistoryItem, Notification, Resource, Genre, TechSpecs, FilterDictionaries } from '../types/index';

export const storageService = {
  getCapabilities: async (): Promise<any | null> => {
    return await fetchApi<any>('/v1/storage/capabilities');
  },

  getProviderTypes: async (): Promise<any[]> => {
    // Falls back to empty array if not found
    const data = await fetchApi<any>('/v1/storage/provider-types');
    return data || [];
  },

  getSources: async (): Promise<import('../types/index').StorageSource[]> => {
    const data = await fetchApi<import('../types/index').StorageSource[]>('/v1/storage/sources');
    return data || [];
  },

  getSource: async (id: number): Promise<import('../types/index').StorageSource | null> => {
    return await fetchApi<import('../types/index').StorageSource>(`/v1/storage/sources/${id}`);
  },

  getSourceBrowse: async (id: number, browsePath: string = '/'): Promise<{ items: import('../types/index').FileItem[] | null, error?: string }> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/storage/sources/${id}/browse?path=${encodeURIComponent(browsePath)}&dirs_only=true`);
      const data = await res.json().catch(() => null);
      if (res.ok && data?.code === 200) {
        return { items: data.data?.items || [] };
      }
      return { items: null, error: data?.msg || `HTTP Error ${res.status}` };
    } catch (e: any) {
      return { items: null, error: e.message };
    }
  },

  // 刷新已保存存储源的目录缓存（AList/OpenList/光鸭走 alist 内核都吃这个）。
  // 底层调上游 fs/list?refresh=true，不触发扫描和刮削。云盘新增文件但 alist
  // 还没同步时调一次能立刻拿到最新列表。path 为空 = 刷新根目录。
  refreshSourcePath: async (id: number, path?: string, dirsOnly: boolean = false): Promise<{ ok: boolean; msg?: string; items?: import('../types/index').FileItem[] }> => {
    const body: any = { dirs_only: dirsOnly };
    if (path && path !== '/') body.path = path;
    const res = await fetchApiRaw<any>(`/v1/storage/sources/${id}/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) return { ok: true, items: res.data?.items || [] };
    return { ok: false, msg: res.msg || `HTTP ${res.status}` };
  },

  checkHealth: async (id: number): Promise<import('../types/index').StorageSourceHealth | null> => {
    const data = await fetchApi<import('../types/index').StorageSource>(`/v1/storage/sources/${id}/health`);
    return data?.health || null;
  },

  addSource: async (name: string, type: string, config: any): Promise<boolean> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/storage/sources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, type, config })
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  updateSource: async (id: number, name: string, type: string, config: any): Promise<boolean> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/storage/sources/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, type, config })
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  // 删除存储源。
  // - keepMetadata=true 是旧的「软断连」语义，资源记录留下变离线
  // - keepMetadata=false 是「连根清空」，会级联删 media_resources / 库绑定 / 历史 / 字幕等
  //   后端要求带保险柜 PIN（body.pin），前端拿到 40341/40344 自行决定怎么引导
  // - 托管网盘会先删 AList/OpenList 内部挂载；若运行时删除失败，后端返回 50262 且保留本地数据
  // 返回 { ok, code, msg }，调用方按业务码做分支。
  deleteSource: async (
    id: number,
    options: { keepMetadata?: boolean; pin?: string } = {},
  ): Promise<{ ok: boolean; code?: number; msg?: string }> => {
    const keepMetadata = options.keepMetadata === true;
    const body: Record<string, unknown> = {};
    if (options.pin) body.pin = options.pin;
    const res = await fetchApiRaw<unknown>(
      `/v1/storage/sources/${id}?keep_metadata=${keepMetadata}`,
      {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    );
    if (res.ok) return { ok: true, code: res.code };
    return { ok: false, code: res.code, msg: res.msg };
  },

  previewStorage: async (type: string, config: any, targetPath: string = '/'): Promise<{ items: import('../types/index').FileItem[] | null, error?: string }> => {
    try {
      const res = await fetch(`${getApiBase()}/v1/storage/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, config, target_path: targetPath })
      });
      const data = await res.json().catch(() => null);
      
      if (res.ok && data?.code === 200) {
         return { items: data.data?.items || [] };
      }
      
      return { 
        items: null, 
        error: data?.msg || `HTTP Error ${res.status}` 
      };
    } catch (e: any) {
      return { items: null, error: e.message };
    }
  },

  scanSource: async (id: number, options?: { target_path?: string, scrape_enabled?: boolean, scraper_policy?: any, provider_order?: string[] }): Promise<{ ok: boolean; msg?: string }> => {
    // 用 fetchApiRaw 把后端 msg 透出来：未传 target_path 且这个存储源没被
    // 任何媒体库绑定时，后端返 40013，UI 直接用这条提示，比之前笼统的
    // 「触发扫描失败」对用户友好得多。202 也算 ok。
    const res = await fetchApiRaw<unknown>(`/v1/storage/sources/${id}/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options || {}),
    });
    if (res.ok || res.status === 202) return { ok: true };
    return { ok: false, msg: res.msg || `HTTP ${res.status}` };
  },

  // ─── 托管光鸭云盘 (GuangYaPan) ───
  //
  // 与普通 alist/webdav/local 不同——光鸭走 SMS 登录两步流程：
  //   1. start: 发短信验证码，后端创建 source（auth_state=sms_pending）
  //   2. verify: 提交 6 位验证码，source 翻成 ready，actions 全开
  // 用户不接触 AList 内部参数；前端只保存 source.id 跟 auth_state。
  // 完整契约：GET /v1/docs/frontend-managed-guangyapan
  startGuangyapanSms: async (params: {
    phone_number: string;
    name?: string;
    root_path?: string;
    captcha_token?: string;
  }): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/guangyapan/sms/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  verifyGuangyapanSms: async (sourceId: number, verifyCode: string): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/guangyapan/sms/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId, verify_code: verifyCode }),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // ─── 托管天翼云盘 (TianYiCloud) ───
  //
  // 跟光鸭一样属于托管型挂载，但走二维码登录：
  //   1. start: 后端创建 source（auth_state=qr_pending），返回 base64 二维码图片
  //   2. poll:  前端每 2-3s 调一次，直到 authenticated=true / auth_state=ready
  // 用户用天翼云盘 App 扫码确认后，后端拿到 OpenList 侧 token，挂载完成。
  // 完整契约：GET /v1/docs/frontend-managed-tianyicloud
  startTianyicloudQr: async (params: {
    name?: string;
  }): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/tianyicloud/qr/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  pollTianyicloudQr: async (sourceId: number): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/tianyicloud/qr/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId }),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // ─── 通用托管二维码登录 (TianYiCloud / QuarkTV / UCTV) ───
  //
  // 这三家走同一份合同：
  //   POST /v1/storage/managed/{slug}/qr/start  body { name?, ...protocol_extras }
  //   POST /v1/storage/managed/{slug}/qr/poll   body { source_id }
  // 完整契约：GET /v1/docs/frontend-managed-tianyicloud / frontend-managed-quark-uc
  startManagedQrLogin: async (
    slug: string,
    params: {
      name?: string;
      root_folder_id?: string;
      // 115cloud 专属：扫码端类型。后端默认 wechatmini，前端只在用户明确选择
      // 「高级设置 / 切换扫码端」时才需要传值。其他 provider 不识别此字段。
      qrcode_source?: 'web' | 'android' | 'ios' | 'tv' | 'alipaymini' | 'wechatmini' | 'qandroid';
    },
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>(`/v1/storage/managed/${slug}/qr/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  pollManagedQrLogin: async (
    slug: string,
    sourceId: number,
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>(`/v1/storage/managed/${slug}/qr/poll`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId }),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // ─── 重新扫码登录（QuarkTV / UCTV） ───
  //
  // 夸克 TV 同账号在其他设备登录会顶号，老 token 失效。这条接口在原 source_id
  // 上发起新一轮二维码登录，不新建 source、不破坏资源索引与媒体库绑定。完成
  // 后照旧 poll 同一个 source_id 直到 authenticated=true。
  // rootFolderId 可选：不传则沿用 source 当前配置。
  restartManagedQrLogin: async (
    slug: string,
    sourceId: number,
    rootFolderId?: string,
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const body: Record<string, unknown> = { source_id: sourceId };
    if (rootFolderId) body.root_folder_id = rootFolderId;
    const res = await fetchApiRaw<any>(`/v1/storage/managed/${slug}/qr/restart`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // ─── 天翼云盘 PC 扫码登录（实验性） ───
  //
  // 正式天翼托管登录用 OpenList 189CloudTV，但部分老账号在 TV 扫码链路里反复
  // 返回二维码无法挂载；改走 189CloudPC 的 login_type=qrcode 可能正常。
  // ⚠️ 实验接口：不在 storage/capabilities 暴露、不是稳定合同，仅供老账号 TV
  // 扫码失败时的兜底尝试。流程同 qr：pcQrStart → 轮询 pcQrPoll 直到 ready。
  // 完整契约：GET /v1/docs/experimental-tianyicloud-pc-qr
  pcQrStartTianyicloud: async (
    params: { name?: string; cloud_type?: 'personal' | 'family'; root_folder_id?: string },
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/tianyicloud/pc-qr/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  pcQrPollTianyicloud: async (
    sourceId: number,
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/tianyicloud/pc-qr/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId }),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // 为已有天翼来源重新生成 PC 扫码二维码（二维码过期，或把 TV 扫码来源临时
  // 切到 PC 扫码实验链路）。成功会额外返回 replaced_openlist_storage_id /
  // old_openlist_storage_deleted。
  pcQrRestartTianyicloud: async (
    sourceId: number,
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/tianyicloud/pc-qr/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId }),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // ─── 通用托管 OAuth 登录 (BaiduNetdisk) ───
  //
  // 跟 QR 是兄弟接口，但走 OAuth 跳转：
  //   POST /v1/storage/managed/{slug}/oauth/start  body { name?, ...protocol_extras }
  //     → 返回 authorization_url，前端用浏览器打开（Web 端 window.open / PC 端 shellOpen）
  //   POST /v1/storage/managed/{slug}/oauth/poll   body { source_id }
  //     → 状态机：oauth_pending (waiting_for_authorization) → ready | oauth_failed
  // 百度回调走后端 /oauth/callback，前端只 poll；不解析回调 URL。
  // 完整契约：GET /v1/docs/frontend-managed-baidunetdisk
  startManagedOauthLogin: async (
    slug: string,
    params: {
      name?: string;
      root_folder_path?: string;
      // 百度网盘下载接口：official | crack | crack_video。普通用户不暴露，留空走后端默认。
      download_api?: 'official' | 'crack' | 'crack_video';
    },
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>(`/v1/storage/managed/${slug}/oauth/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  pollManagedOauthLogin: async (
    slug: string,
    sourceId: number,
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>(`/v1/storage/managed/${slug}/oauth/poll`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId }),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // ─── 托管 OAuth：oob 模式提交授权码 ───
  //
  // 当 oauth/start 返回 callback_mode=oob 时，百度不会回调到我们域名（公共
  // OAuth 应用 redirect_uri 不匹配），而是把授权码展示给用户。前端让用户
  // 把这串码粘贴回来，调这个接口换 token。成功后 source 直接 ready，
  // 不需要再 poll。
  completeManagedOauthLogin: async (
    slug: string,
    sourceId: number,
    authorizationCode: string,
  ): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>(`/v1/storage/managed/${slug}/oauth/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId, authorization_code: authorizationCode }),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },

  // ─── 托管账号密码登录 (123Pan) ───
  //
  // 跟 QR / OAuth 兄弟，但 123 盘只有一步——直接 POST username + password，
  // 后端登录成功就把 source 拉到 ready，没有 pending / poll / qr_code 之类。
  // 完整契约：GET /v1/docs/frontend-managed-123pan
  loginManaged123Pan: async (params: {
    name?: string;
    username: string;
    password: string;
    root_folder_id?: string;
    platform?: string;
  }): Promise<{ ok: boolean; msg?: string; data?: any }> => {
    const res = await fetchApiRaw<any>('/v1/storage/managed/123pan/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (res.ok) return { ok: true, data: res.data };
    return { ok: false, msg: res.msg || `HTTP ${res.status}`, data: res.data };
  },
};

