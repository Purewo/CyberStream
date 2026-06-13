import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Eye, EyeOff } from 'lucide-react';
import { authService, AuthStatus } from '../api/auth';
import { BootTerminalLine, IdentityHUD, StampOverlay, TechBadge, FilterTag } from '../components/ui/CyberComponents';
import { toast } from '../utils';

type LoginPhase = 'idle' | 'authenticating' | 'cooldown' | 'verified' | 'severing';

interface LoginProps {
  onLoggedIn: (status: AuthStatus) => void;
  themeName?: string;
}

// 中央玻璃卡 + 氛围辉光 + 远处 HUD 当氛围灯。表单居中、大圆角、多层阴影做立体感。
// 状态机：idle → authenticating → (verified|cooldown|err) → idle
// 提交时 HUD 进度从 60 推到 100，终端日志同步，成功瞬间叠 StampOverlay 一帧再跳。
export const Login: React.FC<LoginProps> = ({ onLoggedIn, themeName = 'CYBER' }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [phase, setPhase] = useState<LoginPhase>('idle');
  const [hudProgress, setHudProgress] = useState(60);
  const [hudLabel, setHudLabel] = useState('STANDBY');
  const [stamped, setStamped] = useState(false);
  const [requestModal, setRequestModal] = useState(false);
  const [cooldownLeft, setCooldownLeft] = useState(0);
  const [verifiedNodeId, setVerifiedNodeId] = useState('----');

  const baseBootLog: BootTerminalLine[] = useMemo(() => ([
    { id: 'boot-1', level: 'ok', text: 'crypto/init ........... 12ms' },
    { id: 'boot-2', level: 'ok', text: 'device/0xA3F1 trusted' },
    { id: 'boot-3', level: 'ok', text: 'uplink established' },
    { id: 'boot-4', level: 'pending', text: 'awaiting handshake' },
  ]), []);
  const [extraLines, setExtraLines] = useState<BootTerminalLine[]>([]);
  const lines = useMemo(() => [...baseBootLog, ...extraLines], [baseBootLog, extraLines]);

  // 非 CYBER 主题下 [OK] 跟主题色，避免硬编码绿与血红/金撞色
  const okFollowsAccent = themeName !== 'CYBER';

  const cooldownRef = useRef<number | null>(null);

  useEffect(() => {
    if (phase !== 'cooldown' || cooldownLeft <= 0) return;
    cooldownRef.current = window.setTimeout(() => {
      setCooldownLeft(s => s - 1);
    }, 1000);
    return () => {
      if (cooldownRef.current) window.clearTimeout(cooldownRef.current);
    };
  }, [phase, cooldownLeft]);

  useEffect(() => {
    if (phase === 'cooldown' && cooldownLeft === 0) {
      setPhase('idle');
      setExtraLines(prev => [...prev, { id: `cool-end-${Date.now()}`, level: 'info', text: 'cooldown cleared, ready' }]);
    }
  }, [phase, cooldownLeft]);

  const fmtCooldown = (sec: number) => {
    const m = Math.floor(sec / 60), s = sec % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (phase !== 'idle' || !username.trim() || !password) return;

    setPhase('authenticating');
    setHudLabel('NEGOTIATING');
    setHudProgress(78);
    setExtraLines(prev => [...prev, { id: `req-${Date.now()}`, level: 'pending', text: `negotiating tls handshake for ${username}` }]);

    const result = await authService.login(username.trim(), password);

    if (result.ok && result.data) {
      setExtraLines(prev => {
        const replaced = prev.map(l => l.level === 'pending' ? { ...l, level: 'ok' as const, text: 'handshake accepted' } : l);
        return [
          ...replaced,
          { id: `ok-${Date.now()}`, level: 'ok', text: `welcome, ${result.data!.user?.display_name || result.data!.user?.username || username}` },
        ];
      });
      setHudProgress(100);
      setHudLabel('VERIFIED');

      const uid = result.data.user?.id ?? 0;
      setVerifiedNodeId(uid.toString(16).toUpperCase().padStart(4, '0').slice(-4));
      setStamped(true);
      setPhase('verified');

      // 380ms 后切到 severing：戳记快速淡出 → 剑气登场 → 屏幕一分为二飞散
      window.setTimeout(() => {
        setStamped(false);
        setPhase('severing');
      }, 380);

      // 380(verified→severing) + 1200(劈屏总时长) = 1580ms 后跳转
      window.setTimeout(() => {
        onLoggedIn(result.data!);
      }, 1580);
      return;
    }

    if (result.status === 429) {
      const wait = result.retryAfterSec ?? 60;
      setHudLabel('THROTTLED');
      setHudProgress(45);
      setExtraLines(prev => {
        const replaced = prev.map(l => l.level === 'pending' ? { ...l, level: 'err' as const, text: `cooldown ${fmtCooldown(wait)} remaining` } : l);
        return [...replaced, { id: `cool-${Date.now()}`, level: 'pending', text: `cooldown ticking ${fmtCooldown(wait)}` }];
      });
      setCooldownLeft(wait);
      setPhase('cooldown');
      toast.error(result.msg || `登录尝试过多，请等待 ${fmtCooldown(wait)} 后重试`);
      return;
    }

    setHudLabel('REJECTED');
    setHudProgress(35);
    setExtraLines(prev => prev.map(l => l.level === 'pending' ? {
      ...l,
      level: 'err' as const,
      text: result.msg || 'handshake rejected: invalid credentials',
    } : l));
    toast.error(result.msg || '凭证无效');
    setPhase('idle');
  };

  useEffect(() => {
    if (phase !== 'cooldown') return;
    setExtraLines(prev => prev.map(l => l.level === 'pending' && l.text.startsWith('cooldown ticking')
      ? { ...l, text: `cooldown ticking ${fmtCooldown(cooldownLeft)}` }
      : l
    ));
  }, [cooldownLeft, phase]);

  const submitDisabled = phase !== 'idle' || !username.trim() || !password;
  const submitLabel = (() => {
    switch (phase) {
      case 'authenticating': return '正在握手…';
      case 'verified': return '已通过';
      case 'cooldown': return `已锁定 · ${fmtCooldown(cooldownLeft)}`;
      default: return '登录';
    }
  })();

  return (
    <div data-phase={phase} className="login-root fixed inset-0 z-[200] overflow-hidden flex items-center justify-center" style={{ backgroundColor: 'var(--color-bg)' }}>
      {/* 背景：网格 + 扫描线（沿用全局类） */}
      <div className="absolute inset-0 perspective-grid pointer-events-none opacity-50"></div>
      <div className="absolute inset-0 scanlines pointer-events-none"></div>

      {/* 双色辉光氛围灯 */}
      <div className="absolute -top-48 -left-48 w-[600px] h-[600px] rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, var(--color-secondary) 0%, transparent 65%)', opacity: 0.18, filter: 'blur(40px)' }} />
      <div className="absolute -bottom-48 -right-48 w-[680px] h-[680px] rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, var(--color-primary) 0%, transparent 65%)', opacity: 0.18, filter: 'blur(40px)' }} />

      {/* 远处氛围 HUD：在屏幕右下偏外，缩小+大幅降透明度做氛围灯 */}
      <div className="absolute -right-32 -bottom-32 pointer-events-none hidden md:block" style={{ opacity: 0.18 }} aria-hidden="true">
        <IdentityHUD progress={hudProgress} label={hudLabel} size={520} />
      </div>

      {/* 顶栏：仅保留品牌字标 */}
      <div className="absolute top-6 left-8 z-10">
        <span className="font-['Orbitron'] tracking-[0.4em] text-sm font-black"
          style={{ color: 'var(--color-primary)', textShadow: '0 0 10px var(--color-primary)' }}>
          CYBER//STREAM
        </span>
      </div>

      {/* 中央玻璃卡 */}
      <div className="relative z-10 w-[min(440px,92vw)]">
        <style>{`
          @keyframes login-card-in {
            0% { transform: translateY(24px) scale(0.97); opacity: 0; }
            100% { transform: translateY(0) scale(1); opacity: 1; }
          }
          @keyframes login-ring-spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
          /* 盖掉 Chrome/Safari 记住密码后填充的浅色背景：用 inset 巨型阴影伪造透明黑底，
             文字色用 -webkit-text-fill-color 强制走主色。 */
          input:-webkit-autofill,
          input:-webkit-autofill:hover,
          input:-webkit-autofill:focus,
          input:-webkit-autofill:active {
            -webkit-box-shadow: 0 0 0 1000px rgba(0,0,0,0.55) inset !important;
            box-shadow: 0 0 0 1000px rgba(0,0,0,0.55) inset !important;
            -webkit-text-fill-color: var(--color-primary) !important;
            caret-color: var(--color-primary) !important;
            transition: background-color 9999s ease-in-out 0s;
          }
          @media (prefers-reduced-motion: reduce) {
            .login-card-anim, .login-ring-spin { animation: none !important; }
          }

          /* ─── 剑气劈屏 · 玄铁裂空 ─── */
          /* 切线方向：右上 → 左下，单位向量 ≈ (-1,1)/√2，法线 (1,1)/√2 与 (-1,-1)/√2 */
          @keyframes blade-slash {
            0%   { stroke-dashoffset: 1; opacity: 0; filter: blur(0.5px); }
            10%  { opacity: 1; }
            55%  { opacity: 1; filter: blur(0px); }
            100% { stroke-dashoffset: 0; opacity: 0.95; }
          }
          @keyframes blade-glow-fade {
            0%, 30% { opacity: 0; }
            55% { opacity: 0.95; }
            100% { opacity: 0; }
          }
          @keyframes sever-flash {
            0%, 25% { opacity: 0; }
            32% { opacity: 1; }
            55% { opacity: 0.55; }
            100% { opacity: 0; }
          }
          @keyframes sever-half-top {
            0%   { transform: translate3d(0, 0, 0) rotate(0deg); filter: blur(0px); opacity: 1; }
            8%   { transform: translate3d(0, 0, 0) rotate(0deg); filter: blur(0px); opacity: 1; }
            100% { transform: translate3d(-12vw, -10vh, 0) rotate(-1.6deg); filter: blur(8px); opacity: 0; }
          }
          @keyframes sever-half-bottom {
            0%   { transform: translate3d(0, 0, 0) rotate(0deg); filter: blur(0px); opacity: 1; }
            8%   { transform: translate3d(0, 0, 0) rotate(0deg); filter: blur(0px); opacity: 1; }
            100% { transform: translate3d(12vw, 10vh, 0) rotate(1.6deg); filter: blur(8px); opacity: 0; }
          }
          @keyframes spark-fly-up {
            0%   { transform: translate3d(0,0,0) scale(0.4); opacity: 0; }
            15%  { opacity: 1; }
            100% { transform: translate3d(var(--sx), var(--sy), 0) scale(0); opacity: 0; }
          }
          @keyframes spark-fly-dn {
            0%   { transform: translate3d(0,0,0) scale(0.4); opacity: 0; }
            15%  { opacity: 1; }
            100% { transform: translate3d(var(--sx), var(--sy), 0) scale(0); opacity: 0; }
          }
          @keyframes sever-card-charge {
            0%   { transform: scale(1); }
            100% { transform: scale(0.96); }
          }

          .sever-root { animation: sever-card-charge 80ms cubic-bezier(.4,0,.2,1) forwards; }
          .sever-blade-line {
            stroke-dasharray: 1;
            stroke-dashoffset: 1;
            animation: blade-slash 320ms cubic-bezier(.55,.05,.25,1) 80ms forwards;
          }
          .sever-blade-halo {
            opacity: 0;
            animation: blade-glow-fade 700ms cubic-bezier(.4,0,.2,1) 80ms forwards;
          }
          .sever-flash {
            opacity: 0;
            animation: sever-flash 480ms cubic-bezier(.2,.8,.2,1) 200ms forwards;
          }
          .sever-half-top {
            animation: sever-half-top 1120ms cubic-bezier(.16,.84,.24,1) 80ms forwards;
            will-change: transform, opacity, filter;
          }
          .sever-half-bottom {
            animation: sever-half-bottom 1120ms cubic-bezier(.16,.84,.24,1) 80ms forwards;
            will-change: transform, opacity, filter;
          }
          .sever-spark {
            animation-duration: 520ms;
            animation-timing-function: cubic-bezier(.2,.8,.2,1);
            animation-delay: 260ms;
            animation-fill-mode: forwards;
            will-change: transform, opacity;
          }
          /* 隐藏 severing 期间原始登录视觉，让位给两份 clip 克隆 */
          .login-content-hidden { visibility: hidden; }

          @keyframes blade-residue {
            0%, 30% { opacity: 0; }
            45% { opacity: 0.85; }
            100% { opacity: 0; }
          }
          .sever-blade-residue {
            opacity: 0;
            animation: blade-residue 1000ms cubic-bezier(.4,0,.2,1) 200ms forwards;
            filter: blur(0.8px);
          }

          /* severing 时隐藏原始登录子节点（除剑气覆盖层），由两份 clip-path 镜像接管视觉 */
          .login-root[data-phase="severing"] > *:not(.sever-overlay) {
            visibility: hidden;
          }

          @media (prefers-reduced-motion: reduce) {
            .sever-half-top, .sever-half-bottom { animation: none !important; opacity: 0; transition: opacity 200ms linear; }
            .sever-blade-line, .sever-blade-halo, .sever-blade-residue, .sever-flash, .sever-spark, .sever-root { animation: none !important; }
          }
        `}</style>

        <div
          className="login-card-anim relative rounded-3xl border overflow-hidden"
          style={{
            background: 'linear-gradient(180deg, rgba(20,20,30,0.78) 0%, rgba(10,10,18,0.88) 100%)',
            borderColor: 'rgba(255,255,255,0.08)',
            boxShadow:
              '0 30px 80px -20px rgba(0,0,0,0.7),' +
              ' 0 0 0 1px rgba(255,255,255,0.04) inset,' +
              ' 0 0 60px -10px var(--color-primary)',
            backdropFilter: 'blur(18px) saturate(1.2)',
            WebkitBackdropFilter: 'blur(18px) saturate(1.2)',
            animation: 'login-card-in 600ms cubic-bezier(.2,.8,.2,1) both',
          }}
        >
          {/* 顶部高光描边 */}
          <div className="absolute inset-x-0 top-0 h-[1px] pointer-events-none"
            style={{ background: 'linear-gradient(90deg, transparent, var(--color-primary), transparent)', opacity: 0.55 }} />

          {/* HUD 头像区 */}
          <div className="relative flex flex-col items-center pt-9 pb-4 px-8">
            <div className="relative w-[140px] h-[140px]">
              {/* 旋转外环 */}
              <div className="absolute inset-0 login-ring-spin rounded-full"
                style={{
                  animation: 'login-ring-spin 18s linear infinite',
                  border: '1px dashed var(--color-primary)',
                  opacity: 0.45,
                }} />
              <div className="absolute inset-2 rounded-full"
                style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
              {/* 中央徽章：黑洞质感球体 */}
              <div className="absolute inset-5 rounded-full flex items-center justify-center"
                style={{
                  // 中心纯黑、外缘微微透出环境，假装一个吞光的黑洞
                  background:
                    'radial-gradient(circle at 50% 50%, #000000 0%, #000000 55%, rgba(8,8,14,0.92) 78%, rgba(20,20,32,0.85) 100%)',
                  border: '1px solid rgba(255,255,255,0.06)',
                  boxShadow:
                    // 外圈吸积盘：主色微光做能量边
                    '0 0 24px -6px var(--color-primary),' +
                    // 内描边强压暗，凹陷感
                    ' inset 0 0 32px 4px rgba(0,0,0,0.95),' +
                    // 顶部一丝主色折射，破单调全黑
                    ' inset 0 6px 14px -6px color-mix(in srgb, var(--color-primary) 35%, transparent)',
                }}>
                {/* 顶部微高光：球体立体感 */}
                <span aria-hidden="true"
                  className="absolute top-[10%] left-[20%] w-[55%] h-[35%] rounded-full pointer-events-none"
                  style={{
                    background: 'radial-gradient(ellipse at center, rgba(255,255,255,0.08) 0%, transparent 70%)',
                    filter: 'blur(2px)',
                  }} />
                <span className="relative font-['Orbitron'] font-black text-2xl tracking-[0.15em]"
                  style={{ color: 'var(--color-primary)', textShadow: '0 0 12px var(--color-primary), 0 0 4px var(--color-primary)' }}>
                  CS
                </span>
              </div>
            </div>

            <h1 className="mt-5 font-['Orbitron'] font-black tracking-[0.3em] text-xl uppercase text-white">
              欢迎登录
            </h1>
            <p className="mt-1 text-[11px] tracking-[0.3em] uppercase font-['Rajdhani']"
              style={{ color: 'var(--color-primary)' }}>
              赛博 · 影流 · 节点
            </p>
          </div>

          {/* 表单 */}
          <form onSubmit={handleSubmit} className="px-8 pt-2 pb-8 flex flex-col gap-3">
            <FieldInput
              label="账号"
              type="text"
              autoComplete="username"
              placeholder="用户名 / 邮箱"
              value={username}
              onChange={setUsername}
              disabled={phase !== 'idle'}
            />
            <FieldInput
              label="密码"
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={setPassword}
              disabled={phase !== 'idle'}
              withReveal
            />

            <button
              type="submit"
              disabled={submitDisabled}
              className="group relative mt-2 w-full px-5 py-3 rounded-xl border font-['Orbitron'] tracking-[0.3em] text-xs uppercase overflow-hidden transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                borderColor: 'var(--color-primary)',
                color: '#0a0a12',
                background: 'linear-gradient(180deg, var(--color-primary) 0%, color-mix(in srgb, var(--color-primary) 80%, var(--color-secondary)) 100%)',
                boxShadow: '0 8px 24px -8px var(--color-primary), 0 0 0 1px rgba(255,255,255,0.08) inset',
              }}
            >
              <span className="relative z-10 flex items-center justify-center gap-2 font-bold">
                {submitLabel}
                {phase === 'idle' && <ChevronRight size={14} />}
              </span>
              <span aria-hidden="true"
                className="absolute inset-y-0 -left-full w-1/2 group-hover:left-full transition-all duration-700 pointer-events-none"
                style={{ background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.45), transparent)' }} />
            </button>

            <div className="flex items-center justify-end mt-2 text-[11px] font-['Rajdhani'] tracking-widest text-white/50">
              <button
                type="button"
                onClick={() => setRequestModal(true)}
                className="register-link group relative px-3 py-1.5 rounded-md border border-transparent transition-all duration-200 hover:scale-[1.04] active:scale-100"
              >
                <span className="relative z-10 transition-colors group-hover:text-primary">
                  ※ 注册账号
                </span>
                {/* hover 时浮现描边 + 主色光晕 */}
                <span aria-hidden="true"
                  className="absolute inset-0 rounded-md opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none"
                  style={{
                    border: '1px solid color-mix(in srgb, var(--color-primary) 60%, transparent)',
                    boxShadow: '0 0 12px -2px var(--color-primary), inset 0 0 12px -6px var(--color-primary)',
                    background: 'color-mix(in srgb, var(--color-primary) 8%, transparent)',
                  }} />
                {/* hover 时一道斜向扫光 */}
                <span aria-hidden="true"
                  className="absolute inset-0 rounded-md overflow-hidden pointer-events-none">
                  <span className="absolute inset-y-0 -left-full w-1/2 group-hover:left-full transition-all duration-700"
                    style={{ background: 'linear-gradient(90deg, transparent, color-mix(in srgb, var(--color-primary) 35%, transparent), transparent)' }} />
                </span>
              </button>
            </div>
          </form>
        </div>

        {/* 卡片底纹小注 */}
        <div className="text-center mt-4 text-[10px] font-['Rajdhani'] tracking-[0.4em] text-white/30">
          私人节点 · 仅限授权访问
        </div>
      </div>

      {/* 成功盖戳 */}
      <StampOverlay visible={stamped} nodeId={verifiedNodeId} />

      {/* REQUEST ID modal */}
      {requestModal && (
        <div className="fixed inset-0 z-[210] flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setRequestModal(false)}>
          <div className="relative max-w-md w-[90%] rounded-2xl border p-6"
            style={{
              background: 'linear-gradient(180deg, rgba(20,20,30,0.92), rgba(10,10,18,0.95))',
              borderColor: 'var(--color-primary)',
              boxShadow: '0 30px 80px -10px rgba(0,0,0,0.7), 0 0 50px -10px var(--color-primary)',
            }}
            onClick={(e) => e.stopPropagation()}>
            <h3 className="font-['Orbitron'] tracking-[0.3em] text-lg mb-3" style={{ color: 'var(--color-primary)' }}>
              注册账号
            </h3>
            <p className="text-white/70 leading-relaxed text-sm font-['Noto_Sans_SC']">
              这是一个私人节点。CyberStream 当前不开放自助注册——
              账号由节点管理员开通。请联系你的管理员要一组用户名 / 初始密钥。
            </p>
            <p className="text-white/45 leading-relaxed text-xs font-['Rajdhani'] tracking-wider mt-3">
              首次登录后建议立刻在「账户」中修改密码与显示名。
            </p>
            <div className="flex justify-end mt-5">
              <FilterTag label="知道了" active onClick={() => setRequestModal(false)} />
            </div>
          </div>
        </div>
      )}

      {/* 剑气劈屏 · 玄铁裂空 ─── verified→severing 阶段触发 */}
      {phase === 'severing' && <SeverOverlay nodeId={verifiedNodeId} />}
    </div>
  );
};

