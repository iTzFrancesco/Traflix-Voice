import type { DesktopUpdateNotice as DesktopUpdateNoticeInfo } from "./useDesktopUpdater";

interface DesktopUpdateNoticeProps {
  update: DesktopUpdateNoticeInfo | null;
  isBusy: boolean;
  onRetry: () => void;
  onDownload: () => void;
  onInstall: () => void;
  onDismiss: () => void;
}

export default function DesktopUpdateNotice({
  update,
  isBusy,
  onRetry,
  onDownload,
  onInstall,
  onDismiss,
}: DesktopUpdateNoticeProps) {
  if (!update) return null;

  const percentage =
    update.contentLength && update.contentLength > 0
      ? Math.min(100, Math.round((update.downloadedBytes / update.contentLength) * 100))
      : null;
  const statusMessage = {
    available: isBusy
      ? "Aggiornamento disponibile. Puoi continuare a dettare e scegliere quando scaricarlo."
      : "Aggiornamento disponibile. Il download parte solo quando lo scegli.",
    downloading:
      percentage === null
        ? "Download dell’aggiornamento in corso…"
        : `Download dell’aggiornamento in corso… ${percentage}%`,
    ready: isBusy
      ? "Download completato. L’installazione è in attesa che termini la dettatura."
      : "Download completato. Installa e riavvia quando preferisci.",
    installing: "Installazione e riavvio di Traflix Voice…",
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
      </div>
      {update.state === "downloading" && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-[var(--primary-orange)] transition-[width] duration-200"
            style={{ width: `${percentage ?? 8}%` }}
          />
        </div>
      )}
      {(update.state === "available" || update.state === "ready" || update.state === "error") && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {update.state === "available" && (
            <button
              type="button"
              className="rounded-lg bg-[var(--primary-orange)] px-3 py-1.5 text-xs font-semibold text-black hover:brightness-110"
              onClick={onDownload}
            >
              Scarica aggiornamento
            </button>
          )}
          {update.state === "ready" && (
            <button
              type="button"
              className="rounded-lg bg-[var(--primary-orange)] px-3 py-1.5 text-xs font-semibold text-black enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={onInstall}
              disabled={isBusy}
            >
              {isBusy ? "Attendi la fine della dettatura" : "Installa e riavvia"}
            </button>
          )}
          {update.state === "error" && (
            <button
              type="button"
              className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold hover:bg-white/10"
              onClick={onRetry}
            >
              Riprova
            </button>
          )}
          <button
            type="button"
            className="rounded-lg border border-white/20 px-3 py-1.5 text-xs font-semibold text-white/75 hover:bg-white/10"
            onClick={onDismiss}
          >
            Più tardi
          </button>
        </div>
      )}
    </section>
  );
}
