import React, { useEffect, useState } from 'react';
import { CheckCircle, AlertTriangle, Info, XOctagon } from 'lucide-react';
import { ToastType } from '../../utils';

interface ToastData {
  id: number;
  message: string;
  type: ToastType;
}

export const Toaster = () => {
  const [toasts, setToasts] = useState<ToastData[]>([]);

  useEffect(() => {
    const handleToast = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const id = Date.now() + Math.random();
      setToasts(prev => [...prev, { id, message: detail.message, type: detail.type }]);
      
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, detail.duration || 3000);
    };

    window.addEventListener('cyber:toast', handleToast);
    return () => window.removeEventListener('cyber:toast', handleToast);
  }, []);

  if (toasts.length === 0) return null;

  const getIcon = (type: ToastType) => {
    switch (type) {
      case 'success': return <CheckCircle className="text-green-500" size={18} />;
      case 'error': return <XOctagon className="text-red-500" size={18} />;
      case 'warning': return <AlertTriangle className="text-yellow-500" size={18} />;
      case 'info':
      default: return <Info className="text-primary" size={18} />;
    }
  };

  const getBgClass = (type: ToastType) => {
    switch (type) {
      case 'success': return 'border-green-500/50 bg-green-500/10';
      case 'error': return 'border-red-500/50 bg-red-500/10';
      case 'warning': return 'border-yellow-500/50 bg-yellow-500/10';
      case 'info':
      default: return 'border-primary-50 bg-primary-10';
    }
  };

  return (
    <div className="fixed top-20 right-6 z-[100] flex flex-col gap-3 pointer-events-none">
      {toasts.map(t => (
        <div 
          key={t.id} 
          className={`flex items-center gap-3 px-4 py-3 border backdrop-blur-md font-mono text-white shadow-xl animate-in slide-in-from-right-10 fade-in duration-300 min-w-[280px] pointer-events-auto ${getBgClass(t.type)}`}
        >
          {getIcon(t.type)}
          <span className="text-sm tracking-wide">{t.message}</span>
        </div>
      ))}
    </div>
  );
};
