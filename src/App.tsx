import { useState, useEffect, useCallback, useRef } from "react";
import Sidebar from "./components/Sidebar";
import HomeTab from "./components/HomeTab";
import IATab from "./components/IATab";
import TastiTab from "./components/TastiTab";
import CronologiaTab from "./components/CronologiaTab";
import SistemaTab from "./components/SistemaTab";
import ToastContainer from "./components/Toast";
import LoadingOverlay from "./components/LoadingOverlay";
import DownloadPopup from "./components/DownloadPopup";
import { useHotkey } from "./hooks/useHotkey";
import type {
  AppSettings,
  AppStats,
  GroqUsage,
  TranscriptionEntry,
  AudioDeviceInfo,
  Provider,
  Toast,
  PythonEvent,
} from "./types";
import { WHISPER_MODELS } from "./types";

// ─── HELPERS ──────────────────────────────────────────────────────────────────

function formatKey(key: string): string {
  const map: Record<string, string> = {
    Control: "CommandOrControl",
    Alt: "Alt",
    Shift: "Shift",
    " ": "Space",
    Meta: "Super",
  };
  return map[key] || key.charAt(0).toUpperCase() + key.slice(1);
}

function convertToSRT(text: string): string {
  const lines = text.split("\n").filter((line) => line.trim());
  let srtContent = "";
  let index = 1;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;

    const timestampMatch = line.match(/^\[(\d{1,2}):(\d{2})\]\s*(.+)$/);

    if (timestampMatch) {
      // Formato atteso: [mm:ss] Testo
      const minutes = parseInt(timestampMatch[1]);
      const seconds = parseInt(timestampMatch[2]);
      const textContent = timestampMatch[3];
      const startTime = `00:${String(minutes).padStart(2, "0")}:${String(
        seconds
      ).padStart(2, "0")},000`;
      let endSec = minutes * 60 + seconds + 3;
      const endH = Math.floor(endSec / 3600);
      const endM = Math.floor((endSec % 3600) / 60);
      const endS = endSec % 60;

      const endTime = `${String(endH).padStart(2, "0")}:${String(
        endM
      ).padStart(2, "0")}:${String(endS).padStart(2, "0")},000`;

      srtContent += `${index}\n`;
      srtContent += `${startTime} --> ${endTime}\n`;
      srtContent += `${textContent}\n\n`;
      index++;
    } else {
      const startSeconds = (index - 1) * 3;
      const endSeconds = index * 3;
      const startH = Math.floor(startSeconds / 3600);
      const startM = Math.floor((startSeconds % 3600) / 60);
      const startS = startSeconds % 60;
      const endH = Math.floor(endSeconds / 3600);
      const endM = Math.floor((endSeconds % 3600) / 60);
      const endS = endSeconds % 60;

      srtContent += `${index}\n`;
      srtContent += `${String(startH).padStart(2, "0")}:${String(
        startM
      ).padStart(2, "0")}:${String(startS).padStart(2, "0")},000 --> ${String(
        endH
      ).padStart(2, "0")}:${String(endM).padStart(2, "0")}:${String(
        endS
      ).padStart(2, "0")},000\n`;
      srtContent += `${line}\n\n`;
      index++;
    }
  }
  return srtContent;
}

// ─── APP ──────────────────────────────────────────────────────────────────────

// DEV mode badge
const IS_DEV = import.meta.env.DEV;

