import type { AppSettings, AppStats, GroqUsage, Provider } from "../types";
import { WHISPER_MODELS } from "../types";
import Oscilloscope from "./Oscilloscope";

interface HomeTabProps {
  stats: AppStats;
  settings: AppSettings | null;
  selectedProvider: Provider;
  selectedModel: string;
  transcriptionStatus: string;
  groqUsage: GroqUsage | null;
  currentVolume: number;
  activeTranscription: boolean;
  transcriptionText: string;
  onStartTranscription: () => void;
  onStopTranscription: () => void;
  onClearText: () => void;
}

function formatTime(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

const STATUS_ICONS: Record<string, string> = {
  starting: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg> Avvio motore vocale...`,
  loading_model: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg> Caricamento modello...`,
  listening: `<svg class="status-icon status-icon--pulse" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg> Registrazione in corso...`,
  processing: `<svg class="status-icon status-icon--spin" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Elaborazione...`,
  ready: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg> Pronto`,
  result: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg> Pronto`,
  error: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Errore`,
  rate_limit: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> Limite Raggiunto`,
};

export default function HomeTab({
  stats,
  settings,
  selectedProvider,
  selectedModel,
  transcriptionStatus,
  groqUsage,
  currentVolume,
  activeTranscription,
  transcriptionText,
  onStartTranscription,
  onStopTranscription,
  onClearText,
}: HomeTabProps) {
  const modelName =
    selectedProvider === "cloud"
      ? "Whisper Large V3 Turbo (Cloud)"
      : `Whisper ${WHISPER_MODELS.find((m) => m.id === selectedModel)?.name || selectedModel}`;

  const statusHtml = STATUS_ICONS[transcriptionStatus] || (
    `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:1.25em;height:1.25em;vertical-align:-0.15em;flex-shrink:0;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg> Caricamento...`
  );

  const dailySecs = groqUsage?.audio_seconds || 0;
  const hourlySecs = groqUsage?.audio_seconds_hourly || 0;
  const dailyPct = Math.min(100, (dailySecs / 28800) * 100);
  const hourlyPct = Math.min(100, (hourlySecs / 7200) * 100);

  return (
    <div className="tab-slide-in">
      <header className="flex justify-between items-center mb-10">
        <h1
          className="m-0 text-[2rem] font-extrabold tracking-[-1px]"
          style={{
            background: "linear-gradient(135deg, #ff4444 0%, #ff8c00 100%)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}
        >
          Dashboard
        </h1>
      </header>

      {/* Stats Grid */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(130px,1fr))] gap-4 mb-8">
        <div className="bg-[rgba(26,26,26,0.85)] p-5 rounded-[20px] border border-[rgba(255,255,255,0.08)] flex flex-col gap-[5px]"
          style={{ borderColor: "rgba(255,140,0,0.3)", boxShadow: "0 8px 25px rgba(255,140,0,0.1)" }}>
          <span className="text-[0.75rem] text-[#888] font-semibold">Parole Trascritte</span>
          <span className="text-[1.8rem] font-extrabold text-[var(--primary-orange)]">
            {stats.total_words}
          </span>
        </div>
        <div className="bg-[rgba(26,26,26,0.85)] p-5 rounded-[20px] border border-[rgba(255,255,255,0.08)] flex flex-col gap-[5px]">
          <span className="text-[0.75rem] text-[#888] font-semibold">WPM Media</span>
          <span className="text-[1.8rem] font-extrabold text-[var(--primary-orange)]">
            {stats.avg_wpm}
          </span>
        </div>
        <div className="bg-[rgba(26,26,26,0.85)] p-5 rounded-[20px] border border-[rgba(255,255,255,0.08)] flex flex-col gap-[5px]">
          <span className="text-[0.75rem] text-[#888] font-semibold">Tempo Attivo</span>
          <span className="text-[1.8rem] font-extrabold text-[var(--primary-orange)]">
            {formatTime(stats.total_time)}
          </span>
        </div>
      </div>

      {/* Stato Attuale */}
      <div className="bg-[rgba(34,34,34,0.6)] p-6 rounded-[20px] border border-[rgba(255,255,255,0.08)] mb-6">
        <h2 className="text-[#eee] text-[1.4rem] font-bold m-0 mb-4"
          style={{
            background: "linear-gradient(135deg, #ff4444 0%, #ff8c00 100%)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>
          Stato Attuale
        </h2>
        <p className="text-[#666] text-[0.95rem] m-0 mb-2">
          Combinazione attiva:{" "}
          <strong style={{ color: "var(--primary-orange)" }}>
            {settings?.hotkey || "Caricamento..."}
          </strong>
        </p>
        <p className="text-[#666] text-[0.95rem] m-0 mb-2">
          Modello in uso: <strong className="text-[#ccc]">{modelName}</strong>
        </p>
        <p className="text-[#666] text-[0.95rem] m-0">
          Stato motore:{" "}
          <strong
            className="inline-flex items-center gap-1"
            dangerouslySetInnerHTML={{ __html: statusHtml }}
          />
        </p>
      </div>

      {/* Cloud Usage Dashboard */}
      {selectedProvider === "cloud" && (
        <div className="bg-[rgba(34,34,34,0.6)] p-6 rounded-[20px] border border-[rgba(255,255,255,0.08)] mb-6">
          <div className="flex items-center gap-2 mb-4">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4fc3f7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2v8"></path><path d="m16 6-4 4-4-4"></path><path d="M12 18v4"></path><path d="m8 18 4-4 4 4"></path><path d="M2 12h8"></path><path d="m6 8 4 4-4 4"></path><path d="M22 12h-8"></path><path d="m18 16 4-4-4-4"></path>
            </svg>
            <h2 className="m-0 text-[1.4rem] font-bold"
              style={{
                background: "linear-gradient(135deg, #ff4444 0%, #ff8c00 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}>
              Utilizzo Cloud
            </h2>
          </div>
          <div className="flex gap-6 flex-wrap">
            <div className="flex-1 min-w-[160px] bg-[rgba(79,195,247,0.04)] border border-[rgba(79,195,247,0.12)] rounded-[14px] p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-[0.72rem] font-bold text-[#888] uppercase tracking-[0.04em]">Giornaliero</span>
                <span className="text-[0.85rem] font-bold text-[#4fc3f7]">{Math.round(dailySecs)} / 28,800s</span>
              </div>
              <div className="bg-[#222] h-1.5 rounded-[4px] overflow-hidden">
                <div className="h-full rounded-[4px] transition-[width] duration-300" style={{ width: `${dailyPct}%`, background: "#4fc3f7" }} />
              </div>
            </div>
            <div className="flex-1 min-w-[160px] bg-[rgba(255,140,0,0.04)] border border-[rgba(255,140,0,0.12)] rounded-[14px] p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="text-[0.72rem] font-bold text-[#888] uppercase tracking-[0.04em]">Orario</span>
                <span className="text-[0.85rem] font-bold text-[var(--primary-orange)]">{Math.round(hourlySecs)} / 7,200s</span>
              </div>
              <div className="bg-[#222] h-1.5 rounded-[4px] overflow-hidden">
                <div className="h-full rounded-[4px] transition-[width] duration-300" style={{ width: `${hourlyPct}%`, background: "var(--primary-orange)" }} />
              </div>
              <div className="text-[0.6rem] text-[#555] mt-1.5">Reset {groqUsage?.hourly_reset || "--:--"}</div>
            </div>
          </div>
        </div>
      )}

      {/* Transcription Workspace */}
      <div className="bg-[rgba(26,26,26,0.85)] border border-[rgba(255,255,255,0.08)] rounded-[20px] p-5 mb-6 flex flex-col gap-4 shadow-[0_10px_40px_rgba(0,0,0,0.3)]">
        <Oscilloscope currentVolume={currentVolume} />

        <div className="flex-1 h-[200px]">
          <textarea
            id="transcription-box"
            className="w-full h-full bg-[rgba(0,0,0,0.2)] border border-[rgba(255,255,255,0.08)] rounded-xl p-4 text-[#eee] text-[0.95rem] leading-[1.5] resize-none outline-none transition-[border-color] duration-300 cursor-pointer"
            style={{ fontFamily: "inherit" }}
            readOnly
            value={transcriptionText}
            placeholder="Clicca qui per registrare una trascrizione di test..."
            aria-label="Testo trascritto"
            onClick={(e) => {
              const ta = e.currentTarget;
              ta.select();
              navigator.clipboard.writeText(ta.value).catch(() => {});
            }}
          />
        </div>

        <div className="flex gap-3">
          <button
            id="start-rec-main"
            className={`flex-1 border-none text-white py-3.5 rounded-xl font-extrabold flex items-center justify-center gap-2.5 transition-all duration-200 cursor-pointer ${
              activeTranscription
                ? "animate-[pulseRec_1.4s_ease-in-out_infinite]"
                : ""
            }`}
            style={{
              background: activeTranscription
                ? "linear-gradient(135deg, #ff2222 10%, #cc0000 100%)"
                : "linear-gradient(135deg, var(--primary-orange) 10%, #ff4444 100%)",
              boxShadow: activeTranscription
                ? "0 4px 20px rgba(255, 34, 34, 0.45)"
                : "0 4px 15px rgba(255,140,0,0.3)",
            }}
            onClick={activeTranscription ? onStopTranscription : onStartTranscription}
          >
            {activeTranscription ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" x2="12" y1="19" y2="22" />
              </svg>
            )}
            <span>{activeTranscription ? "Ferma" : "Trascrivi Ora"}</span>
          </button>

          <button
            id="clear-text-btn"
            className="px-4 bg-[rgba(255,255,255,0.05)] border border-[rgba(255,255,255,0.08)] text-[#888] rounded-xl flex items-center justify-center cursor-pointer transition-all duration-200 hover:bg-[rgba(255,255,255,0.1)] hover:text-[#eee]"
            title="Pulisci"
            onClick={onClearText}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