// ─── 局部子组件 ───────────────────────────────────────────────

const FieldInput: React.FC<{
  label: string;
  type: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete?: string;
  disabled?: boolean;
  /** 密码字段：右侧渲染一个 Eye 切换显隐。 */
  withReveal?: boolean;
}> = ({ label, type, placeholder, value, onChange, autoComplete, disabled, withReveal }) => {
  const [focused, setFocused] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const effectiveType = withReveal && revealed ? 'text' : type;
  return (
    <label className="flex flex-col gap-1.5">
      <span className="font-['Orbitron'] tracking-[0.3em] text-[10px] text-white/55 uppercase">{label}</span>
      <div className="relative">
        <input
          type={effectiveType}
          value={value}
          autoComplete={autoComplete}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          className={`w-full bg-black/40 px-4 py-3 ${withReveal ? 'pr-11' : ''} rounded-xl text-sm placeholder-white/25 outline-none transition-all disabled:opacity-60 font-mono tracking-wider`}
          style={{
            color: 'var(--color-primary)',
            caretColor: 'var(--color-primary)',
            textShadow: focused ? '0 0 8px var(--color-primary)' : '0 0 4px color-mix(in srgb, var(--color-primary) 60%, transparent)',
            border: `1px solid ${focused ? 'var(--color-primary)' : 'rgba(255,255,255,0.08)'}`,
            boxShadow: focused
              ? '0 0 0 4px color-mix(in srgb, var(--color-primary) 14%, transparent), 0 0 20px -8px var(--color-primary)'
              : 'none',
          }}
        />
        {withReveal && (
          <button
            type="button"
            tabIndex={-1}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setRevealed(v => !v)}
            aria-label={revealed ? '隐藏密码' : '显示密码'}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-md text-white/45 hover:text-primary transition-colors disabled:opacity-40"
            disabled={disabled}
          >
            {revealed ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        )}
      </div>
    </label>
  );
};

