import { useRef, useState } from "react";
import type { AudioFileStatus, AudioFileTranscript } from "../hooks/useAudioFileTranscription";
import type { Provider } from "../types";

interface AudioFileTabProps {
  file: File | null;
  status: AudioFileStatus;
  result: AudioFileTranscript | null;
  error: string;
  provider: Provider;
  cloudCorrectionEnabled: boolean;
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
  provider,
  cloudCorrectionEnabled,
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
  const isCloud = provider === "cloud";

  const chooseFile = (selected: File | undefined) => {
    if (!selected || busy) return;
    if (!isAudioFile(selected)) {
      setDropError("Scegli un file audio (MP3, M4A, WAV, OGG…).");
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
      setCopyError("Impossibile copiare il testo negli appunti.");
    }
  };

  const liveMessage = error
    ? error
    : dropError || copyError
      ? dropError || copyError
      : status === "decoding"
        ? "Apro l'audio…"
        : status === "transcribing"
          ? isCloud ? "Invio l'audio a Groq Cloud e preparo il testo…" : "Il motore locale sta trascrivendo l'audio…"
          : status === "saving"
            ? "Salvataggio della trascrizione in cronologia…"
            : status === "done" && result
              ? result.text ? "Trascrizione completata e salvata." : result.notice
              : "";

  const saveLabel = status === "saving"
    ? "Salvataggio in corso…"
    : result?.savedInHistory
      ? "salvata in Cronologia"
      : "salvataggio in Cronologia non riuscito";

