import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';

export const FilterTag: React.FC<{ label: string; active: boolean; onClick: () => void }> = ({ label, active, onClick }) => (
  <button onClick={onClick} className={`px-3 py-1 text-xs md:text-sm font-['Noto_Sans_SC'] transition-all duration-200 skew-x-[-10deg] border border-transparent ${active ? 'bg-primary text-black font-bold border-primary shadow-[0_0_10px_var(--color-primary)]' : 'text-gray-400 hover:text-primary hover:border-primary/30 hover:bg-primary/5'}`} >
    <div className="skew-x-[10deg]">{label}</div>
  </button>
);

interface FilterTagsRowProps {
  items: string[];
  active: string;
  onSelect: (value: string) => void;
  labelOf?: (value: string) => string;
  // 'more' = 截断时尾部显示「更多」按钮，点开把剩余项展示出来（再点收起）；
  // 'value' = 始终保留 items 末尾的字面量项作为筛选选项（如年份的「更早」）。
  truncationMode: 'more' | 'value';
}

// 单行筛选标签：JS 测量真实宽度做单行截断；超出容器宽度时按 truncationMode 决定尾部按钮。
export const FilterTagsRow: React.FC<FilterTagsRowProps> = ({ items, active, onSelect, labelOf, truncationMode }) => {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const ghostRef = useRef<HTMLDivElement | null>(null);
  const [visibleCount, setVisibleCount] = useState<number>(items.length);
  const [expanded, setExpanded] = useState(false);

  // value 模式：尾部那个字面量项（如「更早」）始终保留在最后，参与折叠计算
  const tailValue = truncationMode === 'value' && items.length > 0 ? items[items.length - 1] : null;
  const headItems = tailValue !== null ? items.slice(0, -1) : items;

  const recompute = () => {
    const container = containerRef.current;
    const ghost = ghostRef.current;
    if (!container || !ghost) return;
    const containerWidth = container.clientWidth;
    const buttons = Array.from(ghost.querySelectorAll<HTMLElement>('[data-tag]')) as HTMLElement[];
    const gap = 8; // 与 gap-2 一致
    // tailButton 是必须保留的尾部按钮宽度（更多 / 更早），不存在则 0
    const tailButton = ghost.querySelector<HTMLElement>('[data-tail]');
    const tailWidth = tailButton ? tailButton.offsetWidth + gap : 0;

    let used = 0;
    let count = 0;
    for (let i = 0; i < buttons.length; i++) {
      const w = buttons[i].offsetWidth;
      const next = used + (count === 0 ? w : gap + w);
      // 还要为 tail 按钮预留位置（仅当后面还有项被截掉时才需要 tail）
      const remaining = buttons.length - (i + 1);
      const need = next + (remaining > 0 ? tailWidth : 0);
      if (need <= containerWidth) {
        used = next;
        count = i + 1;
      } else {
        break;
      }
    }
    // 没有任何项装得下时，至少展示第一个，避免空行
    if (count === 0 && buttons.length > 0) count = 1;
    setVisibleCount(count);
  };

  useLayoutEffect(recompute);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => recompute());
    ro.observe(container);
    return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const truncated = visibleCount < headItems.length;
  const display = labelOf || ((v: string) => v);

  // 展开模式：直接 wrap 显示全部，加一个收起按钮
  if (expanded && truncationMode === 'more') {
    return (
      <div className="flex flex-wrap gap-2 flex-1 min-w-0">
        {headItems.map(v => (
          <FilterTag key={v} label={display(v)} active={active === v} onClick={() => onSelect(v)} />
        ))}
        <button
          onClick={() => setExpanded(false)}
          className="px-3 py-1 text-xs md:text-sm font-['Noto_Sans_SC'] transition-all duration-200 skew-x-[-10deg] border border-transparent text-gray-500 hover:text-primary hover:border-primary/30 hover:bg-primary/5"
        >
          <div className="skew-x-[10deg]">收起</div>
        </button>
      </div>
    );
  }

  const visibleItems = headItems.slice(0, visibleCount);

  return (
    <div ref={containerRef} className="relative flex-1 min-w-0">
      {/* Ghost 行用于测量真实按钮宽度，对用户不可见也不参与布局占位 */}
      <div
        ref={ghostRef}
        className="absolute left-0 top-0 invisible pointer-events-none flex gap-2 whitespace-nowrap"
        aria-hidden="true"
      >
        {headItems.map(v => (
          <span data-tag key={v}>
            <FilterTag label={display(v)} active={false} onClick={() => undefined} />
          </span>
        ))}
        {truncationMode === 'more' && (
          <span data-tail>
            <FilterTag label="更多" active={false} onClick={() => undefined} />
          </span>
        )}
        {tailValue !== null && (
          <span data-tail>
            <FilterTag label={display(tailValue)} active={false} onClick={() => undefined} />
          </span>
        )}
      </div>

      <div className="flex gap-2 whitespace-nowrap overflow-hidden">
        {visibleItems.map(v => (
          <FilterTag key={v} label={display(v)} active={active === v} onClick={() => onSelect(v)} />
        ))}
        {truncationMode === 'more' && truncated && (
          <FilterTag label="更多" active={false} onClick={() => setExpanded(true)} />
        )}
        {tailValue !== null && (
          <FilterTag
            label={display(tailValue)}
            active={active === tailValue}
            onClick={() => onSelect(tailValue)}
          />
        )}
      </div>
    </div>
  );
};

