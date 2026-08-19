import { useCallback, useEffect, useRef, useState } from "react";
import type { Provider, PythonEvent, ToastType } from "../types";
import { WHISPER_MODELS } from "../types";

export interface DownloadInfo {
  modelName: string;
  progress: number;
  title?: string;
  message?: string;
  isError?: boolean;
}

interface UsePythonOutputOptions {
  selectedProvider: Provider;
  showToast: (message: string, type: ToastType) => void;
  updateStats: (
    words: number,
    wpm: number,
    timeDelta: number,
  ) => Promise<unknown>;
  saveTranscription: (
    text: string,
    timestamp: string,
    wordCount: number
  ) => Promise<void>;
  recordGroqUsage: (durationSecs: number) => void;
}

type ModelStatus = Record<
  string,
  { downloaded: boolean; loading: boolean }
>;

const TRANSCRIPTION_STATUSES = new Set([
  "starting",
  "loading_model",
  "listening",
  "processing",
  "ready",
  "result",
  "error",
  "rate_limit",
]);

const HISTORY_TIMESTAMP_FORMATTER = new Intl.DateTimeFormat("it-IT", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function positiveFiniteNumber(value: unknown): number {
  if (typeof value !== "number" && typeof value !== "string") return 0;
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function modelNameFor(id?: string): string {
  return WHISPER_MODELS.find((model) => model.id === id)?.name || id || "";
}

function clearLoading(status: ModelStatus): ModelStatus {
  const next = { ...status };
  for (const key of Object.keys(next)) {
    if (next[key].loading) next[key] = { ...next[key], loading: false };
  }
  return next;
}

export function usePythonOutput({
  selectedProvider,
  showToast,
  updateStats,
  saveTranscription,
  recordGroqUsage,
}: UsePythonOutputOptions) {
  const [modelStatus, setModelStatus] = useState<ModelStatus>({});
  const [modelReady, setModelReady] = useState(false);
  const [showLoading, setShowLoading] = useState(false);
  const [transcriptionStatus, setTranscriptionStatus] = useState("idle");
  const [downloadInfo, setDownloadInfo] = useState<DownloadInfo | null>(null);
  const [transcriptionText, setTranscriptionText] = useState("");
  const [gpuStatus, setGpuStatus] = useState("Dispositivo in uso: CPU");

  const selectedProviderRef = useRef(selectedProvider);
  selectedProviderRef.current = selectedProvider;
  const activeTranscriptionRef = useRef(false);
  const transcriptionLockRef = useRef(false);
  const isTestRecordingRef = useRef(false);
  const modelReadyRef = useRef(false);
  const lastTranscriptionStatusRef = useRef("idle");
  modelReadyRef.current = modelReady;

  const updateModelStatus = useCallback(
    (modelId: string, patch: Partial<ModelStatus[string]>) => {
      setModelStatus((prev) => ({
        ...prev,
        [modelId]: { ...prev[modelId], ...patch },
      }));
    },
    []
  );

  const mergeModelStatus = useCallback(
    (downloadedById: Record<string, boolean>) => {
      setModelStatus((prev) => {
        const next = { ...prev };
        for (const [id, downloaded] of Object.entries(downloadedById)) {
          next[id] = { ...next[id], downloaded };
        }
        return next;
      });
    },
    []
  );

  const clearTranscriptionText = useCallback(() => {
    setTranscriptionText("");
  }, []);
  const clearDownloadInfo = useCallback(() => {
    setDownloadInfo(null);
  }, []);

  useEffect(() => {
    if (!window.__TAURI__?.event?.listen) return;

    let cancelled = false;
    let unlisten: (() => void) | null = null;

    window.__TAURI__.event
      .listen("python_output", (event: { payload: unknown }) => {
        try {
          const rawPayload = typeof event.payload === "string" ? event.payload : "";

          // Python always writes the status field first. The overlay is the
          // only consumer of volume events, so reject both compact and legacy
          // JSON spellings before paying for JSON.parse in the main app.
          if (
            rawPayload.startsWith('{"status":"volume"') ||
            rawPayload.startsWith('{"status": "volume"')
          ) {
            return;
          }

          const data = JSON.parse(rawPayload) as PythonEvent;

          // The overlay owns volume updates. Exit before any React state
          // checks or allocations so the high-frequency meter never causes
          // work in the main application tree.
          if (data.status === "volume") return;

          let pastePromise: Promise<unknown> | null = null;

          // Start the native paste before React state or persistence work.
          if (data.status === "result" && data.text && window.__TAURI__?.core?.invoke) {
            pastePromise = window.__TAURI__.core.invoke("execute_paste", {
              text: data.text,
            });
          }

          if (data.status === "starting" || data.status === "loading_model") {
            setModelReady(false);
            setShowLoading(true);
          } else if (
            data.status === "ready" ||
            data.status === "result" ||
            data.status === "error"
          ) {
            setModelReady(true);
            setShowLoading(false);
          }

          if (
            TRANSCRIPTION_STATUSES.has(data.status || "") &&
            lastTranscriptionStatusRef.current !== data.status
          ) {
            lastTranscriptionStatusRef.current = data.status;
            setTranscriptionStatus(data.status);
          }

          if (data.status === "listening") {
            activeTranscriptionRef.current = true;
            transcriptionLockRef.current = false;
          } else if (
            data.status === "result" ||
            data.status === "ready" ||
            data.status === "error"
          ) {
            activeTranscriptionRef.current = false;
            transcriptionLockRef.current = false;
          }

          if (data.status === "downloading") {
            if (data.model) updateModelStatus(data.model, { loading: true });
            setDownloadInfo({
              modelName: modelNameFor(data.model),
              progress: data.progress || 0,
            });
          }

          if (data.status === "download_complete") {
            if (data.model) {
              updateModelStatus(data.model, { downloaded: true, loading: false });
            }
            setDownloadInfo({
              modelName: modelNameFor(data.model),
              progress: 100,
            });
            showToast(
              `Modello ${modelNameFor(data.model)} scaricato con successo`,
              "success"
            );
          }

          if (data.status === "download_error") {
            console.error("Download Error:", data.message);
            setDownloadInfo({
              modelName: modelNameFor(data.model),
              progress: 100,
              title: "Errore nel Download",
              message:
                data.message ||
                "Si è verificato un errore durante il download.",
              isError: true,
            });
            setModelStatus(clearLoading);
            showToast(
              data.message || "Errore durante il download del modello",
              "error"
            );
          }

          if (data.status === "error") {
            console.error("Python Error:", data.message);
            setModelStatus(clearLoading);
            showToast(data.message || "Errore del motore Python", "error");
          }

          if (data.status === "rate_limit") {
            showToast(data.message || "Rate limit raggiunto", "error");
          }

          if (data.status === "gpu_info") {
            const deviceLabel =
              data.current_device === "cuda"
                ? `GPU (${data.device_name})`
                : "CPU";
            const cudaLabel = data.cuda_available
              ? `CUDA disponibile (${data.device_name})`
              : "CUDA non disponibile";
            setGpuStatus(`Dispositivo in uso: ${deviceLabel} | ${cudaLabel}`);
          }

          if (data.status === "info" && data.message) {
            console.log("[Python]", data.message);
          }
          if (data.status === "warning" && data.message) {
            console.warn("[Python]", data.message);
            showToast(data.message, "error");
          }

          if (data.status === "result" && data.text) {
            const resultText = data.text;
            const trimmedResultText = resultText.trim();
            const duration = positiveFiniteNumber(data.duration);
            if (isTestRecordingRef.current) {
              isTestRecordingRef.current = false;
              setTranscriptionText((previous) =>
                previous + trimmedResultText + "\n"
              );
            }

            if (pastePromise) {
              void pastePromise.catch((error) =>
                console.error("[RESULT] paste error:", error)
              );
            }

            const wordCount = countWords(trimmedResultText);
            if (wordCount > 0 && duration > 0) {
              const wpm = Math.round((wordCount / duration) * 60);
              void updateStats(wordCount, wpm, duration / 60)
                .catch(() => {});
            }

            const historyTimestamp = HISTORY_TIMESTAMP_FORMATTER.format(new Date());
            void saveTranscription(
              trimmedResultText,
              historyTimestamp,
              wordCount
            );

            if (selectedProviderRef.current === "cloud") {
              recordGroqUsage(duration);
            }
          }
        } catch (error) {
          console.error("[python_output] Error:", error);
        }
      })
      .then((cleanup: () => void) => {
        if (cancelled) cleanup();
        else unlisten = cleanup;
      });

    return () => {
      cancelled = true;
      if (unlisten) unlisten();
    };
  }, [
    updateStats,
    recordGroqUsage,
    saveTranscription,
    showToast,
    updateModelStatus,
  ]);

  return {
    modelStatus,
    modelReady,
    modelReadyRef,
    showLoading,
    transcriptionStatus,
    transcriptionText,
    downloadInfo,
    gpuStatus,
    activeTranscriptionRef,
    transcriptionLockRef,
    isTestRecordingRef,
    updateModelStatus,
    mergeModelStatus,
    clearTranscriptionText,
    clearDownloadInfo,
  };
}
