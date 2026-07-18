import { useCallback } from "react";

const IS_DEV = import.meta.env.DEV;
interface SidebarProps { activeTab: string; onTabChange: (tab: string) => void; appVersion: string; }

const tabs = [
  { id: "home", label: "Console", short: "C", svg: '<rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect>' },
  { id: "ia", label: "Motore IA", short: "IA", svg: '<path d="M12 2v8"></path><path d="m16 6-4 4-4-4"></path><path d="M12 18v4"></path><path d="m8 18 4-4 4 4"></path><path d="M2 12h8"></path><path d="m6 8 4 4-4 4"></path><path d="M22 12h-8"></path><path d="m18 16 4-4-4-4"></path>' },
  { id: "tasti", label: "Scorciatoie", short: "⌘", svg: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M6 16h12"/>' },
  { id: "cronologia", label: "Cronologia", short: "H", svg: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>' },
  { id: "sistema", label: "Sistema", short: "S", svg: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09A1.65 1.65 0 0 0 19.4 15z"/>' },
];

export default function Sidebar({ activeTab, onTabChange, appVersion }: SidebarProps) {
  const handleKeyDown = useCallback((e: React.KeyboardEvent, index: number) => {
    const next = e.key === "ArrowDown" ? index + 1 : e.key === "ArrowUp" ? index - 1 : null;
    if (next !== null) {
      e.preventDefault();
      e.stopPropagation();
      const target = tabs[(next + tabs.length) % tabs.length];
      onTabChange(target.id);
      requestAnimationFrame(() => document.getElementById(`nav-tab-${target.id}`)?.focus());
    }
  }, [onTabChange]);
  return <nav className="w-[64px] bg-black/20 border-r border-white/[.08] flex flex-col items-center flex-shrink-0 py-4" aria-label="Menu principale">
    <div className="relative mb-7"><img src="/assets/logo.png" alt="Traflix Voice" className="w-9 h-9 object-contain" />{IS_DEV && <span className="absolute -right-1 -top-1 w-2 h-2 rounded-full bg-[#ff626b]" />}</div>
    <div className="flex flex-col gap-2 w-full px-2" role="tablist" aria-orientation="vertical">
      {tabs.map((tab, index) => { const active = activeTab === tab.id; return <button id={`nav-tab-${tab.id}`} key={tab.id} type="button" role="tab" aria-selected={active} aria-label={tab.label} title={tab.label} tabIndex={active ? 0 : -1} onClick={() => onTabChange(tab.id)} onKeyDown={(e) => handleKeyDown(e, index)} className={`group relative h-10 rounded-xl transition-all ${active ? "bg-[rgba(255,157,36,.13)] text-[var(--accent)]" : "text-[#8d8a85] hover:bg-white/[.055] hover:text-[#e4e0d9]"}`}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5 mx-auto" aria-hidden="true" dangerouslySetInnerHTML={{ __html: tab.svg }} />
        <span className="sr-only">{tab.label}</span>{active && <span className="absolute -left-2 top-3 h-4 w-[2px] rounded-r bg-[var(--accent)]" />}
      </button>; })}
    </div>
    <div className="mt-auto flex flex-col items-center gap-1.5"><span className={`rounded-md px-1.5 py-1 text-[.58rem] font-extrabold tracking-[.16em] ${IS_DEV ? "bg-[#ff626b]/15 text-[#ff626b] shadow-[0_0_12px_rgba(255,98,107,.18)]" : "text-[#77736d]"}`}>{IS_DEV ? "DEV" : "VOICE"}</span><span className="font-mono text-[.78rem] font-bold tracking-[-.05em] text-[#d7d2ca]">v{appVersion || "…"}</span></div>
  </nav>;
}