export default function App() {
  // ── STATE ──
  const [activeTab, setActiveTab] = useState("home");
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [stats, setStats] = useState<AppStats>({
    total_words: 0,
    avg_wpm: 0,
    total_time: 0,
  });
  const [modelStatus, setModelStatus] = useState<
    Record<string, { downloaded: boolean; loading: boolean }>
  >({});
  const [selectedModel, setSelectedModel] = useState("small");
  const [selectedProvider, setSelectedProvider] = useState<Provider>("local");
  const [selectedLanguage, setSelectedLanguage] = useState("it");
  const [computeDevice, setComputeDevice] = useState("cpu");
  const [transcriptionStatus, setTranscriptionStatus] = useState("idle");
  const [modelReady, setModelReady] = useState(false);
  const [activeTranscription, setActiveTranscription] = useState(false);
  const [showLoading, setShowLoading] = useState(false);
  const [downloadInfo, setDownloadInfo] = useState<{
    modelName: string;
    progress: number;
    title?: string;
    message?: string;
    isError?: boolean;
  } | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [transcriptionText, setTranscriptionText] = useState("");
  const [historyEntries, setHistoryEntries] = useState<TranscriptionEntry[]>([]);
  const [audioDevices, setAudioDevices] = useState<AudioDeviceInfo[]>([]);
  const [appVersion, setAppVersion] = useState("");
  const [holdToSpeak, setHoldToSpeak] = useState(false);
  const [widgetMode, setWidgetMode] = useState("always");
  const [groqUsage, setGroqUsage] = useState<GroqUsage | null>(null);
  const [gpuStatus, setGpuStatus] = useState("Dispositivo in uso: CPU");

  const toastIdRef = useRef(0);
  const activeTranscriptionRef = useRef(false);
  const selectedProviderRef = useRef<Provider>("local");
  const isTestRecordingRef = useRef(false);
  const startSoundRef = useRef<HTMLAudioElement | null>(null);
  const stopSoundRef = useRef<HTMLAudioElement | null>(null);
  const hotkeyInputRef = useRef<HTMLInputElement | null>(null);
  const hotkeyListenersRef = useRef<(() => void)[]>([]);
  const modelReadyRef = useRef(false);
  const holdToSpeakRef = useRef(false);
  const startFnRef = useRef<(isTest?: boolean) => Promise<void>>(async () => {});
  const stopFnRef = useRef<() => void>(() => {});
  modelReadyRef.current = modelReady;
  holdToSpeakRef.current = holdToSpeak;
  selectedProviderRef.current = selectedProvider;

  // ── HOTKEY RECORDING ──
  const {
    isRecording: isHotkeyRecording,
    recordedKeys,
    startRecording,
    stopRecording,
    resetKeys,
  } = useHotkey();

  // ── TOAST ──
  const showToast = useCallback(
    (message: string, type: "success" | "error" | "info") => {
      const id = ++toastIdRef.current;
      setToasts((prev) => [...prev, { id, message, type }]);
    },
    []
  );

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // ── LOAD SETTINGS WITH RETRY ──
  const loadSettings = useCallback(async (): Promise<AppSettings | null> => {
    if (!window.__TAURI__?.core?.invoke) return null;

    for (let attempt = 0; attempt < 4; attempt++) {
      if (attempt > 0) {
        console.warn(`[settings] retrying loadSettings (attempt ${attempt + 1}/4)...`);
        await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
      }
      try {
        const s = (await window.__TAURI__.core.invoke(
          "load_settings"
        )) as AppSettings | null;
        if (!s || typeof s.hotkey === "undefined") {
          console.warn("[settings] invalid data:", JSON.stringify(s));
          continue;
        }
        console.log(
          "[settings] loaded provider:",
          s.provider,
          "model:",
          s.model,
          "hotkey:",
          s.hotkey
        );
        setSettings(s);
        setSelectedModel(s.model || "small");
        setSelectedProvider((s.provider as Provider) || "local");
        setSelectedLanguage(s.selectedLanguage || "it");
        setComputeDevice(s.computeDevice || "cpu");
        setHoldToSpeak(s.holdToSpeak ?? false);
        setWidgetMode(s.widgetMode ?? "always");
        return s;
      } catch (err) {
        console.warn("[settings] error:", err);
      }
    }
    return null;
  }, []);

  // ── PERSIST SETTINGS ──
  const persistSettings = useCallback(
    async (overrides?: Partial<AppSettings>) => {
      if (!window.__TAURI__?.core?.invoke || !settings) return;
      const merged: AppSettings = { ...settings, ...overrides };
      try {
        await window.__TAURI__.core.invoke("save_settings", { settings: merged });
        setSettings(merged);
      } catch (err) {
        console.error("[settings] save error:", err);
      }
    },
    [settings]
  );

  // ── LOAD STATS ──
  const loadStats = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const s = (await window.__TAURI__.core.invoke("get_stats")) as AppStats;
        setStats({
          total_words: s.total_words ?? 0,
          avg_wpm: s.avg_wpm ?? 0,
          total_time: s.total_time ?? 0,
        });
        return;
      } catch (err) {
        if (attempt < 2) await new Promise((r) => setTimeout(r, 500));
      }
    }
  }, []);

  // ── CHECK MODELS ──
  const refreshAllModelStatus = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;
    const results = await Promise.all(
      WHISPER_MODELS.map((m) =>
        window.__TAURI__.core
          .invoke("check_model_exists", { modelId: m.id })
          .then((exists) => ({ id: m.id, exists }))
      )
    );
    const newStatus: Record<string, { downloaded: boolean; loading: boolean }> =
      {};
    for (const { id, exists } of results) {
      newStatus[id] = { ...modelStatus[id], downloaded: exists as boolean };
    }
    setModelStatus((prev) => ({ ...prev, ...newStatus }));
  }, []);

  // ── GROQ USAGE ──
  const loadGroqUsageFromStorage = useCallback((): GroqUsage | null => {
    try {
      const raw = localStorage.getItem("groq_usage");
      if (!raw) return null;
      const parsed = JSON.parse(raw) as GroqUsage;
      const today = new Date().toISOString().split("T")[0];
      if (parsed.date !== today) return null;
      return parsed;
    } catch {
      return null;
    }
  }, []);

  const recordGroqUsage = useCallback((durationSecs: number) => {
    if (!durationSecs) return;
    try {
      const today = new Date().toISOString().split("T")[0];
      let u: GroqUsage;
      const raw = localStorage.getItem("groq_usage");
      if (raw) {
        try {
          u = JSON.parse(raw);
        } catch {
          u = { date: today, audio_seconds: 0, audio_seconds_hourly: 0, hourly_reset: "" };
        }
      } else {
        u = { date: today, audio_seconds: 0, audio_seconds_hourly: 0, hourly_reset: "" };
      }
      if (u.date !== today) {
        u = { date: today, audio_seconds: 0, audio_seconds_hourly: 0, hourly_reset: "" };
      }
      const now = Date.now();
      const thisHour = Math.floor(now / 3600000);
      if (u._lastHour !== thisHour) {
          u.audio_seconds_hourly = 0;
          u._lastHour = thisHour;
        }
      u.audio_seconds = Math.round((u.audio_seconds || 0) + durationSecs);
      u.audio_seconds_hourly = Math.round((u.audio_seconds_hourly || 0) + durationSecs);
      const nextHour = (Math.floor(now / 3600000) + 1) * 3600000;
      u.hourly_reset = new Date(nextHour).toLocaleTimeString("it-IT", {
        hour: "2-digit",
        minute: "2-digit",
      });
      localStorage.setItem("groq_usage", JSON.stringify(u));
      setGroqUsage(u);
    } catch {}
  }, []);

  const reloadGroqUsage = useCallback(() => {
    setGroqUsage(loadGroqUsageFromStorage());
  }, [loadGroqUsageFromStorage]);

  // ── AUDIO DEVICES ──
  const loadAudioDevices = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;
    try {
      const result = (await window.__TAURI__.core.invoke(
        "get_audio_devices"
      )) as AudioDeviceInfo[];
      setAudioDevices(result || []);
    } catch (err) {
      console.error("[audio] Errore:", err);
    }
  }, []);

  // ── HISTORY ──
  const loadHistory = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;
    try {
      const result = (await window.__TAURI__.core.invoke(
        "get_history"
      )) as TranscriptionEntry[];
      setHistoryEntries(result || []);
    } catch (err) {
      console.error("[cronologia] Errore:", err);
    }
  }, []);

  const clearHistory = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;
    try {
      await window.__TAURI__.core.invoke("clear_history");
      setHistoryEntries([]);
      loadStats();
    } catch (err) {
      console.error("[cronologia] Errore cancellazione:", err);
    }
  }, [loadStats]);

  // ── INIT ──
  // Set DEV title
  useEffect(() => {
    if (IS_DEV) {
      document.title = "Traflix Voice [DEV]";
    }
  }, []);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];

    const init = async () => {
      // Load settings
      const initialSettings = await loadSettings();

      // Load stats
      loadStats();

      // These startup tasks are independent. Cloud users do not need local
      // model probes at all, so avoid touching the model catalog in that mode.
      const versionTask = (async () => {
        if (window.__TAURI__?.app?.getVersion) {
          try {
            const ver = await window.__TAURI__.app.getVersion();
            setAppVersion(ver);
          } catch {}
        }
      })();
      const modelTask =
        initialSettings?.provider === "cloud"
          ? Promise.resolve()
          : refreshAllModelStatus();
      await Promise.all([versionTask, loadAudioDevices(), modelTask]);

      // Load groq usage
      setGroqUsage(loadGroqUsageFromStorage());

      // Initialize sounds
      startSoundRef.current = new Audio("/assets/sounds/start.wav");
      stopSoundRef.current = new Audio("/assets/sounds/stop.wav");
      if (startSoundRef.current) startSoundRef.current.volume = 1.0;
      if (stopSoundRef.current) stopSoundRef.current.volume = 1.0;

      // Request Python status sync
      const statusTimer = setTimeout(async () => {
        try {
          await window.__TAURI__.core.invoke("send_to_python", {
            message: JSON.stringify({ command: "get_status" }),
          });
        } catch (err) {
          console.warn("[startup] get_status error:", err);
        }
      }, 100);
      timers.push(statusTimer);
    };

    init();

    return () => {
      timers.forEach(clearTimeout);
    };
  }, []);

  // ── PYTHON OUTPUT EVENT LISTENER ──
  useEffect(() => {
    if (!window.__TAURI__?.event?.listen) return;

    let cancelled = false;
    let unlisten: (() => void) | null = null;

    window.__TAURI__.event
      .listen("python_output", async (event: { payload: unknown }) => {
        try {
          const data = JSON.parse(event.payload as string) as PythonEvent;
          let pastePromise: Promise<unknown> | null = null;

          // Start the native paste before any React state updates or local
          // bookkeeping can yield the event handler.
          if (data.status === "result" && data.text && window.__TAURI__?.core?.invoke) {
            pastePromise = window.__TAURI__.core.invoke("execute_paste", {
              text: data.text,
            });
          }

          // Update modelReady and loading overlay
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

          if (["starting", "loading_model", "listening", "processing", "ready", "result", "error", "rate_limit"].includes(data.status || "")) {
            setTranscriptionStatus(data.status);
          }

          // Play sounds + UI state (only for test recordings)
          if (data.status === "listening") {
            activeTranscriptionRef.current = true;
            transcriptionLockRef.current = false;
            if (isTestRecordingRef.current) {
              setActiveTranscription(true);
            }
          } else if (data.status === "result" || data.status === "ready") {
            if (isTestRecordingRef.current) setActiveTranscription(false);
            activeTranscriptionRef.current = false;
            transcriptionLockRef.current = false;
          }

          // Download handling
          if (data.status === "downloading") {
            if (data.model) {
              setModelStatus((prev) => ({
                ...prev,
                [data.model!]: {
                  ...prev[data.model!],
                  loading: true,
                },
              }));
            }
            const modelName =
              WHISPER_MODELS.find((m) => m.id === data.model)?.name ||
              data.model ||
              "";
            setDownloadInfo({
              modelName,
              progress: data.progress || 0,
            });
          }

          if (data.status === "download_complete") {
            if (data.model) {
              setModelStatus((prev) => ({
                ...prev,
                [data.model!]: { downloaded: true, loading: false },
              }));
            }
            const modelName =
              WHISPER_MODELS.find((m) => m.id === data.model)?.name ||
              data.model ||
              "";
            // Show 100% briefly then close
            setDownloadInfo({ modelName, progress: 100 });
            showToast(`Modello ${modelName} scaricato con successo`, "success");
          }

          if (data.status === "download_error") {
            console.error("Download Error:", data.message);
            const modelName =
              WHISPER_MODELS.find((m) => m.id === data.model)?.name ||
              data.model ||
              "";
            setDownloadInfo({
              modelName,
              progress: 100,
              title: "Errore nel Download",
              message: data.message || "Si è verificato un errore durante il download.",
              isError: true,
            });
            // Reset loading states
            setModelStatus((prev) => {
              const next = { ...prev };
              for (const key of Object.keys(next)) {
                if (next[key].loading) next[key] = { ...next[key], loading: false };
              }
              return next;
            });
            showToast(data.message || "Errore durante il download del modello", "error");
          }

          // Error from Python
          if (data.status === "error") {
            console.error("Python Error:", data.message);
            setModelStatus((prev) => {
              const next = { ...prev };
              for (const key of Object.keys(next)) {
                if (next[key].loading) next[key] = { ...next[key], loading: false };
              }
              return next;
            });
            showToast(data.message || "Errore del motore Python", "error");
          }

          // Rate limit
          if (data.status === "rate_limit") {
            showToast(data.message || "Rate limit raggiunto", "error");
          }

          // GPU info
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

          // Volume is consumed directly by the overlay. Keeping it out of
          // React state prevents the full main window from rerendering while
          // the user is speaking.
          if (data.status === "volume") return;

          // Log messages
          if (data.status === "info" && data.message) {
            console.log("[Python]", data.message);
          }
          if (data.status === "warning" && data.message) {
            console.warn("[Python]", data.message);
            showToast(data.message, "error");
          }

          // Result with transcription text
          if (data.status === "result" && data.text) {
            const resultText = data.text;
            if (isTestRecordingRef.current) {
              isTestRecordingRef.current = false;
              setTranscriptionText((prev) => prev + resultText.trim() + "\n");
            }

            // Paste first: stats/history are local persistence work and must
            // not add latency before the text reaches the active application.
            if (pastePromise) {
              void pastePromise.catch((e) => console.error("[RESULT] paste error:", e));
            }

            // Update stats
            const wordCount = resultText
              .trim()
              .split(/\s+/)
              .filter(Boolean).length;
            if (wordCount > 0 && data.duration) {
              const wpm = Math.round((wordCount / data.duration) * 60);
              if (window.__TAURI__?.core?.invoke) {
                void window.__TAURI__.core
                  .invoke("update_stats", {
                    words: wordCount,
                    wpm,
                    timeDelta: data.duration / 60,
                  })
                  .then(() => loadStats())
                  .catch(() => {});
              }
            }

            // Save to history
            const historyTimestamp = new Date().toLocaleString("it-IT", {
              day: "2-digit",
              month: "2-digit",
              year: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            });
            if (window.__TAURI__?.core?.invoke) {
              void window.__TAURI__.core
                .invoke("save_transcription", {
                  text: data.text.trim(),
                  timestamp: historyTimestamp,
                  wordCount,
                })
                .catch(() => {});
            }

            // Groq usage tracking
            if (selectedProviderRef.current === "cloud") {
              recordGroqUsage(data.duration || 0);
            }

            // Reload groq usage
            reloadGroqUsage();
          }
        } catch (err) {
          console.error("[python_output] Error:", err);
        }
      })
      .then((fn: () => void) => {
        if (cancelled) {
          fn(); // Promise risolta dopo cleanup → disiscrivi subito
        } else {
          unlisten = fn;
        }
      });

    return () => {
      cancelled = true;
      if (unlisten) unlisten();
    };
  }, []);

  // ── HOTKEY EVENT LISTENERS (with refs to avoid re-registration) ──
  useEffect(() => {
    if (!window.__TAURI__?.event?.listen) return;

    // Clean up any stale listeners first
    hotkeyListenersRef.current.forEach((fn) => fn());
    hotkeyListenersRef.current = [];

    let cancelled = false;

    Promise.all([
      window.__TAURI__.event.listen("hotkey_pressed", () => {
        if (!modelReadyRef.current) {
          showToast("Caricamento modello in corso, attendere...", "info");
          return;
        }
        if (holdToSpeakRef.current) {
          startFnRef.current();
        } else {
          if (activeTranscriptionRef.current) {
            stopFnRef.current();
          } else {
            startFnRef.current();
          }
        }
      }),
      window.__TAURI__.event.listen("hotkey_released", () => {
        if (holdToSpeakRef.current) {
          stopFnRef.current();
        }
      }),
      window.__TAURI__.event.listen("hotkey_error", (event: { payload: unknown }) => {
        console.error("[hotkey] Error:", event.payload);
        showToast(event.payload as string, "error");
      }),
    ]).then((fns) => {
      if (!cancelled) {
        hotkeyListenersRef.current = fns;
      } else {
        fns.forEach((fn) => fn());
      }
    });

    return () => {
      cancelled = true;
      hotkeyListenersRef.current.forEach((fn) => fn());
      hotkeyListenersRef.current = [];
    };
  }, []); // empty deps = register once

  // ── LOCAL FALLBACK HOTKEY (Ctrl+Alt) ──
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const isControlAlt = e.ctrlKey && e.altKey;
      if (!isControlAlt) return;
      if (!modelReadyRef.current) {
        showToast("Caricamento modello in corso, attendere...", "info");
        return;
      }
      if (holdToSpeakRef.current) {
        startFnRef.current();
      } else {
        if (activeTranscriptionRef.current) {
          stopFnRef.current();
        } else {
          startFnRef.current();
        }
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (holdToSpeakRef.current && (e.key === "Control" || e.key === "Alt")) {
        stopFnRef.current();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, []);

  // ── TRANSCRIPTION CONTROL ──
  const transcriptionLockRef = useRef(false);
  const transcriptionCooldownRef = useRef(0);
  const startTranscription = useCallback(async (isTest?: boolean) => {
    if (activeTranscriptionRef.current || transcriptionLockRef.current) return;
    const now = Date.now();
    if (now - transcriptionCooldownRef.current < 300) return;
    transcriptionCooldownRef.current = now;
    transcriptionLockRef.current = true;
    isTestRecordingRef.current = !!isTest;
    if (!modelReady) {
      showToast("Caricamento modello in corso, attendere...", "info");
      transcriptionLockRef.current = false;
      return;
    }

    const status = modelStatus[selectedModel] || { downloaded: false };
    if (selectedProvider !== "cloud" && !status.downloaded) {
      showToast(
        "Modello non scaricato. Scarica prima il modello dalla tab IA.",
        "error"
      );
      transcriptionLockRef.current = false;
      return;
    }

    activeTranscriptionRef.current = true;
    if (isTest) setActiveTranscription(true);

    try {
      await window.__TAURI__.core.invoke("send_to_python", {
        message: JSON.stringify({
          command: "transcribe",
          model: selectedModel,
          device:
            settings?.selectedDevice === "default"
              ? null
              : settings?.selectedDevice,
          language: selectedLanguage,
          provider: selectedProvider,
        }),
      });
    } catch (err) {
      console.error("[REC] start error:", err);
      activeTranscriptionRef.current = false;
      setActiveTranscription(false);
    } finally {
      transcriptionLockRef.current = false;
    }
  }, [modelReady, modelStatus, selectedModel, selectedProvider, selectedLanguage, settings]);

  startFnRef.current = startTranscription;

  const stopTranscription = useCallback(() => {
    if (!activeTranscriptionRef.current) return;
    activeTranscriptionRef.current = false;
    transcriptionLockRef.current = false;
    try {
      void window.__TAURI__.core.invoke("stop_python").catch((err: unknown) => {
        console.error("[REC] stop error:", err);
      });
    } catch (err) {
      console.error("[REC] stop error:", err);
    }
    setActiveTranscription(false);
  }, []);
  stopFnRef.current = stopTranscription;

  // ── MODEL ACTION ──
  const handleModelAction = useCallback(
    async (modelId: string) => {
      const status = modelStatus[modelId] || { downloaded: false, loading: false };
      if (!status.downloaded) {
        setModelStatus((prev) => ({
          ...prev,
          [modelId]: { ...prev[modelId], loading: true },
        }));
        try {
          await window.__TAURI__.core.invoke("send_to_python", {
            message: JSON.stringify({ command: "download", model: modelId }),
          });
        } catch (err) {
          console.error("[download] Error:", err);
        }
      } else {
        setSelectedModel(modelId);
        if (settings) {
          persistSettings({ model: modelId });
        }
      }
    },
    [modelStatus, settings, persistSettings]
  );

  // ── PROVIDER TOGGLE ──
  const handleProviderToggle = useCallback(
    async (provider: Provider) => {
      setSelectedProvider(provider);
      if (settings) {
        await persistSettings({ provider });
      }
      showToast(`Provider: ${provider === "cloud" ? "Cloud" : "Locale"}`, "info");
      try {
        await window.__TAURI__.core.invoke("send_to_python", {
          message: JSON.stringify({
            command: "set_provider",
            provider,
            model: selectedModel,
          }),
        });
      } catch (err) {
        console.warn("[provider] Error:", err);
      }
    },
    [settings, persistSettings, selectedModel, showToast]
  );

  // ── HOLD TO SPEAK CHANGE (auto‑salvataggio immediato) ──
  const handleHoldToSpeakChange = useCallback(
    async (value: boolean) => {
      setHoldToSpeak(value);
      await persistSettings({ holdToSpeak: value });
    },
    [persistSettings]
  );

  // ── WIDGET MODE CHANGE (auto‑salvataggio immediato) ──
  const handleWidgetModeChange = useCallback(
    async (value: string) => {
      setWidgetMode(value);
      await persistSettings({ widgetMode: value });
    },
    [persistSettings]
  );

  // ── SETTING CHANGE (from SistemaTab) ──
  const handleSettingChange = useCallback(
    async (key: string, value: string | boolean) => {
      if (!settings) return;

      const updated = { ...settings, [key]: value };
      setSettings(updated);

      // Handle special cases that need immediate side effects
      if (key === "selectedLanguage") {
        setSelectedLanguage(value as string);
      }
      if (key === "computeDevice") {
        setComputeDevice(value as string);
        try {
          await window.__TAURI__.core.invoke("send_to_python", {
            message: JSON.stringify({
              command: "set_device",
              device: value,
            }),
          });
        } catch (err) {
          console.warn("[gpu] set_device error:", err);
        }
      }
      if (key === "groqApiKey") {
        try {
          await window.__TAURI__.core.invoke("send_to_python", {
            message: JSON.stringify({
              command: "set_groq_api_key",
              api_key: value,
            }),
          });
        } catch (err) {
          console.warn("[groq] API key update error:", err);
        }
      }

      await persistSettings(updated);
      showToast("Impostazioni salvate", "info");
    },
    [settings, persistSettings, showToast]
  );

  // ── SAVE HOTKEY (salva hotkey + holdToSpeak + widgetMode) ──
  const handleSaveHotkey = useCallback(async (slot: "primary" | "secondary" = "primary", secondaryValue?: string) => {
    const input = document.getElementById(slot === "primary" ? "hotkey" : "secondary-hotkey") as HTMLInputElement;
    if (!input) return;
    const value = input.value;

    const isControlAlt =
      value === "CommandOrControl+Alt+..." || value === "Control+Alt+...";
    if (isControlAlt) {
      input.value = "CommandOrControl+Alt";
    }

    await persistSettings({
      ...(slot === "primary" ? { hotkey: input.value } : { secondaryHotkey: secondaryValue ?? input.value }),
      holdToSpeak,
      widgetMode,
    });
    showToast("Impostazioni salvate con successo", "success");
  }, [persistSettings, showToast, holdToSpeak, widgetMode]);

  // ── EXPORT ──
  const exportText = useCallback(
    (format: "txt" | "srt") => {
      if (!transcriptionText.trim()) {
        showToast("Nessuna trascrizione da esportare!", "info");
        return;
      }

      let content: string;
      let filename: string;

      if (format === "txt") {
        content = transcriptionText;
        filename = "trascrizione.txt";
      } else {
        content = convertToSRT(transcriptionText);
        filename = "trascrizione.srt";
      }

      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      showToast(`File ${filename} esportato con successo`, "success");
    },
    [transcriptionText, showToast]
  );

  const clearText = useCallback(() => {
    setTranscriptionText("");
  }, []);

  // ── HISTORY CLICK (copy) ──
  const handleHistoryClick = useCallback(
    async (text: string, index: number) => {
      try {
        await navigator.clipboard.writeText(text);
        showToast("Testo copiato negli appunti", "success");
      } catch (err) {
        console.error("[cronologia] Errore copia:", err);
      }
    },
    [showToast]
  );

  // ── TAB CHANGE ──
  const handleTabChange = useCallback(
    (tab: string) => {
      setActiveTab(tab);
      if (tab === "home") {
        loadStats();
        reloadGroqUsage();
      }
      if (tab === "ia") {
        loadSettings();
        reloadGroqUsage();
      }
      if (tab === "tasti") {
        loadSettings();
      }
      if (tab === "cronologia") {
        loadHistory();
      }
    },
    [loadStats, reloadGroqUsage, loadSettings, loadHistory]
  );

  // ── DOWNLOAD CLOSE ──
  const handleDownloadClose = useCallback(() => {
    setDownloadInfo(null);
  }, []);

  // ── RENDER ──
  return (
    <div
      className="app-canvas flex h-dvh w-dvw"
    >
      <Sidebar activeTab={activeTab} onTabChange={handleTabChange} appVersion={appVersion} />

      <main className="flex-1 px-5 py-6 overflow-y-auto flex flex-col relative">
        {activeTab === "home" && (
          <HomeTab
            stats={stats}
            settings={settings}
            selectedProvider={selectedProvider}
            selectedModel={selectedModel}
            transcriptionStatus={transcriptionStatus}
            groqUsage={groqUsage}

          />
        )}

        {activeTab === "ia" && (
          <IATab
            models={WHISPER_MODELS}
            selectedModel={selectedModel}
            selectedProvider={selectedProvider}
            modelStatus={modelStatus}
            groqUsage={groqUsage}
            onProviderToggle={handleProviderToggle}
            onModelAction={handleModelAction}
          />
        )}

        {activeTab === "tasti" && (
          <TastiTab
            settings={settings}
            isRecording={isHotkeyRecording}
            recordedKeys={recordedKeys}
            holdToSpeak={holdToSpeak}
            widgetMode={widgetMode}
            onStartRecording={startRecording}
            onStopRecording={stopRecording}
            onHoldToSpeakChange={handleHoldToSpeakChange}
            onWidgetModeChange={handleWidgetModeChange}
            onSave={handleSaveHotkey}
            onSecondarySave={(value) => handleSaveHotkey("secondary", value)}
            onHotkeyChange={(val) => recordedKeys}
          />
        )}

        {activeTab === "cronologia" && (
          <CronologiaTab
            entries={historyEntries}
            onClear={clearHistory}
            onEntryClick={handleHistoryClick}
          />
        )}

        {activeTab === "sistema" && (
          <SistemaTab
            settings={settings}
            devices={audioDevices}
            appVersion={appVersion}
            gpuStatus={gpuStatus}
            onSettingChange={handleSettingChange}
          />
        )}
      </main>

      <LoadingOverlay show={showLoading} />
      <DownloadPopup download={downloadInfo} onClose={handleDownloadClose} />
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </div>
  );
}
