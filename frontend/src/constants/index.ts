import { ThemeConfig } from './types';

export const API_BASE = "https://pw.pioneer.fan:84/api";

export const THEMES: Record<string, ThemeConfig> = { 
  CYBER: { primary: '#00f3ff', secondary: '#bc13fe', bg: '#050505', text: '#ffffff', accent: '#f2ff00' }, 
  ARASAKA: { primary: '#ff003c', secondary: '#ffffff', bg: '#0a0000', text: '#ffcccc', accent: '#ff5555' }, 
  GOLDEN: { primary: '#ffd700', secondary: '#00ff9d', bg: '#050805', text: '#ffffee', accent: '#ffaa00' } 
};

export const FEATURED_MOVIE = { 
  id: 'featured-01', title: 'NEON GENESIS', rating: '9.8', year: 2077, duration: '142 MIN', tags: ['4K', 'HDR', 'DOLBY ATMOS'], 
  desc: '在被巨型企业控制的反乌托邦未来，一名网络黑客发现了一个能够重写人类意识的古老代码。他必须在现实与虚拟的边缘做出抉择。这是一个关于觉醒、反抗与赛博格灵魂的故事。', 
  cast: ['ALEX', 'SARAH', 'CYPHER'], director: 'THE ARCHITECT', source_path: '' 
};

export const FILTERS = { 
  types: ["全部类型", "科幻", "动作", "冒险", "剧情", "动画", "悬疑", "惊悚", "犯罪", "战争", "奇幻"], 
  regions: ["全部地区", "美国", "日本", "中国", "英国", "韩国", "其他"], 
  years: ["全部年份", "2025", "2024", "2023", "2022", "2021", "2020", "更早"], 
  sorts: [{ id: 'update_time', label: '更新时间' }, { id: 'rating', label: '综合评分' }, { id: 'year', label: '上映年份' }] 
};

export const generateMockData = (page: number, limit: number, type: string, region: string) => { 
  const mockTypes = ["科幻", "动作", "悬疑", "剧情", "动画", "惊悚"]; 
  const mockRegions = ["美国", "日本", "中国", "英国"]; 
  const totalItems = 86; 
  const start = (page - 1) * limit; 
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const items = Array.from({ length: limit }, (_, i) => { 
    const id = start + i + 1; 
    if (id > totalItems) return null; 
    const currentType = type !== "全部" ? type : mockTypes[id % mockTypes.length]; 
    const currentRegion = region !== "全部" ? region : mockRegions[id % mockRegions.length]; 
    return { 
      id: `mock-${id}`, title: `${currentRegion === '中国' ? '流浪地球' : 'NEON GENESIS'} PROTOCOL ${id}`, rating: (7 + Math.random() * 2.5).toFixed(1), year: 2020 + (id % 6), duration: `${90 + (id % 40)} MIN`, type: currentType, region: currentRegion, tags: [currentType, currentRegion, '4K'], cover_url: "", tech_specs: { resolution: id % 3 === 0 ? '4K' : '1080P', codec: id % 2 === 0 ? 'HEVC' : 'AVC' } 
    }; 
  }).filter(Boolean); 
  return { items, meta: { page, limit, total: totalItems, pages: Math.ceil(totalItems / limit) } }; 
};