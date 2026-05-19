import React, { useMemo } from 'react';
import { Cpu, Globe, Calendar } from 'lucide-react';
import { FilterTag } from '../ui/CyberComponents';

// Mapping for API region names to Chinese
const REGION_NAME_MAP: Record<string, string> = {
  "United States of America": "美国",
  "United States": "美国",
  "United Kingdom": "英国",
  "China": "中国",
  "Japan": "日本",
  "South Korea": "韩国",
  "Korea": "韩国",
  "France": "法国",
  "Germany": "德国",
  "Canada": "加拿大",
  "Australia": "澳大利亚",
  "India": "印度",
  "Russia": "俄罗斯",
  "Thailand": "泰国",
  "Hong Kong": "中国香港",
  "Taiwan": "中国台湾",
  "Italy": "意大利",
  "Spain": "西班牙",
  "Brazil": "巴西",
  "Sweden": "瑞典",
  "Unknown": "未知",
  "Other": "其他"
};

// Mapping for API genre names to Chinese or UI display names
const GENRE_DISPLAY_MAP: Record<string, string> = {
  "Local": "本地"
};

interface FilterPanelProps {
  rawGenres: string[];
  rawRegions: string[];
  rawYears: string[];
  activeFilters: {
    type: string;
    region: string;
    year: string;
  };
  onFilterChange: (key: 'type' | 'region' | 'year', value: string) => void;
}

export const FilterPanel: React.FC<FilterPanelProps> = ({ 
  rawGenres, 
  rawRegions, 
  rawYears, 
  activeFilters, 
  onFilterChange 
}) => {

  // Logic 1: Process Genres (Filter unwanted, Rename/Move Local)
  const processedGenres = useMemo(() => {
    let genres = [...rawGenres];
    
    // Filter out unwanted genres locally
    const unwantedGenres = ["电视电影", "音乐", "Sci-Fi & Fantasy", "动作冒险"];
    genres = genres.filter(g => !unwantedGenres.includes(g));

    // Move "Local" to the end
    const localIndex = genres.indexOf("Local");
    if (localIndex !== -1) {
      genres.splice(localIndex, 1);
      genres.push("Local");
    }
    
    return ["全部类型", ...genres];
  }, [rawGenres]);

  // Logic 2: Process Regions (Move Unknown to end)
  const processedRegions = useMemo(() => {
    let regions = [...rawRegions];
    
    const unknownIndex = regions.indexOf("Unknown");
    if (unknownIndex !== -1) {
        regions.splice(unknownIndex, 1);
        regions.push("Unknown");
    }
    
    return ["全部地区", ...regions];
  }, [rawRegions]);

  // Logic 3: Process Years (Filter unreasonable, limit length)
  const processedYears = useMemo(() => {
    const currentYear = new Date().getFullYear();
    // Convert strings to numbers for comparison if needed, assuming API sends strings or numbers
    // Here we map to number first to be safe
    let years = rawYears.map(y => parseInt(String(y))).filter(n => !isNaN(n));

    // Filter unreasonable years
    years = years.filter(y => y >= 1880 && y <= currentYear + 1);

    // Sort descending
    years.sort((a, b) => b - a);

    // Limit display length
    const MAX_YEARS_DISPLAY = 25;
    const limitedYears = years.slice(0, MAX_YEARS_DISPLAY);

    return ["全部年份", ...limitedYears.map(String), "更早"];
  }, [rawYears]);

  return (
    <div className="bg-[#0a0a12]/80 border border-white/10 backdrop-blur-md p-6 mb-10 relative overflow-hidden group tech-border">
      <div className="absolute top-0 right-0 w-16 h-16 border-t-2 border-r-2 border-red-500/50"></div>
      <div className="space-y-4 relative z-10">
        {/* Genre Filter */}
        <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-4">
          <span className="text-primary font-['Noto_Sans_SC'] font-bold py-1 min-w-[4rem] flex items-center gap-2">
            <Cpu size={14} /> 类型
          </span>
          <div className="flex flex-wrap gap-2">
            {processedGenres.map(type => (
              <FilterTag 
                key={type} 
                label={GENRE_DISPLAY_MAP[type] || type} 
                active={activeFilters.type === type} 
                onClick={() => onFilterChange('type', type)} 
              />
            ))}
          </div>
        </div>
        <div className="h-[1px] bg-white/5 w-full"></div>
        
        {/* Region Filter */}
        <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-4">
          <span className="text-secondary font-['Noto_Sans_SC'] font-bold py-1 min-w-[4rem] flex items-center gap-2">
            <Globe size={14} /> 地区
          </span>
          <div className="flex flex-wrap gap-2">
            {processedRegions.map(region => (
              <FilterTag 
                key={region} 
                label={REGION_NAME_MAP[region] || region} 
                active={activeFilters.region === region} 
                onClick={() => onFilterChange('region', region)} 
              />
            ))}
          </div>
        </div>
        <div className="h-[1px] bg-white/5 w-full"></div>
        
        {/* Year Filter */}
        <div className="flex flex-col md:flex-row md:items-center gap-2 md:gap-4">
          <span className="text-accent font-['Noto_Sans_SC'] font-bold py-1 min-w-[4rem] flex items-center gap-2">
            <Calendar size={14} /> 年份
          </span>
          <div className="flex flex-wrap gap-2">
            {processedYears.map(year => (
              <FilterTag 
                key={year} 
                label={year} 
                active={activeFilters.year === year} 
                onClick={() => onFilterChange('year', year)} 
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};