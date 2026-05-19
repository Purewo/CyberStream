import React from 'react';

export const FilterTag: React.FC<{ label: string; active: boolean; onClick: () => void }> = ({ label, active, onClick }) => (
  <button onClick={onClick} className={`px-3 py-1 text-xs md:text-sm font-['Noto_Sans_SC'] transition-all duration-200 skew-x-[-10deg] border border-transparent ${active ? 'bg-primary text-black font-bold border-primary shadow-[0_0_10px_var(--color-primary)]' : 'text-gray-400 hover:text-primary hover:border-primary/30 hover:bg-primary/5'}`} > 
    <div className="skew-x-[10deg]">{label}</div> 
  </button>
);

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