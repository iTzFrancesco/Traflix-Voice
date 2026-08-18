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
  loadStats: () => void | Promise<void>;
  saveTranscription: (
    text: string,
    timestamp: string,
    wordCount: number
  ) => Promise<void>;
  recordGroqUsage: (durationSecs: number) => void;
  reloadGroqUsage: () => void;
}

type ModelStatus = Record<
  string,
  { downloaded: boolean; loading: boolean }
>;

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
  loadStats,
  saveTranscription,
  recordGroqUsage,
  reloadGroqUsage,
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
      .listen("python_output", async (event: { payload: unknown }) => {
        try {
          const data = JSON.parse(event.payload as string) as PythonEvent;
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
            [
              "starting",
              "loading_model",
              "listening",
              "processing",
              "ready",
              "result",
              "error",
              "rate_limit",
            ].includes(data.status || "")
          ) {
            setTranscriptionStatus(data.status);
          }

          if (data.status === "listening") {
            activeTranscriptionRef.current = true;
            transcriptionLockRef.current = false;
          } else if (data.status === "result" || data.status === "ready") {
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

          // Volume is consumed by the overlay and must not rerender the app.
          if (data.status === "volume") return;

          if (data.status === "info" && data.message) {
            console.log("[Python]", data.message);
          }
          if (data.status === "warning" && data.message) {
            console.warn("[Python]", data.message);
            showToast(data.message, "error");
          }

          if (data.status === "result" && data.text) {
            const resultText = data.text;
            if (isTestRecordingRef.current) {
              isTestRecordingRef.current = false;
              setTranscriptionText((previous) =>
                previous + resultText.trim() + "\n"
              );
            }

            if (pastePromise) {
              void pastePromise.catch((error) =>
                console.error("[RESULT] paste error:", error)
              );
            }

            const wordCount = resultText
              .trim()
              .split(/\s+/)
              .filter(Boolean).length;
            if (wordCount > 0 && data.duration && window.__TAURI__?.core?.invoke) {
              const wpm = Math.round((wordCount / data.duration) * 60);
              void window.__TAURI__.core
                .invoke("update_stats", {
                  words: wordCount,
                  wpm,
                  timeDelta: data.duration / 60,
                })
                .then(() => loadStats())
                .catch(() => {});
            }

            const historyTimestamp = new Date().toLocaleString("it-IT", {
              day: "2-digit",
              month: "2-digit",
              year: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            });
            void saveTranscription(
              resultText.trim(),
              historyTimestamp,
              wordCount
            );

            if (selectedProviderRef.current === "cloud") {
              recordGroqUsage(data.duration || 0);
            }
            reloadGroqUsage();
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
    loadStats,
    recordGroqUsage,
    reloadGroqUsage,
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
