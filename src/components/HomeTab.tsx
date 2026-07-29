import type { AppSettings, AppStats, GroqUsage, Provider } from "../types";
import { WHISPER_MODELS } from "../types";

interface HomeTabProps {
  stats: AppStats;
  settings: AppSettings | null;
  selectedProvider: Provider;
  selectedModel: string;
  transcriptionStatus: string;
  groqUsage: GroqUsage | null;
}

const statusMeta: Record<string, { label: string; tone: string }> = {
  starting: { label: "Avvio motore vocale", tone: "#ff9d24" },
  loading_model: { label: "Caricamento modello", tone: "#ff9d24" },
  listening: { label: "Registrazione in corso", tone: "#ff626b" },
  processing: { label: "Elaborazione trascrizione", tone: "#ff9d24" },
  transforming: { label: "Trasformazione testo", tone: "#ff9d24" },
  transformed: { label: "Pronto", tone: "#55d89b" },
  ready: { label: "Pronto", tone: "#55d89b" },
  result: { label: "Pronto", tone: "#55d89b" },
  error: { label: "Errore del motore", tone: "#ff626b" },
  rate_limit: { label: "Limite Cloud raggiunto", tone: "#ff9d24" },
};

function UsageMeter({ label, used, limit, color, footer }: { label: string; used: number; limit: number; color: string; footer?: string }) {
  const percent = Math.min(100, (used / limit) * 100);
  return <div className="panel-subtle p-3.5">
    <div className="flex items-center justify-between gap-2 mb-2"><span className="text-[.64rem] font-bold uppercase tracking-[.09em] text-[var(--quiet)]">{label}</span><span className="text-[.75rem] font-bold" style={{ color }}>{Math.round(used).toLocaleString("it-IT")} / {limit.toLocaleString("it-IT")}s</span></div>
    <div className="h-1.5 overflow-hidden rounded-full bg-black/30"><div className="h-full rounded-full transition-[width] duration-300" style={{ width: `${percent}%`, background: color }} /></div>
    {footer && <p className="m-0 mt-2 text-[.64rem] text-[var(--quiet)]">{footer}</p>}
  </div>;
}

export default function HomeTab({ stats, settings, selectedProvider, selectedModel, transcriptionStatus, groqUsage }: HomeTabProps) {
  const status = statusMeta[transcriptionStatus] ?? { label: "In preparazione", tone: "#ff9d24" };
  const modelName = selectedProvider === "cloud" ? "Whisper Large V3 Turbo (Cloud)" : `Whisper ${WHISPER_MODELS.find((m) => m.id === selectedModel)?.name ?? selectedModel}`;
  return <div className="tab-slide-in max-w-[700px] mx-auto w-full">
    <header className="mb-6"><p className="eyebrow m-0 mb-2">Traflix Voice / Dashboard</p><h1 className="page-title m-0">Panoramica</h1></header>

    <section className="panel p-5 mb-4" aria-label="Parole trascritte">
      <p className="m-0 font-mono text-[.68rem] font-bold uppercase tracking-[.13em] text-[var(--accent)]">Parole trascritte</p>
      <p className="m-0 mt-2 font-mono text-[2.6rem] leading-none tracking-[-.07em] font-bold text-[#f5f3ef]">{stats.total_words.toLocaleString("it-IT")}</p>
      <p className="m-0 mt-2 text-[.78rem] text-[var(--muted)]">Ritmo medio: <strong className="text-[var(--ink)]">{stats.avg_wpm} WPM</strong> · Tempo attivo: <strong className="text-[var(--ink)]">{stats.total_time < 60 ? `${Math.round(stats.total_time)} min` : `${(stats.total_time / 60).toFixed(1)} h`}</strong></p>
    </section>

    <section className="panel p-5 mb-4" aria-label="Stato attuale">
      <div className="flex items-center justify-between gap-3 mb-5"><div><p className="eyebrow m-0">Stato attuale</p><h2 className="m-0 mt-1 text-[1.15rem] tracking-[-.02em]">Configurazione attiva</h2></div><span className="inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-[.7rem] font-bold" style={{ color: status.tone, background: `${status.tone}18` }}><span className="w-1.5 h-1.5 rounded-full" style={{ background: status.tone }} />{status.label}</span></div>
      <dl className="m-0 grid gap-3"><div className="flex items-baseline justify-between gap-4 border-b border-white/[.07] pb-3"><dt className="text-[.76rem] text-[var(--muted)]">Scorciatoia attiva</dt><dd className="m-0 font-mono text-[.78rem] font-bold text-[var(--accent)]">{settings?.hotkey ?? "Caricamento…"}</dd></div><div className="flex items-baseline justify-between gap-4"><dt className="text-[.76rem] text-[var(--muted)]">Modello in uso</dt><dd className="m-0 text-right text-[.78rem] font-semibold text-[var(--ink)]">{modelName}</dd></div></dl>
    </section>

    {selectedProvider === "cloud" && <section className="panel p-5" aria-label="Utilizzo Cloud">
      <div className="mb-4"><p className="eyebrow m-0">Utilizzo Cloud</p><h2 className="m-0 mt-1 text-[1.15rem] tracking-[-.02em]">Quota Groq</h2></div>
      <div className="grid gap-3"><UsageMeter label="Giornaliero" used={groqUsage?.audio_seconds ?? 0} limit={28800} color="#55d89b" /><UsageMeter label="Orario" used={groqUsage?.audio_seconds_hourly ?? 0} limit={7200} color="var(--accent)" footer={`Reset ${groqUsage?.hourly_reset ?? "--:--"}`} /></div>
    </section>}
  </div>;
}