export const TechBadge: React.FC<{ children?: React.ReactNode; className?: string }> = ({ children, className = "" }) => (
  <div className={`flex items-center gap-2 px-2 py-1 bg-black/60 border border-white/10 text-[10px] font-['Orbitron'] tracking-wider ${className}`}> 
    {children} 
  </div>
);

export const SciFiProgressRing = ({ progress, size = 80, isDragging = false }: { progress: number; size?: number, isDragging?: boolean }) => {
  const segments = 24; 
  const radius = 24;
  const circumference = 2 * Math.PI * radius;
  const isFull = Math.round(progress) === 100;
  return (
    <div className="relative flex items-center justify-center group" style={{ width: size, height: size }}>
       <svg width={size} height={size} viewBox="0 0 64 64" className="transform -rotate-90">
          <circle cx="32" cy="32" r="16" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="1" />
          {[...Array(segments)].map((_, i) => {
             const threshold = (i + 1) * (100 / segments);
             const isActive = (progress >= threshold) || isFull || (progress > 0 && i === 0);
             const gap = 4.5; 
             const dashLength = (circumference / segments) - gap;
             return (
               <circle key={i} cx="32" cy="32" r="24" fill="none" stroke={isActive ? "var(--color-primary)" : "rgba(255,255,255,0.1)"} strokeWidth="5" strokeDasharray={`${dashLength} ${circumference - dashLength}`} strokeDashoffset={-i * (circumference / segments)} strokeLinecap="butt" className={`${!isDragging ? 'transition-all duration-300' : ''} ${isActive ? 'drop-shadow-[0_0_5px_var(--color-primary)]' : ''}`} />
             )
          })}
       </svg>
       <div className="absolute inset-0 flex items-center justify-center flex-col">
         <span className="font-bold font-['Orbitron'] text-primary transition-colors shadow-black drop-shadow-md" style={{ fontSize: size * 0.25 }}>{Math.round(progress)}<span style={{ fontSize: size * 0.15 }}>%</span></span>
       </div>
    </div>
  );
};

export const SciFiProgressBar = ({ progress }: { progress: number }) => {
  const bars = 40; 
  return (
      <div className="flex gap-0.5 w-full h-2 mt-3">
          {[...Array(bars)].map((_, i) => {
              const threshold = (i + 1) * (100 / bars);
              const isActive = progress >= threshold;
              return <div key={i} className={`flex-1 h-full rounded-sm transition-all duration-300 ${isActive ? 'bg-primary shadow-[0_0_5px_var(--color-primary)]' : 'bg-white/10'}`}></div>
          })}
      </div>
  )
}

