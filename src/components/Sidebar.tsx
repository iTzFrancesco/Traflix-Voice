import { useCallback } from "react";

const IS_DEV = import.meta.env.DEV;

interface SidebarProps {
  activeTab: string;
  onTabChange: (tab: string) => void;
}

const tabs = [
  {
    id: "home",
    label: "Home",
    svg: '<rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect>',
  },
  {
    id: "ia",
    label: "IA",
    svg: '<path d="M12 2v8"></path><path d="m16 6-4 4-4-4"></path><path d="M12 18v4"></path><path d="m8 18 4-4 4 4"></path><path d="M2 12h8"></path><path d="m6 8 4 4-4 4"></path><path d="M22 12h-8"></path><path d="m18 16 4-4-4-4"></path>',
  },
  {
    id: "tasti",
    label: "Tasti",
    svg: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 8h.01"/><path d="M10 8h.01"/><path d="M14 8h.01"/><path d="M18 8h.01"/><path d="M6 12h.01"/><path d="M10 12h.01"/><path d="M14 12h.01"/><path d="M18 12h.01"/><path d="M7 16h10"/>',
  },
  {
    id: "cronologia",
    label: "Cronologia",
    svg: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  },
  {
    id: "sistema",
    label: "Sistema",
    svg: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  },
];

export default function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, tabId: string) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onTabChange(tabId);
      }
    },
    [onTabChange]
  );

  return (
    <nav
      className="w-[56px] bg-[rgba(15,15,15,0.8)] backdrop-blur-[30px] border-r border-[rgba(255,255,255,0.08)] flex flex-col items-center flex-shrink-0"
      role="navigation"
      aria-label="Menu principale"
    >
      <div className="py-6 px-2 flex justify-center items-center relative">
        <img
          src="/assets/logo.png"
          alt="Traflix Logo"
          className="w-10 h-10 object-contain"
          style={{ filter: "drop-shadow(0 0 10px rgba(255, 68, 68, 0.2))" }}
        />
        {IS_DEV && (
          <div className="absolute top-1 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.8)]" />
        )}
      </div>

      <ul className="list-none p-0 m-0 flex flex-col gap-4 flex-1 w-full" role="tablist">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <li
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={tab.id}
              tabIndex={isActive ? 0 : -1}
              className={`
                flex flex-col items-center justify-center cursor-pointer
                transition-all duration-250 ease-[cubic-bezier(0.4,0,0.2,1)]
                relative py-2.5 w-full
                ${isActive ? "text-[var(--primary-orange)]" : "text-[#777]"}
              `}
              onClick={() => onTabChange(tab.id)}
              onKeyDown={(e) => handleKeyDown(e, tab.id)}
            >
              <div
                className={`w-6 h-6 flex items-center justify-center transition-transform duration-300 ${
                  isActive ? "scale-110" : ""
                }`}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="w-full h-full"
                  aria-hidden="true"
                  dangerouslySetInnerHTML={{ __html: tab.svg }}
                />
              </div>

              {isActive && (
                <div
                  className="absolute right-[-1px] top-[25%] h-1/2 w-[4px] rounded-l-md"
                  style={{
                    background: "var(--primary-orange)",
                    boxShadow: "-2px 0 10px var(--primary-orange)",
                  }}
                />
              )}
            </li>
          );
        })}
      </ul>

      {IS_DEV && (
        <div className="pb-3 text-center">
          <span className="text-[0.5rem] font-bold tracking-[0.15em] text-red-500/70 uppercase">Dev</span>
        </div>
      )}
    </nav>
  );
}
