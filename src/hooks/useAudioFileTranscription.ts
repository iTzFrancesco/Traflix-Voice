import { useCallback, useEffect, useRef, useState } from "react";

const SAMPLE_RATE = 16000;
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const MAX_SAMPLES = SAMPLE_RATE * 600;
const FILE_TIMEOUT_MS = 12 * 60 * 1000;

const HISTORY_TIMESTAMP_FORMATTER = new Intl.DateTimeFormat("it-IT", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export type AudioFileStatus = "idle" | "decoding" | "transcribing" | "saving" | "done" | "error";

export interface AudioFileTranscript {
  text: string;
  notice: string;
  duration: number;
  provider: string;
  language: string;
  savedInHistory: boolean;
}

interface UseAudioFileTranscriptionOptions {
  language: string;
  model: string;
  saveTranscription: (
    text: string,
    timestamp: string,
    wordCount: number
  ) => Promise<boolean>;
}

interface FileEvent {
  status?: string;
  request_id?: string;
  text?: string;
  message?: string;
  duration?: number;
  provider?: string;
  language?: string;
}

function monoSamples(buffer: AudioBuffer): Float32Array {
  const frames = buffer.length;
  const channels = buffer.numberOfChannels;
  if (channels === 1) return new Float32Array(buffer.getChannelData(0));
  const mono = new Float32Array(frames);
  for (let channel = 0; channel < channels; channel += 1) {
    const data = buffer.getChannelData(channel);
    for (let frame = 0; frame < frames; frame += 1) mono[frame] += data[frame];
  }
  for (let frame = 0; frame < frames; frame += 1) mono[frame] /= channels;
  return mono;
}

function resample(samples: Float32Array, fromRate: number, toRate: number): Float32Array {
  const output = new Float32Array(Math.max(1, Math.round(samples.length * toRate / fromRate)));
  const step = fromRate / toRate;
  for (let index = 0; index < output.length; index += 1) {
    const position = index * step;
    const lower = Math.floor(position);
    const upper = Math.min(lower + 1, samples.length - 1);
    const fraction = position - lower;
    output[index] = samples[lower] * (1 - fraction) + samples[upper] * fraction;
  }
  return output;
}

async function decodeToPcm16(file: File): Promise<Int16Array> {
  if (file.size > MAX_FILE_BYTES) {
    throw new Error("Il file supera 25 MB. Scegli un audio più breve.");
  }
  const bytes = await file.arrayBuffer();
  const context = new OfflineAudioContext({
    numberOfChannels: 1,
    length: 1,
    sampleRate: SAMPLE_RATE,
  });
  let decoded: AudioBuffer;
  try {
    decoded = await context.decodeAudioData(bytes);
  } catch {
    throw new Error("Formato audio non supportato dal browser. Prova MP3, WAV o OGG.");
  }
  // Check the duration before allocating the downmixed arrays: a highly
  // compressed file can be small on disk but very long once decoded.
  if (decoded.length === 0 || decoded.duration > 600) {
    throw new Error("Durata audio non valida (massimo 10 minuti).");
  }
  const mono = monoSamples(decoded);
  // decodeAudioData usually resamples to the context rate; the explicit check
  // is what guarantees 16 kHz regardless of browser behaviour.
  const samples = decoded.sampleRate === SAMPLE_RATE
    ? mono
    : resample(mono, decoded.sampleRate, SAMPLE_RATE);
  if (samples.length === 0 || samples.length > MAX_SAMPLES) {
    throw new Error("Durata audio non valida (massimo 10 minuti).");
  }
  const pcm = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    pcm[index] = Math.max(-32768, Math.min(32767, Math.round(samples[index] * 32767)));
  }
  return pcm;
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

export function useAudioFileTranscription({
  language,
  model,
  saveTranscription,
}: UseAudioFileTranscriptionOptions) {
  // This hook is mounted at app level: the result is saved even if the user
  // switches tab while the sidecar is still transcribing.
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<AudioFileStatus>("idle");
  const [result, setResult] = useState<AudioFileTranscript | null>(null);
  const [error, setError] = useState("");
  const requestIdRef = useRef<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const optionsRef = useRef({ language, model });
  optionsRef.current = { language, model };

  const clearTimer = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!window.__TAURI__?.event?.listen) return;
    let cancelled = false;
    let unlisten: (() => void) | null = null;

    window.__TAURI__.event
      .listen("python_output", (event) => {
        if (cancelled) return;
        let data: FileEvent;
        try {
          data = JSON.parse(typeof event.payload === "string" ? event.payload : "") as FileEvent;
        } catch {
          return;
        }
        // Parse and check the status semantically: the raw prefix depends on
        // the sidecar's JSON serialization style.
        if (typeof data.status !== "string" || !data.status.startsWith("file_")) return;
        if (!data.request_id || data.request_id !== requestIdRef.current) return;

        if (data.status === "file_processing") {
          setStatus("transcribing");
          return;
        }
        if (data.status === "file_result") {
          clearTimer();
          requestIdRef.current = null;
          const text = (data.text || "").trim();
          setResult({
            text,
            notice: text ? "" : (data.message || "Nessun testo rilevato in questo audio."),
            duration: data.duration || 0,
            provider: "local",
            language: data.language || optionsRef.current.language,
            savedInHistory: false,
          });
          setError("");
          const wordCount = text ? text.split(/\s+/).length : 0;
          if (wordCount > 0) {
            setStatus("saving");
            void saveTranscription(
              text,
              HISTORY_TIMESTAMP_FORMATTER.format(new Date()),
              wordCount
            ).then((saved) => {
              setResult((previous) => previous ? { ...previous, savedInHistory: saved } : previous);
              setStatus("done");
            });
          } else {
            setStatus("done");
          }
          return;
        }
        if (data.status === "file_error") {
          clearTimer();
          requestIdRef.current = null;
          setError(data.message || "Trascrizione non riuscita.");
          setResult(null);
          setStatus("error");
        }
      })
      .then((cleanup) => {
        if (cancelled) cleanup();
        else unlisten = cleanup;
      });

    return () => {
      cancelled = true;
      if (unlisten) unlisten();
    };
  }, [saveTranscription, clearTimer]);

  useEffect(() => clearTimer, [clearTimer]);

  const reset = useCallback(() => {
    clearTimer();
    requestIdRef.current = null;
    setStatus("idle");
    setResult(null);
    setError("");
  }, [clearTimer]);

  const selectFile = useCallback((selected: File) => {
    if (requestIdRef.current) return;
    setFile(selected);
    reset();
  }, [reset]);

  const clearFile = useCallback(() => {
    if (requestIdRef.current) return;
    setFile(null);
    reset();
  }, [reset]);

  const transcribeFile = useCallback(async () => {
    if (!file || requestIdRef.current || !window.__TAURI__?.core?.invoke) return;
    setError("");
    setResult(null);
    setStatus("decoding");
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    requestIdRef.current = requestId;
    try {
      const pcm = await decodeToPcm16(file);
      if (requestIdRef.current !== requestId) return;
      const options = optionsRef.current;
      setStatus("transcribing");
      timeoutRef.current = setTimeout(() => {
        if (requestIdRef.current !== requestId) return;
        requestIdRef.current = null;
        setError("Trascrizione non completata. Controlla che il motore vocale sia disponibile.");
        setStatus("error");
      }, FILE_TIMEOUT_MS);
      await window.__TAURI__.core.invoke("send_to_python", {
        message: JSON.stringify({
          command: "transcribe_audio_file",
          request_id: requestId,
          samples: toBase64(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)),
          provider: "local",
          language: options.language,
          model: options.model,
        }),
      });
    } catch (decodeError) {
      if (requestIdRef.current !== requestId) return;
      clearTimer();
      requestIdRef.current = null;
      setError(decodeError instanceof Error ? decodeError.message : "Impossibile leggere il file audio.");
      setStatus("error");
    }
  }, [file, clearTimer]);

  return {
    file,
    status,
    result,
    error,
    selectFile,
    clearFile,
    transcribeFile,
    reset,
  };
}