export const EcgLoading = ({ text, onCancel }: { text: string; onCancel?: () => void }) => {
  return (
    <div className="absolute inset-0 z-40 bg-black/80 backdrop-blur-sm flex flex-col items-center justify-center pointer-events-auto">
       <div className="flex flex-col items-center relative z-10 w-full max-w-md">
          <div className="text-primary animate-pulse font-['Orbitron'] mb-6 tracking-widest text-xl font-bold drop-shadow-[0_0_10px_var(--color-primary)]">
             {text}
          </div>
          
          <div className="w-full h-32 md:h-40 relative overflow-hidden border border-primary/20 rounded-lg bg-[#050505] shadow-[0_0_20px_rgba(0,0,0,0.8)_inset]">
             {/* Grid */}
             <div className="absolute inset-0 opacity-20" style={{ backgroundImage: "url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMCIgaGVpZ2h0PSIxMCI+PHBhdGggZD0iTTEwIDBMMCAwIDAgMTAiIGZpbGw9Im5vbmUiIHN0cm9rZT0icmdiYSgwLCAyNDMsIDI1NSwgMSkiIHN0cm9rZS13aWR0aD0iMSIvPjwvc3ZnPg==')" }}></div>
             
             <style>{`
                 @keyframes ecg-scroll {
                     0% { transform: translateX(0); }
                     100% { transform: translateX(-200px); }
                 }
             `}</style>
             
             {/* Wave Container */}
             <div className="absolute inset-y-0 left-0 flex items-center w-[1200px]" style={{ animation: 'ecg-scroll 1.2s linear infinite' }}>
                <svg viewBox="0 0 1200 100" className="w-[1200px] h-full" preserveAspectRatio="none">
                    {/* Glowing Trail layer */}
                    <polyline 
                       points="0,50 100,50 115,20 130,95 150,5 170,50 300,50 315,20 330,95 350,5 370,50 500,50 515,20 530,95 550,5 570,50 700,50 715,20 730,95 750,5 770,50 900,50 915,20 930,95 950,5 970,50 1100,50 1115,20 1130,95 1150,5 1170,50 1200,50" 
                       fill="none" 
                       stroke="var(--color-primary)" 
                       strokeWidth="4" 
                       strokeLinecap="round"
                       strokeLinejoin="round"
                       className="opacity-50 drop-shadow-[0_0_8px_var(--color-primary)]"
                    />
                    {/* Core Core line */}
                    <polyline 
                       points="0,50 100,50 115,20 130,95 150,5 170,50 300,50 315,20 330,95 350,5 370,50 500,50 515,20 530,95 550,5 570,50 700,50 715,20 730,95 750,5 770,50 900,50 915,20 930,95 950,5 970,50 1100,50 1115,20 1130,95 1150,5 1170,50 1200,50" 
                       fill="none" 
                       stroke="#fff" 
                       strokeWidth="1.5" 
                       strokeLinecap="round"
                       strokeLinejoin="round"
                    />
                </svg>
             </div>

             {/* Fade edges */}
             <div className="absolute right-0 top-0 bottom-0 w-16 bg-gradient-to-l from-[#050505] to-transparent z-10 pointer-events-none"></div>
             <div className="absolute left-0 top-0 bottom-0 w-16 bg-gradient-to-r from-[#050505] to-transparent z-10 pointer-events-none"></div>
             
             {/* Center Scanline */}
             <div className="absolute top-0 bottom-0 left-[20%] w-[1px] bg-primary/80 drop-shadow-[0_0_3px_var(--color-primary)] z-20 pointer-events-none"></div>
          </div>
          
          {onCancel && (
              <button onClick={onCancel} className="mt-8 px-8 py-2.5 bg-red-500/10 text-red-500 border border-red-500/30 hover:border-red-500 hover:bg-red-500/20 hover:shadow-[0_0_15px_rgba(239,68,68,0.5)] hover:text-red-400 transition-all font-['Orbitron'] tracking-widest text-sm rounded cursor-pointer pointer-events-auto flex items-center gap-2">
                 <div className="w-2 h-2 rounded-full bg-red-500 animate-[ping_1.5s_infinite]"></div>
                 取消转码 (ABORT)
              </button>
          )}
       </div>
    </div>
  );
};