// 紧凑版终端日志：每条只显示等级标签 + 文字，不带光标 / 标题栏，留极客味但不抢戏
const CompactBootLog: React.FC<{ lines: BootTerminalLine[]; okFollowsAccent: boolean }> = ({ lines, okFollowsAccent }) => {
  const colorOf = (lvl: BootTerminalLine['level']): string => {
    switch (lvl) {
      case 'ok': return okFollowsAccent ? 'var(--color-accent)' : '#00ff7a';
      case 'warn': return 'var(--color-accent)';
      case 'err': return '#ff3366';
      case 'pending': return 'var(--color-primary)';
      default: return 'rgba(255,255,255,0.5)';
    }
  };
  const tagOf = (lvl: BootTerminalLine['level']): string => {
    switch (lvl) {
      case 'ok': return '[OK]';
      case 'warn': return '[!?]';
      case 'err': return '[!!]';
      case 'pending': return '[..]';
      default: return '[··]';
    }
  };
  // 只显示最新 4 条，避免无限增长把卡撑大
  const tail = lines.slice(-4);
  const lastPendingIdx = (() => {
    for (let i = tail.length - 1; i >= 0; i--) {
      if (tail[i].level === 'pending') return i;
    }
    return -1;
  })();
  return (
    <>
      <style>{`@keyframes term-cursor-blink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }`}</style>
      {tail.map((line, idx) => (
        <div key={line.id} className="flex gap-2 items-baseline">
          <span style={{ color: colorOf(line.level), letterSpacing: '0.05em' }}>{tagOf(line.level)}</span>
          <span className="text-white/65 truncate">
            {line.text}
            {idx === lastPendingIdx && (
              <span aria-hidden="true"
                className="inline-block ml-1 w-1.5 h-3 align-middle"
                style={{ background: 'var(--color-primary)', animation: 'term-cursor-blink 1s steps(2) infinite' }}
              />
            )}
          </span>
        </div>
      ))}
    </>
  );
};

