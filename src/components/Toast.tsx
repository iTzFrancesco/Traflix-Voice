import { useEffect } from "react";
import type { Toast as ToastType } from "../types";

interface ToastContainerProps {
  toasts: ToastType[];
  onRemove: (id: number) => void;
}

export default function ToastContainer({ toasts, onRemove }: ToastContainerProps) {
  return (
    <div
      className="fixed bottom-5 right-5 z-[2000] flex flex-col gap-2.5 pointer-events-none"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onRemove={onRemove} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onRemove }: { toast: ToastType; onRemove: (id: number) => void }) {
  useEffect(() => {
    const timer = setTimeout(() => {
      onRemove(toast.id);
    }, 3000);
    return () => clearTimeout(timer);
  }, [toast.id, onRemove]);

  const borderColor = {
    success: "rgba(34,197,94,0.3)",
    error: "rgba(239,68,68,0.3)",
    info: "rgba(255,140,0,0.3)",
  };

  const accentColor = {
    success: "#22c55e",
    error: "#ef4444",
    info: "var(--primary-orange)",
  };

  const iconSvg = (type: string) => {
    if (type === "success") return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="9 12 11 14 15 10" />
      </svg>
    );
    if (type === "error") return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="15" y1="9" x2="9" y2="15" />
        <line x1="9" y1="9" x2="15" y2="15" />
      </svg>
    );
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary-orange)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
    );
  };

  return (
    <div
      className="toast-surface backdrop-blur-[10px] rounded-xl px-4 py-3 min-w-[280px] max-w-[400px] text-[#f6f6f6] text-[0.85rem] font-semibold flex items-center gap-2.5 pointer-events-auto animate-[slideInRight_0.3s_cubic-bezier(0.16,1,0.3,1)] relative overflow-hidden"
      style={{ border: `1px solid ${borderColor[toast.type]}` }}
    >
      <div
        className="absolute left-0 top-0 w-[4px] h-full"
        style={{
          background: accentColor[toast.type],
          boxShadow: `0 0 10px ${accentColor[toast.type]}`,
        }}
      />
      <span className="flex-shrink-0">{iconSvg(toast.type)}</span>
      <span className="flex-1 leading-[1.4]">{toast.message}</span>
    </div>
  );
}