export const CyberSword = () => {
    const count = 100;
    const dots = Array.from({ length: count });
    return (
        <div className="w-full h-8 flex items-center overflow-hidden mask-gradient-to-r">
             <div className="flex gap-0.5 w-full h-full items-center">
                <style>{`@keyframes sword-pulse { 0% { background-color: rgba(255,255,255,0.05); transform: scaleY(1); } 2% { background-color: var(--color-primary); transform: scaleY(1.8); box-shadow: 0 0 8px var(--color-primary); } 4% { background-color: rgba(255,255,255,0.05); transform: scaleY(1); } 100% { background-color: rgba(255,255,255,0.05); transform: scaleY(1); } }`}</style>
                {dots.map((_, i) => (<div key={i} className="flex-1 h-2 rounded-[1px] transition-all" style={{ animation: 'sword-pulse 5s infinite linear', animationDelay: `${i * 0.03}s` }}></div>))}
            </div>
        </div>
    );
};

// ─── 登录页专属原子 ──────────────────────────────────────────────
// 一套受控的"终端日志 + 全息 HUD + 通行戳印"组件。Login.tsx 的状态机驱动它们：
// 进站 boot 自检 → 等握手 → 提交时进度推到 100 → 成功盖戳。
// 失败/限流也走同一条日志，零额外设计。

export type BootTerminalLineLevel = 'ok' | 'warn' | 'err' | 'pending' | 'info';

export interface BootTerminalLine {
  /** 唯一 key，用于 React 列表 reconcile + 决定光标只跟最后一条 pending 行 */
  id: string;
  level: BootTerminalLineLevel;
  text: string;
}

interface BootTerminalProps {
  lines: BootTerminalLine[];
  /** 终端右下露出来的子元素（表单/按钮区） */
  children?: React.ReactNode;
  /** ARASAKA 等主题下 [OK] 用 var(--color-accent) 金色而非硬编码绿。默认 false。 */
  okFollowsAccent?: boolean;
}

export const BootTerminal: React.FC<BootTerminalProps> = ({ lines, children, okFollowsAccent = false }) => {
  const colorOf = (lvl: BootTerminalLineLevel): string => {
    switch (lvl) {
      case 'ok': return okFollowsAccent ? 'var(--color-accent)' : '#00ff7a';
      case 'warn': return 'var(--color-accent)';
      case 'err': return '#ff3366';
      case 'pending': return 'var(--color-primary)';
      case 'info':
      default: return 'rgba(255,255,255,0.62)';
    }
  };
  const tagOf = (lvl: BootTerminalLineLevel): string => {
    switch (lvl) {
      case 'ok': return '[OK]';
      case 'warn': return '[!?]';
      case 'err': return '[!!]';
      case 'pending': return '[..]';
      case 'info':
      default: return '[··]';
    }
  };

  // 光标只跟最后一条 pending 行；没 pending 行时不显示。
  const lastPendingIdx = (() => {
    for (let i = lines.length - 1; i >= 0; i--) {
      if (lines[i].level === 'pending') return i;
    }
    return -1;
  })();

  return (
    <div className="relative bg-[#0a0a12]/85 backdrop-blur-md border border-white/10 tech-border w-full max-w-[560px]">
      <div className="absolute top-0 right-0 w-16 h-16 border-t-2 border-r-2 border-red-500/50 pointer-events-none"></div>
      {/* 标题栏 */}
      <div className="flex items-center justify-between bg-black/60 border-b border-white/5 px-3 py-1.5">
        <span className="font-['Orbitron'] tracking-[0.25em] uppercase text-[10px] text-white/60">
          cyberstream@auth:~
        </span>
        <span className="flex items-center gap-2 text-white/40 text-[10px] font-['Rajdhani'] tracking-widest">
          <span>×</span><span>─</span><span>□</span>
        </span>
      </div>
      {/* 日志区 */}
      <div className="px-4 pt-3 pb-2 font-['Rajdhani'] text-xs leading-relaxed">
        <style>{`@keyframes term-cursor-blink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }`}</style>
        {lines.map((line, idx) => (
          <div key={line.id} className="flex gap-2 items-baseline">
            <span style={{ color: colorOf(line.level), letterSpacing: '0.05em' }}>
              {tagOf(line.level)}
            </span>
            <span className="text-white/75 truncate">
              {line.text}
              {idx === lastPendingIdx && (
                <span
                  aria-hidden="true"
                  className="inline-block ml-1 w-2 h-3 align-middle"
                  style={{ background: 'var(--color-primary)', animation: 'term-cursor-blink 1s steps(2) infinite' }}
                />
              )}
            </span>
          </div>
        ))}
      </div>
      {/* 表单 / 操作区 */}
      {children && (
        <div className="px-4 pb-4 pt-1 border-t border-white/5">
          {children}
        </div>
      )}
    </div>
  );
};