// ─── 剑气劈屏 · 玄铁裂空 ─────────────────────────────────────────
// 切线方向：屏幕右上角 (110vw, -10vh) → 左下角 (-10vw, 110vh)
// 工作原理：
//   1. 用两份带 clip-path 的镜像层重画登录视觉骨架（网格 + 辉光 + 玻璃卡轮廓 + 字标），
//      原始内容由 .login-root[data-phase="severing"] 全部隐藏，避免重复渲染开销
//   2. 上半三角向左上飞 + 旋转 -1.6deg + blur，下半向右下飞 + 旋转 +1.6deg
//   3. 剑气：SVG line 沿对角线，stroke-dashoffset 从 1→0 划过；外层主色光晕，内层白刃
//   4. 切割闪光：右上原点向外径向白闪一帧
//   5. 火星粒子：8 颗沿切线起 + 向法线方向飞散（CSS variable 注入个性化偏移）
const SeverOverlay: React.FC<{ nodeId: string }> = ({ nodeId }) => {
  // 切线起点 (110, -10)，终点 (-10, 110)（百分比坐标系，x 用 vw，y 用 vh）
  // 8 颗火星沿路径分布，每颗法线方向飞 60-110px
  const sparks = useMemo(() => {
    const arr: { id: number; left: string; top: string; sx: string; sy: string; size: number; up: boolean; delay: number }[] = [];
    for (let i = 0; i < 8; i++) {
      const t = 0.18 + (0.64 * i) / 7; // 沿切线 18%~82%
      const left = `${110 - 120 * t}vw`;
      const top = `${-10 + 120 * t}vh`;
      // 法线 (1,1)/√2 或 (-1,-1)/√2，距离 60~120px
      const dist = 60 + Math.random() * 60;
      const up = i % 2 === 0;
      const sign = up ? -1 : 1;
      const sx = `${sign * dist * 0.7}px`; // 注意：法线指向右下/左上，但视觉上向"两半飞行的方向"飞更合理
      const sy = `${sign * dist * 0.7}px`;
      arr.push({
        id: i,
        left, top,
        sx, sy,
        size: 3 + Math.round(Math.random() * 3),
        up,
        delay: 240 + i * 18,
      });
    }
    return arr;
  }, []);

  return (
    <div className="sever-overlay fixed inset-0 pointer-events-none" style={{ zIndex: 5 }} aria-hidden="true">
      {/* ─── 上半三角（向左上飞） ─── */}
      <div
        className="sever-half-top absolute inset-0"
        style={{ clipPath: 'polygon(0 0, 100% 0, 0 100%)', WebkitClipPath: 'polygon(0 0, 100% 0, 0 100%)' }}
      >
        <SeverMirrorScene />
      </div>
      {/* ─── 下半三角（向右下飞） ─── */}
      <div
        className="sever-half-bottom absolute inset-0"
        style={{ clipPath: 'polygon(100% 0, 100% 100%, 0 100%)', WebkitClipPath: 'polygon(100% 0, 100% 100%, 0 100%)' }}
      >
        <SeverMirrorScene />
      </div>

      {/* ─── 切割瞬间右上角白闪 ─── */}
      <div
        className="sever-flash absolute"
        style={{
          top: '-30vh',
          right: '-30vw',
          width: '110vw',
          height: '110vh',
          background: 'radial-gradient(circle at top right, #ffffff 0%, color-mix(in srgb, var(--color-primary) 70%, white) 18%, transparent 55%)',
          mixBlendMode: 'screen',
        }}
      />

      {/* ─── 剑气本体 ─── */}
      <svg
        className="absolute inset-0 w-full h-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        style={{ overflow: 'visible' }}
      >
        <defs>
          <linearGradient id="bladeGrad" x1="100%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0" />
            <stop offset="20%" stopColor="var(--color-primary)" stopOpacity="0.95" />
            <stop offset="50%" stopColor="#ffffff" stopOpacity="1" />
            <stop offset="80%" stopColor="var(--color-secondary)" stopOpacity="0.95" />
            <stop offset="100%" stopColor="var(--color-secondary)" stopOpacity="0" />
          </linearGradient>
          <filter id="bladeBlur" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="0.6" />
          </filter>
        </defs>
        {/* 外层 halo（粗、模糊、主色） */}
        <line
          className="sever-blade-halo"
          x1="110" y1="-10" x2="-10" y2="110"
          stroke="url(#bladeGrad)"
          strokeWidth="2.4"
          strokeLinecap="round"
          pathLength={1}
          filter="url(#bladeBlur)"
          vectorEffect="non-scaling-stroke"
          style={{ strokeWidth: 24 } as React.CSSProperties}
        />
        {/* 中层光晕 */}
        <line
          className="sever-blade-halo"
          x1="110" y1="-10" x2="-10" y2="110"
          stroke="url(#bladeGrad)"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          style={{ strokeWidth: 8, animationDelay: '120ms' } as React.CSSProperties}
        />
        {/* 内层白刃（划过动画） */}
        <line
          className="sever-blade-line"
          x1="110" y1="-10" x2="-10" y2="110"
          stroke="#ffffff"
          strokeLinecap="round"
          pathLength={1}
          vectorEffect="non-scaling-stroke"
          style={{ strokeWidth: 2 } as React.CSSProperties}
        />
        {/* 余晖：划过后保留 ~600ms 才隐去 */}
        <line
          className="sever-blade-residue"
          x1="110" y1="-10" x2="-10" y2="110"
          stroke="url(#bladeGrad)"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          style={{ strokeWidth: 1.4 } as React.CSSProperties}
        />
      </svg>

      {/* ─── 火星粒子 ─── */}
      {sparks.map(s => (
        <span
          key={s.id}
          className="sever-spark absolute rounded-full"
          style={{
            left: s.left,
            top: s.top,
            width: `${s.size}px`,
            height: `${s.size}px`,
            background: '#ffffff',
            boxShadow: `0 0 ${s.size * 3}px ${s.size}px var(--color-primary)`,
            ['--sx' as string]: s.sx,
            ['--sy' as string]: s.sy,
            animationName: s.up ? 'spark-fly-up' : 'spark-fly-dn',
            animationDelay: `${s.delay}ms`,
          }}
        />
      ))}

      {/* ─── 隐式 nodeId 留作未来扩展（debug 时可以贴回）─── */}
      <span style={{ display: 'none' }}>{nodeId}</span>
    </div>
  );
};

