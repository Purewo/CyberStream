import React, { useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, XOctagon } from 'lucide-react';
import { ToastType } from '../../utils';

interface ToastData {
  id: number;
  message: string;
  type: ToastType;
  duration: number;
}

/** 赛博风弹窗：黑底 + 双色描边（青/玫红/霓虹黄）+ 角标 + 倒计时进度条。
 *  原版用 Tailwind 默认 green-500/red-500，看着像 Bootstrap，跟整体赛博调性
 *  不搭。改成 var(--color-primary)/var(--color-secondary)/var(--color-accent)
 *  系统色 + 等宽字体，配 corner cut 让它跟详情页 tech-badge 一脉相承。 */
export const Toaster = () => {
  const [toasts, setToasts] = useState<ToastData[]>([]);

  useEffect(() => {
    const handleToast = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const id = Date.now() + Math.random();
      const duration = detail.duration || 3000;
      setToasts((prev) => [...prev, { id, message: detail.message, type: detail.type, duration }]);

      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, duration);
    };

    window.addEventListener('cyber:toast', handleToast);
    return () => window.removeEventListener('cyber:toast', handleToast);
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-20 right-6 z-[100] flex flex-col gap-3 pointer-events-none">
      {toasts.map((t) => (
        <CyberToast key={t.id} {...t} />
      ))}
    </div>
  );
};

interface CyberToastProps {
  message: string;
  type: ToastType;
  duration: number;
}

const TYPE_THEMES: Record<
  ToastType,
  { tag: string; color: string; rgb: string; Icon: React.ElementType }
> = {
  success: {
    tag: 'ACK',
    color: 'var(--color-primary)',
    // CYBER 主题的 #22d3ee 拆 RGB；ARASAKA / GOLDEN 主题如果切换会跟下面 var
    // 颜色对不齐——先以默认 CYBER 为准，后续可在 themes 里加 -rgb 变量。
    rgb: '34, 211, 238',
    Icon: CheckCircle2,
  },
  error: {
    tag: 'ERR',
    color: '#ff2e6c',
    rgb: '255, 46, 108',
    Icon: XOctagon,
  },
  warning: {
    tag: 'WARN',
    color: '#f5f00b',
    rgb: '245, 240, 11',
    Icon: AlertTriangle,
  },
  info: {
    tag: 'INFO',
    color: 'var(--color-primary)',
    rgb: '34, 211, 238',
    Icon: Info,
  },
};

const CyberToast: React.FC<CyberToastProps> = ({ message, type, duration }) => {
  const theme = TYPE_THEMES[type] || TYPE_THEMES.info;
  const { Icon } = theme;
  return (
    <div
      className="relative pointer-events-auto min-w-[300px] max-w-[420px] font-mono cyber-toast-enter"
      style={{
        // 黑底 + 玻璃化模糊 + 双层边框（外层主色，内层暗 1 档）
        background:
          'linear-gradient(135deg, rgba(6, 12, 18, 0.92) 0%, rgba(2, 6, 10, 0.96) 100%)',
        border: `1px solid ${theme.color}`,
        boxShadow: `0 0 18px rgba(${theme.rgb}, 0.35), inset 0 0 0 1px rgba(${theme.rgb}, 0.15)`,
        backdropFilter: 'blur(8px)',
        clipPath:
          'polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px))',
      }}
    >
      {/* 顶部装饰条 + 类型 tag */}
      <div className="flex items-center justify-between px-3 py-1 border-b" style={{ borderColor: `rgba(${theme.rgb}, 0.3)` }}>
        <div className="flex items-center gap-2">
          <div
            className="w-1.5 h-1.5 rounded-full animate-pulse"
            style={{ backgroundColor: theme.color, boxShadow: `0 0 8px ${theme.color}` }}
          />
          <span
            className="text-[10px] font-bold tracking-[0.2em] uppercase font-['Orbitron']"
            style={{ color: theme.color }}
          >
            {theme.tag}
          </span>
        </div>
        <span className="text-[9px] text-gray-500 tracking-widest">SYS::TOAST</span>
      </div>

      {/* 主体内容 */}
      <div className="flex items-start gap-3 px-3 py-3">
        <Icon size={18} style={{ color: theme.color, flexShrink: 0, marginTop: 2 }} />
        <span className="text-sm text-white tracking-wide leading-snug whitespace-pre-line">
          {message}
        </span>
      </div>

      {/* 底部倒计时进度条 */}
      <div className="absolute left-0 right-0 bottom-0 h-[2px] overflow-hidden" style={{ backgroundColor: `rgba(${theme.rgb}, 0.12)` }}>
        <div
          className="h-full"
          style={{
            backgroundColor: theme.color,
            boxShadow: `0 0 6px ${theme.color}`,
            animation: `cyberToastCountdown ${duration}ms linear forwards`,
          }}
        />
      </div>

      {/* 右上角和左下角的"切角"装饰线 */}
      <span
        className="absolute top-0 right-0 w-3 h-3 pointer-events-none"
        style={{
          background: `linear-gradient(225deg, ${theme.color} 0%, ${theme.color} 50%, transparent 50%)`,
        }}
      />
      <span
        className="absolute bottom-0 left-0 w-3 h-3 pointer-events-none"
        style={{
          background: `linear-gradient(45deg, ${theme.color} 0%, ${theme.color} 50%, transparent 50%)`,
        }}
      />
    </div>
  );
};
