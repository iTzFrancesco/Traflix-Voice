import type { TranscriptionEntry } from "../types";

interface CronologiaTabProps {
  entries: TranscriptionEntry[];
  onClear: () => void;
  onEntryClick: (text: string, index: number) => void;
}

export default function CronologiaTab({ entries, onClear, onEntryClick }: CronologiaTabProps) {
  return (
    <div className="tab-slide-in">
      <div className="flex justify-between items-center mb-2">
        <h2
          className="m-0 text-[1.4rem] font-bold"
          style={{
            background: "linear-gradient(135deg, #ff4444 0%, #ff8c00 100%)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}
        >
          Cronologia
        </h2>
        <button
          id="clear-history-btn"
          className="bg-[rgba(255,255,255,0.05)] border border-[rgba(255,255,255,0.08)] text-[#888] py-2 px-4 rounded-xl font-semibold text-[0.78rem] whitespace-nowrap cursor-pointer transition-all duration-200 hover:bg-[rgba(255,255,255,0.1)] hover:text-[#eee]"
          onClick={onClear}
        >
          Cancella Cronologia
        </button>
      </div>

      <p className="text-[#666] text-[0.95rem] m-0 mb-4">
        Clicca su una trascrizione per copiarla negli appunti.
      </p>

      <div
        id="history-list"
        className="flex flex-col gap-3 overflow-y-auto pr-1"
        style={{ maxHeight: "calc(100vh - 220px)" }}
        role="list"
        aria-label="Lista cronologia trascrizioni"
      >
        {entries.length === 0 ? (
          <p className="text-[#555] text-[0.85rem] text-center py-12 px-4">
            Nessuna trascrizione salvata.
          </p>
        ) : (
          entries.map((entry, i) => {
            const preview =
              entry.text.length > 120
                ? entry.text.substring(0, 120) + "..."
                : entry.text;
            return (
              <div
                key={`${entry.timestamp}-${i}`}
                className="bg-[rgba(34,34,34,0.6)] border border-[rgba(255,255,255,0.08)] rounded-[14px] p-4 cursor-pointer transition-all duration-200 hover:border-[rgba(255,140,0,0.3)] hover:bg-[rgba(34,34,34,0.85)] hover:-translate-y-px"
                data-index={i}
                title="Clicca per copiare"
                role="listitem"
                onClick={() => onEntryClick(entry.text, i)}
              >
                <div className="flex justify-between items-center mb-2">
                  <span className="text-[0.72rem] font-bold text-[var(--primary-orange)] tracking-[0.02em]">
                    {entry.timestamp}
                  </span>
                  {entry.word_count > 0 && (
                    <span className="text-[0.65rem] font-bold px-2 py-[2px] rounded-full bg-[rgba(255,140,0,0.12)] text-[var(--primary-orange)] border border-[rgba(255,140,0,0.25)]">
                      {entry.word_count} parole
                    </span>
                  )}
                </div>
                <p className="m-0 text-[0.82rem] text-[#aaa] leading-[1.5] break-words">
                  {preview}
                </p>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
