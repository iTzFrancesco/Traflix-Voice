import type { WhisperModel, Provider, GroqUsage } from "../types";
import ModelCard from "./ModelCard";

interface IATabProps {
  models: WhisperModel[];
  selectedModel: string;
  selectedProvider: Provider;
  modelStatus: Record<string, { downloaded: boolean; loading: boolean }>;
  groqUsage: GroqUsage | null;
  onProviderToggle: (provider: Provider) => void;
  onModelAction: (modelId: string) => void;
}

export default function IATab({
  models,
  selectedModel,
  selectedProvider,
  modelStatus,
  groqUsage,
  onProviderToggle,
  onModelAction,
}: IATabProps) {
  const dailySecs = groqUsage?.audio_seconds || 0;
  const hourlySecs = groqUsage?.audio_seconds_hourly || 0;
  const dailyPct = Math.min(100, (dailySecs / 28800) * 100);
  const hourlyPct = Math.min(100, (hourlySecs / 7200) * 100);

  return (
    <div className="tab-slide-in">
      <h2 className="text-[#eee] text-[1.4rem] font-bold m-0 mb-4"
        style={{
          background: "linear-gradient(135deg, #ff4444 0%, #ff8c00 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}>
        Modelli Whisper
      </h2>
      <p className="text-[#666] text-[0.95rem] m-0 mb-3">
        Scegli il modello in base alla precisione che vuoi ottenere.
      </p>

      {/* Provider Toggle */}
      <div className="bg-[rgba(34,34,34,0.6)] p-5 rounded-[20px] border border-[rgba(255,255,255,0.08)] mb-4">
        <div className="flex flex-row justify-between items-center mb-0">
          <div className="flex-1 min-w-0 mr-4">
            <label className="text-[0.9rem] font-bold text-[#ccc] block mb-1">
              Provider Cloud
            </label>
            <p className="text-[0.95rem] text-[#666] m-0">
              Usa Groq Cloud (whisper-large-v3-turbo, 216x real-time) per la trascrizione.
            </p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer flex-shrink-0">
            <input
              type="checkbox"
              className="sr-only peer"
              checked={selectedProvider === "cloud"}
              onChange={() =>
                onProviderToggle(selectedProvider === "cloud" ? "local" : "cloud")
              }
              aria-label="Attiva provider Cloud"
            />
            <div className={`
              w-11 h-6 rounded-full transition-colors duration-300
              ${selectedProvider === "cloud" ? "bg-[var(--primary-orange)]" : "bg-[#333]"}
              after:content-[''] after:absolute after:top-[3px] after:left-[3px]
              after:bg-white after:rounded-full after:h-[18px] after:w-[18px]
              after:transition-transform after:duration-300
              ${selectedProvider === "cloud" ? "after:translate-x-5" : "after:translate-x-0"}
            `} />
          </label>
        </div>

        {/* Cloud usage dashboard (inside provider area) */}
        {selectedProvider === "cloud" && (
          <div className="mt-3 pt-3 border-t border-[rgba(255,255,255,0.08)]">
            <div className="flex gap-4 flex-wrap">
              <div className="flex-1 min-w-[140px]">
                <div className="flex justify-between items-center mb-1.5">
                  <span className="text-[0.65rem] font-bold text-[#888] uppercase tracking-[0.04em]">Giornaliero</span>
                  <span className="text-[0.78rem] font-bold text-[#4fc3f7]">{Math.round(dailySecs)} / 28,800s</span>
                </div>
                <div className="bg-[#222] h-1 rounded-[4px] overflow-hidden">
                  <div className="h-full rounded-[4px]" style={{ width: `${dailyPct}%`, background: "#4fc3f7" }} />
                </div>
              </div>
              <div className="flex-1 min-w-[140px]">
                <div className="flex justify-between items-center mb-1.5">
                  <span className="text-[0.65rem] font-bold text-[#888] uppercase tracking-[0.04em]">Orario</span>
                  <span className="text-[0.78rem] font-bold text-[var(--primary-orange)]">{Math.round(hourlySecs)} / 7,200s</span>
                </div>
                <div className="bg-[#222] h-1 rounded-[4px] overflow-hidden">
                  <div className="h-full rounded-[4px]" style={{ width: `${hourlyPct}%`, background: "var(--primary-orange)" }} />
                </div>
                <div className="text-[0.6rem] text-[#555] mt-1">Reset {groqUsage?.hourly_reset || "--:--"}</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Cloud card */}
      {selectedProvider === "cloud" && (
        <div className="bg-[rgba(34,34,34,0.6)] p-4 rounded-2xl border border-[var(--primary-orange)] bg-[rgba(255,140,0,0.06)] shadow-[0_4px_20px_rgba(255,140,0,0.1)] flex flex-col gap-3 mb-3">
          <div className="flex-1 min-w-0">
            <div className="flex justify-between items-start mb-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="m-0 text-[0.95rem] font-bold text-[#eee]">Whisper Large V3 Turbo</h3>
                <span className="text-[0.62rem] font-bold px-[7px] py-[2px] rounded-full whitespace-nowrap bg-[rgba(79,195,247,0.15)] text-[#4fc3f7] border border-[rgba(79,195,247,0.3)]">Cloud</span>
              </div>
              <div className="flex flex-col items-end gap-[2px]">
                <span className="text-[0.72rem] text-[#555] font-semibold whitespace-nowrap">~3 GB (remoto)</span>
                <span className="text-[0.65rem] text-[#444] whitespace-nowrap">0 GB RAM locale</span>
              </div>
            </div>
            <p className="m-0 mb-2.5 text-[0.75rem] text-[#666] leading-[1.45]">Massima precisione su Groq LPU. 216x real-time — trascrive 1 minuto di audio in ~0.3 secondi. Supporto multilingua incluso italiano. Nessun download richiesto.</p>
            <div className="flex gap-5">
              <div className="flex items-center gap-1.5">
                <span className="text-[0.65rem] text-[#555] font-bold uppercase tracking-[0.04em] whitespace-nowrap">Velocità</span>
                <div className="flex gap-1 items-center">{renderDots(5, 5, "var(--primary-orange)")}</div>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[0.65rem] text-[#555] font-bold uppercase tracking-[0.04em] whitespace-nowrap">Precisione</span>
                <div className="flex gap-1 items-center">{renderDots(5, 5, "#4fc3f7")}</div>
              </div>
            </div>
          </div>
          <button className="w-full text-center py-2 px-4 rounded-xl border font-bold text-[0.78rem] bg-[rgba(34,197,94,0.1)] text-[#22c55e] border-[rgba(34,197,94,0.3)] cursor-default flex items-center justify-center gap-2">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            Attivo
          </button>
        </div>
      )}

      {/* Local models */}
      {selectedProvider !== "cloud" && (
        <div className="grid grid-cols-1 gap-[0.7rem]">
          {models.map((model) => {
            const status = modelStatus[model.id] || { downloaded: false, loading: false };
            return (
              <ModelCard
                key={model.id}
                model={model}
                isActive={model.id === selectedModel}
                isDownloaded={status.downloaded}
                isLoading={status.loading}
                onAction={onModelAction}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function renderDots(filled: number, total: number, color: string) {
  return Array.from({ length: total }, (_, i) => (
    <span
      key={i}
      className={`w-2 h-2 rounded-full ${
        i < filled ? "" : "bg-[#2a2a2a]"
      }`}
      style={
        i < filled
          ? {
              background: color,
              boxShadow: `0 0 6px ${color}80`,
              border: "1px solid transparent",
            }
          : { border: "1px solid #333" }
      }
    />
  ));
}
