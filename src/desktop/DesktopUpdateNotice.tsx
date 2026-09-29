import type { DesktopUpdateNotice as DesktopUpdateNoticeInfo } from "./useDesktopUpdater";

interface DesktopUpdateNoticeProps {
  update: DesktopUpdateNoticeInfo | null;
  isBusy: boolean;
  onRetry: () => void;
}

export default function DesktopUpdateNotice({
  update,
  isBusy,
  onRetry,
}: DesktopUpdateNoticeProps) {
  if (!update) return null;

  const percentage =
    update.contentLength && update.contentLength > 0
      ? Math.min(100, Math.round((update.downloadedBytes / update.contentLength) * 100))
      : null;
  const statusMessage = {
    available: isBusy
      ? "La dettatura è in corso: il download partirà appena termina."
      : "Download automatico in avvio…",
    downloading:
      percentage === null
        ? "Download dell’aggiornamento in corso…"
        : `Download dell’aggiornamento in corso… ${percentage}%`,
    ready: isBusy
      ? "Download completato. L’installazione partirà al termine della dettatura."
      : "Download completato. Avvio dell’installazione…",
    installing: "Installazione automatica e riavvio di Traflix Voice…",
    error: `Aggiornamento non riuscito: ${update.error}`,
  }[update.state];

  return (
    <section
      className="mb-4 rounded-xl border px-4 py-3 text-sm"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      style={{
        background: "linear-gradient(145deg, rgba(49,38,25,.96), rgba(28,27,23,.94))",
        borderColor: "rgba(255,140,0,.36)",
        color: "#f6f6f6",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold">Nuovo aggiornamento PC · v{update.version}</p>
          <p className="mt-1 text-xs leading-relaxed text-white/75">{statusMessage}</p>
          {update.notes && update.state !== "error" && (
            <p className="mt-2 text-xs leading-relaxed text-white/60">{update.notes}</p>
          )}
        </div>
        {update.state === "error" && (
          <button
            type="button"
            className="shrink-0 rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold hover:bg-white/10"
            onClick={onRetry}
          >
            Riprova
          </button>
        )}
      </div>
      {update.state === "downloading" && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-[var(--primary-orange)] transition-[width] duration-200"
            style={{ width: `${percentage ?? 8}%` }}
          />
        </div>
      )}
    </section>
  );
}