  return (
    <div className="tab-slide-in max-w-[700px] mx-auto w-full">
      <p id="audio-file-live" className="sr-only" role="status" aria-live="polite" aria-atomic="true">{liveMessage}</p>

      <header className="mb-5">
        <span className="text-[.66rem] font-extrabold tracking-[.16em] text-[var(--accent)] uppercase">
          Da file a testo
        </span>
        <h1 className="page-title m-0 mt-2">Trascrivi audio</h1>
        <p className="m-0 mt-2 text-[.82rem] text-[var(--muted)]">
          Scegli un file audio, per esempio un vocaletto WhatsApp, e ottieni il testo nella cronologia.
        </p>
      </header>

      <section
        className={`panel p-5 ${dragging ? "ring-2 ring-[var(--accent)]/50" : ""}`}
        aria-labelledby="audio-file-title"
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
      >
        <div className="flex items-center gap-3 mb-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[rgba(255,157,36,.12)] text-[var(--accent)]" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
              <path d="M12 3v12" /><path d="m8 7 4-4 4 4" /><path d="M4 15v3a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-3" />
            </svg>
          </span>
          <div>
            <h2 id="audio-file-title" className="m-0 text-[.95rem] font-bold text-[var(--ink)]">Il tuo audio, in testo</h2>
            <p className="m-0 mt-1 text-[.75rem] text-[var(--muted)]">
              MP3, M4A, WAV, OGG e gli altri formati supportati dal browser. Massimo 25 MB e 10 minuti.
            </p>
          </div>
        </div>

        <input
          ref={inputRef}
          id="audio-file-input"
          type="file"
          accept={ACCEPTED_TYPES}
          hidden
          disabled={busy}
          onChange={(event) => chooseFile(event.target.files?.[0])}
        />

        {file ? (
          <div className="panel-subtle flex items-center gap-3 p-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white/[.05] text-[var(--accent)]" aria-hidden="true">♫</span>
            <span className="min-w-0 flex-1">
              <strong className="block truncate text-[.8rem] text-[var(--ink)]">{file.name}</strong>
              <small className="block text-[.7rem] text-[var(--quiet)]">{formatSize(file.size)} · {isCloud ? "Groq Cloud" : "Motore locale"}</small>
            </span>
            <button
              type="button"
              onClick={() => { onClearFile(); document.getElementById("audio-file-pick")?.focus(); }}
              disabled={busy}
              className="rounded-md border border-white/[.1] bg-white/[.03] px-2.5 py-1.5 text-[.7rem] font-bold text-[var(--muted)] cursor-pointer transition-colors hover:text-[var(--ink)] disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Rimuovi file selezionato"
            >
              Rimuovi
            </button>
          </div>
        ) : (
          <div className="panel-subtle p-6 text-center">
            <span className="block text-2xl text-[var(--quiet)]" aria-hidden="true">♫</span>
            <strong className="mt-2 block text-[.82rem] text-[var(--ink)]">Nessun file selezionato</strong>
            <small className="mt-1 block text-[.72rem] text-[var(--quiet)]">Trascina qui un audio o sceglilo dal dispositivo</small>
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-2.5">
          <button
            id="audio-file-pick"
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
            className="rounded-xl border border-white/[.1] bg-white/[.03] px-4 py-2.5 text-[.75rem] font-bold text-[var(--ink)] cursor-pointer transition-colors hover:border-[var(--accent)]/50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {file ? "Scegli un altro audio" : "Scegli un file audio"}
          </button>
          <button
            id="audio-file-transcribe"
            type="button"
            onClick={onTranscribe}
            disabled={!file || busy}
            aria-busy={busy}
            className="rounded-xl border border-[var(--accent)]/40 bg-[rgba(255,157,36,.14)] px-4 py-2.5 text-[.75rem] font-bold text-[var(--accent)] cursor-pointer transition-colors hover:bg-[rgba(255,157,36,.22)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {status === "decoding" ? "Apro l'audio…" : busy ? "Trascrizione in corso…" : "Trascrivi"}
          </button>
        </div>

        {dropError && <p className="mt-3 text-[.76rem] text-[#ff9a9d]" role="alert">{dropError}</p>}
        {error && <p className="mt-3 text-[.76rem] text-[#ff9a9d]" role="alert">{error}</p>}
      </section>

      {result && (
        <section className="panel p-5 mt-4" aria-labelledby="audio-file-result-title">
          <div className="flex items-start justify-between gap-3">
            <div>
              <span className="text-[.64rem] font-extrabold tracking-[.14em] text-[var(--accent)] uppercase">Trascrizione completata</span>
              <h2 id="audio-file-result-title" className="m-0 mt-1 text-[.95rem] font-bold text-[var(--ink)]">Testo riconosciuto</h2>
            </div>
            <span className="rounded-md bg-white/[.05] px-2 py-1 text-[.64rem] font-bold text-[var(--quiet)]">{result.provider === "cloud" ? "Groq" : "Locale"} · {result.language}</span>
          </div>
          {result.text ? (
            <>
              <p className="mt-4 whitespace-pre-wrap break-words text-[.86rem] leading-7 text-[#d3d0c9]">{result.text}</p>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-white/[.07] pt-3">
                <span className="text-[.7rem] text-[var(--quiet)]">
                  {result.text.split(/\s+/).filter(Boolean).length} parole · {saveLabel}
                </span>
                <button
                  type="button"
                  onClick={() => void copyResult()}
                  className="rounded-lg border border-white/[.1] bg-white/[.03] px-3 py-2 text-[.7rem] font-bold text-[var(--muted)] cursor-pointer transition-colors hover:text-[var(--ink)]"
                >
                  {copied ? "Copiato" : "Copia testo"}
                </button>
              </div>
              {copyError && <p className="mt-2 text-[.72rem] text-[#ff9a9d]" role="alert">{copyError}</p>}
            </>
          ) : (
            <p className="mt-4 text-[.8rem] text-[var(--muted)]">{result.notice}</p>
          )}
        </section>
      )}

      <p className="mt-4 text-[.72rem] leading-6 text-[var(--quiet)]">
        {isCloud
          ? cloudCorrectionEnabled
            ? "Nota sulla privacy: con il provider cloud l'audio viene inviato a Groq tramite connessione protetta e il testo può essere inviato a ChatJimmy per la correzione, insieme al vocabolario personale. Disattiva la correzione nella tab Motore IA se non lo desideri. Il testo viene salvato nella cronologia locale."
            : "Nota sulla privacy: con il provider cloud l'audio viene inviato a Groq tramite connessione protetta. Il vocabolario personale viene usato come prompt. Il testo viene salvato nella cronologia locale."
          : "Nota sulla privacy: con il provider locale l'audio viene elaborato sul dispositivo. Il testo viene salvato nella cronologia locale."}
      </p>
    </div>
  );
}