// 镜像场景：在两个 clip-path 三角内分别重画一份"足够像"的登录骨架
// 包含：网格层 + 扫描线 + 双辉光球 + 中央玻璃卡占位 + 顶栏字标
// 不重画 IdentityHUD / 表单文字，因为飞散过程中观众感知不到细节
const SeverMirrorScene: React.FC = () => {
  return (
    <div className="absolute inset-0" style={{ backgroundColor: 'var(--color-bg)' }}>
      <div className="absolute inset-0 perspective-grid pointer-events-none opacity-50" />
      <div className="absolute inset-0 scanlines pointer-events-none" />
      <div
        className="absolute -top-48 -left-48 w-[600px] h-[600px] rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, var(--color-secondary) 0%, transparent 65%)', opacity: 0.18, filter: 'blur(40px)' }}
      />
      <div
        className="absolute -bottom-48 -right-48 w-[680px] h-[680px] rounded-full pointer-events-none"
        style={{ background: 'radial-gradient(circle, var(--color-primary) 0%, transparent 65%)', opacity: 0.18, filter: 'blur(40px)' }}
      />
      {/* 顶栏字标 */}
      <div className="absolute top-6 left-8">
        <span className="font-['Orbitron'] tracking-[0.4em] text-sm font-black"
          style={{ color: 'var(--color-primary)', textShadow: '0 0 10px var(--color-primary)' }}>
          CYBER//STREAM
        </span>
      </div>
      {/* 玻璃卡占位 */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div
          className="w-[min(440px,92vw)] h-[480px] rounded-3xl border"
          style={{
            background: 'linear-gradient(180deg, rgba(20,20,30,0.78) 0%, rgba(10,10,18,0.88) 100%)',
            borderColor: 'rgba(255,255,255,0.08)',
            boxShadow: '0 30px 80px -20px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.04) inset, 0 0 60px -10px var(--color-primary)',
            backdropFilter: 'blur(18px) saturate(1.2)',
            WebkitBackdropFilter: 'blur(18px) saturate(1.2)',
          }}
        />
      </div>
    </div>
  );
};
