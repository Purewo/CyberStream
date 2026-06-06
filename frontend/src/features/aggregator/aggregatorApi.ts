// 聚合搜索 API 层。
//
// 走后端统一 blueprint（/api/v1/aggregator/*，见 backend/app/api/aggregator_routes.py），
// 不再依赖独立的本地桥（旧 pc/aggregator/bridge.py 端口 10700 已废弃）。前端走
// 统一 API_BASE，web 端和 PC 端都可用。
//
// 设计约束（与抓取层反爬规则一致）：
//   - 一次只打一个 source，绝不并发遍历所有源。
//   - 默认源 rarbt；其他源由用户手动切。

import { fetchApi } from '../../api/core';

export interface AggSearchItem {
  title: string;
  link: string;
  category?: string;
  country?: string;
  years?: string;
  overview?: string;
}

export interface AggCloudLink {
  provider?: string;
  url: string;
  name?: string;
  password?: string;
  description?: string;
}

export interface AggFileItem {
  file_name: string;
  file_size?: string;
  final_link: string;
  file_tag?: string;
}

export interface AggFileGroup {
  quality: string;
  number?: string;
  file_list: AggFileItem[];
}

export interface AggDetail {
  director?: string;
  actors?: string | string[];
  description?: string | string[];
  years?: string[];
  poster?: string;
  douban_score?: string;
  imdb_score?: string;
  source?: string;
  file_content?: AggFileGroup[];
  cloud_links?: AggCloudLink[];
  [k: string]: unknown;
}

export interface AggMagnet {
  file_name?: string;
  image?: string;
  magnet?: string;
}

export interface AggSource {
  name: string;
  /** 展示用中文名 */
  label: string;
  /** 是否为默认自动触发源 */
  isDefault?: boolean;
}

// 源的展示名 + 排序。只列当前实测可用/有意义的，挂掉的(bt7274/yinfans)不展示。
// 顺序即 UI tab 顺序；rarbt 默认（自动触发只打它，资源量最大、magnet 直出）。
export const AGG_SOURCES: AggSource[] = [
  { name: 'rarbt', label: 'RARBT·磁力', isDefault: true },
  { name: '4kzhinan', label: '4K指南·网盘' },
  { name: 'hdzu', label: 'HDZU·磁力' },
  { name: 'renrenys', label: '人人·网盘' },
  { name: 'btbtla', label: 'BTBTLA·磁力(代理)' },
];

export const DEFAULT_AGG_SOURCE = 'rarbt';

// fetchApi 出错（网络失败 / 非 200 信封）时返回 null。聚合搜索组件靠
// try/catch 驱动 error 态，所以这里把 null 转成 throw 保留原行为。
async function aggGet<T>(path: string, params: Record<string, string>): Promise<T> {
  const qs = new URLSearchParams(params).toString();
  const data = await fetchApi<T>(`/v1/aggregator${path}?${qs}`);
  if (data == null) throw new Error('请求失败');
  return data;
}

export const aggregatorApi = {
  // 整合进后端后不再有"本地桥"概念，恒可用（错误按源在调用处 catch）。
  isAvailable: async (): Promise<boolean> => true,

  search: async (keyword: string, source = DEFAULT_AGG_SOURCE, page = 1): Promise<AggSearchItem[]> => {
    const data = await aggGet<{ items: AggSearchItem[] }>('/search', {
      keyword, source, page: String(page),
    });
    return data.items || [];
  },

  detail: async (link: string, source = DEFAULT_AGG_SOURCE): Promise<AggDetail | null> => {
    const data = await aggGet<{ detail: AggDetail | null }>('/detail', { link, source });
    return data.detail;
  },

  magnet: async (link: string, source = DEFAULT_AGG_SOURCE): Promise<AggMagnet | null> => {
    const data = await aggGet<{ magnet: AggMagnet | null }>('/magnet', { link, source });
    return data.magnet;
  },
};