interface IdentityHUDProps {
  /** 0-100，外圈进度 */
  progress?: number;
  /** 状态文本，画在 HUD 中央 */
  label?: string;
  size?: number;
}

// 同心三环 + 极坐标扫描线 + 节点点缀。纯 SVG，prefers-reduced-motion 下旋转停帧但保留发光。
export const IdentityHUD: React.FC<IdentityHUDProps> = ({ progress = 60, label = 'STANDBY', size = 320 }) => {
  const r1 = 110, r2 = 84, r3 = 54;
  const c1 = 2 * Math.PI * r1;
  const ringDash = `${(c1 * progress) / 100} ${c1}`;
  // 六边形节点位置
  const hexNodes = Array.from({ length: 6 }).map((_, i) => {
    const a = (Math.PI / 3) * i - Math.PI / 2;
    return { x: 140 + r2 * Math.cos(a), y: 140 + r2 * Math.sin(a), idx: i };
  });

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <style>{`
        @keyframes hud-rot-slow { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes hud-rot-rev { from { transform: rotate(360deg); } to { transform: rotate(0deg); } }
        @keyframes hud-sweep { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .hud-layer-slow { animation: hud-rot-slow 60s linear infinite; transform-origin: 140px 140px; }
        .hud-layer-rev { animation: hud-rot-rev 90s linear infinite; transform-origin: 140px 140px; }
        .hud-sweep { animation: hud-sweep 4s linear infinite; transform-origin: 140px 140px; }
        @media (prefers-reduced-motion: reduce) {
          .hud-layer-slow, .hud-layer-rev, .hud-sweep { animation: none !important; }
        }
      `}</style>
      <svg viewBox="0 0 280 280" width={size} height={size} className="block" aria-hidden="true">
        {/* 外圈进度 */}
        <g className="hud-layer-slow">
          <circle cx="140" cy="140" r={r1} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="1" />
          <circle
            cx="140" cy="140" r={r1}
            fill="none"
            stroke="var(--color-primary)"
            strokeWidth="1.5"
            strokeDasharray={ringDash}
            strokeLinecap="round"
            transform="rotate(-90 140 140)"
            style={{ filter: 'drop-shadow(0 0 6px var(--color-primary))', transition: 'stroke-dasharray 0.6s ease-out' }}
          />
          {/* 外圈刻度 */}
          {Array.from({ length: 24 }).map((_, i) => {
            const a = (Math.PI / 12) * i;
            const x1 = 140 + (r1 + 4) * Math.cos(a);
            const y1 = 140 + (r1 + 4) * Math.sin(a);
            const x2 = 140 + (r1 + 10) * Math.cos(a);
            const y2 = 140 + (r1 + 10) * Math.sin(a);
            return (
              <line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={i % 6 === 0 ? 'var(--color-primary)' : 'rgba(255,255,255,0.18)'}
                strokeWidth="1" />
            );
          })}
        </g>
        {/* 中圈六边形节点 */}
        <g className="hud-layer-rev">
          <polygon
            points={hexNodes.map(n => `${n.x},${n.y}`).join(' ')}
            fill="none"
            stroke="var(--color-primary)"
            strokeOpacity="0.45"
            strokeWidth="1"
          />
          {hexNodes.map(n => (
            <circle key={n.idx} cx={n.x} cy={n.y} r="3.5"
              fill="var(--color-primary)"
              style={{ filter: 'drop-shadow(0 0 4px var(--color-primary))' }}
            />
          ))}
        </g>
        {/* 内圈+极坐标扫描线 */}
        <g>
          <circle cx="140" cy="140" r={r3} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="1" />
          <circle cx="140" cy="140" r={r3 - 14} fill="none" stroke="var(--color-primary)" strokeOpacity="0.35" strokeWidth="1" strokeDasharray="2 4" />
          <g className="hud-sweep">
            <line x1="140" y1="140" x2="140" y2={140 - r3} stroke="var(--color-primary)" strokeWidth="1.2"
              style={{ filter: 'drop-shadow(0 0 4px var(--color-primary))' }} />
          </g>
          <circle cx="140" cy="140" r="3" fill="var(--color-primary)" />
        </g>
        {/* 中央文字 */}
        <text x="140" y="232" textAnchor="middle"
          fill="var(--color-primary)"
          style={{ filter: 'drop-shadow(0 0 4px var(--color-primary))' }}
          fontFamily="Orbitron, sans-serif"
          fontSize="11"
          letterSpacing="3"
        >
          {label.toUpperCase()}
        </text>
        <text x="140" y="248" textAnchor="middle"
          fill="rgba(255,255,255,0.45)"
          fontFamily="Rajdhani, sans-serif"
          fontSize="10"
          letterSpacing="1.5"
        >
          {`${Math.round(progress)}% · IDENTITY CHECK`}
        </text>
      </svg>
    </div>
  );
};

