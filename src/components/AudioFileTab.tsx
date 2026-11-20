import { useRef, useState } from "react";
import type { AudioFileStatus, AudioFileTranscript } from "../hooks/useAudioFileTranscription";

interface AudioFileTabProps {
  file: File | null;
  status: AudioFileStatus;
  result: AudioFileTranscript | null;
  error: string;
  onSelectFile: (file: File) => void;
  onClearFile: () => void;
  onTranscribe: () => void;
}

const ACCEPTED_TYPES = "audio/*,.ogg,.opus,.mp3,.wav,.m4a,.aac,.flac,.webm";
const AUDIO_EXTENSION = /\.(ogg|opus|mp3|wav|m4a|aac|flac|webm)$/i;

function isAudioFile(file: File): boolean {
  return file.type.startsWith("audio/") || AUDIO_EXTENSION.test(file.name);
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function AudioFileTab({
  file,
  status,
  result,
  error,
  onSelectFile,
  onClearFile,
  onTranscribe,
}: AudioFileTabProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const dragDepthRef = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const [dropError, setDropError] = useState("");

  const busy = status === "decoding" || status === "transcribing" || status === "saving";

  const chooseFile = (selected: File | undefined) => {
    if (!selected || busy) return;
    if (!isAudioFile(selected)) {
      setDropError("Scegli un file audio (MP3, WAV, OGG…).");
      return;
    }
    setDropError("");
    setCopied(false);
    onSelectFile(selected);
  };

  const copyResult = async () => {
    if (!result?.text) return;
    try {
      await navigator.clipboard.writeText(result.text);
      setCopied(true);
      setCopyError("");
    } catch {
      setCopied(false);
      setCopyError("Copia non riuscita.");
    }
  };

  const liveMessage = error
    ? error
    : dropError || copyError
      ? dropError || copyError
      : status === "decoding"
        ? "Apro l'audio…"
        : status === "transcribing"
          ? "Trascrizione locale in corso…"
          : status === "saving"
            ? "Salvataggio in Cronologia…"
            : status === "done" && result
              ? result.text ? "Trascrizione completata." : result.notice
              : "";

  const saveLabel = status === "saving"
    ? "Salvataggio…"
    : result?.savedInHistory
      ? "in Cronologia"
      : "salvataggio non riuscito";

  return (
    <div className="tab-slide-in max-w-[640px] mx-auto w-full">
      <p id="audio-file-live" className="sr-only" role="status" aria-live="polite" aria-atomic="true">{liveMessage}</p>

      <header className="mb-6">
        <h1 className="page-title m-0">Trascrivi audio</h1>
        <p className="m-0 mt-2 text-[.82rem] text-[var(--muted)]">
          Il vocaletto resta sul dispositivo. Nessun invio a servizi online.
        </p>
      </header>

      <input
        ref={inputRef}
        id="audio-file-input"
        type="file"
        accept={ACCEPTED_TYPES}
        hidden
        disabled={busy}
        onChange={(event) => chooseFile(event.target.files?.[0])}
      />

      <div
        id="audio-file-drop"
        role="button"
        tabIndex={busy ? -1 : 0}
        aria-label={file ? `Audio selezionato: ${file.name}. Scegli un altro audio` : "Scegli un file audio"}
        aria-disabled={busy}
        onClick={() => { if (!busy) inputRef.current?.click(); }}
        onKeyDown={(event) => {
          if (busy) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(event) => {
          event.preventDefault();
          if (busy) return;
          dragDepthRef.current += 1;
          setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => {
          event.preventDefault();
          dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
          if (dragDepthRef.current === 0) setDragging(false);
        }}
        onDrop={(event) => {
          event.preventDefault();
          dragDepthRef.current = 0;
          setDragging(false);
          chooseFile(event.dataTransfer.files?.[0]);
        }}
        className={`flex min-h-[132px] cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-5 py-6 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${dragging ? "border-[var(--accent)] bg-[rgba(255,157,36,.06)]" : "border-white/[.14] bg-white/[.025] hover:border-[var(--accent)]/60"} ${busy ? "cursor-not-allowed opacity-60" : ""}`}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 text-[var(--accent)]" aria-hidden="true">
          <path d="M12 16V4" /><path d="m7 9 5-5 5 5" /><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
        </svg>
        {file ? (
          <>
            <strong className="max-w-full truncate text-[.85rem] text-[var(--ink)]">{file.name}</strong>
            <small className="text-[.7rem] text-[var(--muted)]">{formatSize(file.size)} · scegli un altro audio</small>
          </>
        ) : (
          <>
            <strong className="text-[.85rem] text-[var(--ink)]">Trascina un audio qui</strong>
            <small className="text-[.7rem] text-[var(--muted)]">oppure clicca per sceglierlo · MP3, WAV, OGG · max 10 min</small>
          </>
        )}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          id="audio-file-transcribe"
          type="button"
          onClick={onTranscribe}
          disabled={!file || busy}
          aria-busy={busy}
          className="rounded-xl border border-[var(--accent)]/40 bg-[rgba(255,157,36,.14)] px-5 py-2.5 text-[.75rem] font-bold text-[var(--accent)] cursor-pointer transition-colors hover:bg-[rgba(255,157,36,.22)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {status === "decoding" ? "Apro l'audio…" : busy ? "Trascrizione…" : "Trascrivi"}
        </button>
        {file && !busy && (
          <button
            type="button"
            onClick={() => { onClearFile(); document.getElementById("audio-file-drop")?.focus(); }}
            className="text-[.72rem] font-bold text-[var(--muted)] cursor-pointer underline underline-offset-4 hover:text-[var(--ink)]"
          >
            Rimuovi
          </button>
        )}
      </div>

      {(dropError || error) && (
        <p className="mt-3 text-[.76rem] text-[#ff9a9d]" role="alert">{dropError || error}</p>
      )}

      {result && (
        <section className="panel p-5 mt-5" aria-labelledby="audio-file-result-title">
          <div className="flex items-center justify-between gap-3">
            <h2 id="audio-file-result-title" className="m-0 text-[.9rem] font-bold text-[var(--ink)]">Trascrizione</h2>
            <span className="text-[.64rem] font-bold text-[var(--muted)]">Parakeet Ultra</span>
          </div>
          {result.text ? (
            <>
              <p className="mt-4 whitespace-pre-wrap break-words text-[.86rem] leading-7 text-[#d3d0c9]">{result.text}</p>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-white/[.07] pt-3">
                <span className="text-[.7rem] text-[var(--muted)]">
                  {result.text.split(/\s+/).filter(Boolean).length} parole · {saveLabel}
                </span>
                <button
                  type="button"
                  onClick={() => void copyResult()}
                  className="rounded-lg border border-white/[.1] bg-white/[.03] px-3 py-2 text-[.7rem] font-bold text-[var(--muted)] cursor-pointer transition-colors hover:text-[var(--ink)]"
                >
                  {copied ? "Copiato" : "Copia"}
                </button>
              </div>
              {copyError && <p className="mt-2 text-[.72rem] text-[#ff9a9d]" role="alert">{copyError}</p>}
            </>
          ) : (
            <p className="mt-4 text-[.8rem] text-[var(--muted)]">{result.notice}</p>
          )}
        </section>
      )}

      <p className="mt-5 text-[.7rem] text-[var(--muted)]">Il modello locale viene rilasciato dalla memoria al termine.</p>
    </div>
  );
}