interface StampOverlayProps {
  visible: boolean;
  /** 戳印里的中段文字，比如 NODE-7F2A */
  nodeId?: string;
  /** ISO 时间戳；不传时取 now */
  issuedAt?: string;
}

// 提交成功后短暂叠一帧"ID VERIFIED"印章。500ms 后由 Login.tsx 跳路由。
export const StampOverlay: React.FC<StampOverlayProps> = ({ visible, nodeId = '----', issuedAt }) => {
  const ts = issuedAt || new Date().toISOString();
  if (!visible) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none">
      <style>{`
        @keyframes stamp-pop {
          0% { transform: scale(0.6) rotate(-8deg); opacity: 0; }
          55% { transform: scale(1.08) rotate(-4deg); opacity: 1; }
          100% { transform: scale(1) rotate(-3deg); opacity: 1; }
        }
        @keyframes stamp-flash {
          0%, 100% { box-shadow: 0 0 0 rgba(0, 255, 122, 0); }
          50% { box-shadow: 0 0 60px rgba(0, 255, 122, 0.55); }
        }
      `}</style>
      <div
        className="relative px-10 py-5 border-2 backdrop-blur-md"
        style={{
          borderColor: 'var(--color-accent)',
          background: 'rgba(10,10,18,0.78)',
          animation: 'stamp-pop 320ms cubic-bezier(.2,.8,.2,1) forwards, stamp-flash 600ms ease-out 320ms 1',
        }}
      >
        <div className="absolute -top-1 -right-1 w-6 h-6 border-t-2 border-r-2" style={{ borderColor: 'var(--color-accent)' }}></div>
        <div className="absolute -bottom-1 -left-1 w-6 h-6 border-b-2 border-l-2" style={{ borderColor: 'var(--color-accent)' }}></div>
        <div className="font-['Orbitron'] font-black tracking-[0.3em] text-2xl text-center"
          style={{ color: 'var(--color-accent)', textShadow: '0 0 14px var(--color-accent)' }}>
          ■ ID VERIFIED
        </div>
        <div className="font-['Rajdhani'] tracking-widest text-xs text-white/65 text-center mt-1.5">
          NODE-{nodeId} · {ts.replace('T', ' ').replace(/\.\d+Z$/, 'Z')}
        </div>
      </div>
    </div>
  );
};
