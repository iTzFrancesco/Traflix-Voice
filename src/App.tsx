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
import { convertToSRT } from "./lib/export";
import { useHotkey } from "./hooks/useHotkey";
import { useAudioDevices } from "./hooks/useAudioDevices";
import { useGroqUsage } from "./hooks/useGroqUsage";
import { useHistory } from "./hooks/useHistory";
import { usePythonOutput } from "./hooks/usePythonOutput";
import { useSettings } from "./hooks/useSettings";
import { useStats } from "./hooks/useStats";
import type {
  AppSettings,
  Provider,
  Toast,
} from "./types";
import { WHISPER_MODELS } from "./types";

const TRANSCRIPTION_COOLDOWN_MS = 80;

// ─── APP ──────────────────────────────────────────────────────────────────────

// DEV mode badge
const IS_DEV = import.meta.env.DEV;

export default function App() {
  const {
    settings,
    setSettings,
    loadSettings: loadStoredSettings,
    persistSettings: persistStoredSettings,
  } = useSettings();
  const { stats, loadStats, updateStats, runStatsMutation } = useStats();
  const {
    entries: historyEntries,
    loadHistory,
    clearHistory: clearStoredHistory,
    saveTranscription,
  } = useHistory();
  const { devices: audioDevices, loadAudioDevices } = useAudioDevices();
  const { groqUsage, reloadGroqUsage, recordGroqUsage } = useGroqUsage();

  // ── STATE ──
  const [activeTab, setActiveTab] = useState("home");
  const [selectedModel, setSelectedModel] = useState("small");
  const [selectedProvider, setSelectedProvider] = useState<Provider>("local");
  const [selectedLanguage, setSelectedLanguage] = useState("it");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [appVersion, setAppVersion] = useState("");
  const [holdToSpeak, setHoldToSpeak] = useState(false);
  const [widgetMode, setWidgetMode] = useState("always");

  const toastIdRef = useRef(0);
  const startSoundRef = useRef<HTMLAudioElement | null>(null);
  const stopSoundRef = useRef<HTMLAudioElement | null>(null);
  const hotkeyListenersRef = useRef<(() => void)[]>([]);
  const holdToSpeakRef = useRef(false);
  const startFnRef = useRef<(isTest?: boolean) => Promise<void>>(async () => {});
  const stopFnRef = useRef<() => void>(() => {});
  holdToSpeakRef.current = holdToSpeak;

  // ── HOTKEY RECORDING ──
  const {
    isRecording: isHotkeyRecording,
    recordedKeys,
    startRecording,
    stopRecording,
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

  const {
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
  } = usePythonOutput({
    selectedProvider,
    showToast,
    updateStats,
    saveTranscription,
    recordGroqUsage,
  });

  // ── SETTINGS ──
  const loadSettings = useCallback(async (): Promise<AppSettings | null> => {
    const loaded = await loadStoredSettings();
    if (!loaded) return null;

    setSelectedModel(loaded.model || "small");
    setSelectedProvider((loaded.provider as Provider) || "local");
    setSelectedLanguage(loaded.selectedLanguage || "it");
    setHoldToSpeak(loaded.holdToSpeak ?? false);
    setWidgetMode(loaded.widgetMode ?? "always");
    return loaded;
  }, [loadStoredSettings]);

  const persistSettings = useCallback(
    (overrides?: Partial<AppSettings>) => persistStoredSettings(overrides),
    [persistStoredSettings]
  );

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
    mergeModelStatus(
      Object.fromEntries(results.map(({ id, exists }) => [id, exists as boolean]))
    );
  }, [mergeModelStatus]);

  const clearHistory = useCallback(async () => {
    await runStatsMutation(() => clearStoredHistory());
    await loadStats();
  }, [clearStoredHistory, loadStats, runStatsMutation]);

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
      reloadGroqUsage();

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

  // Python events are handled by a dedicated hook so App remains a composition module.

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
  // Duplicate presses are already blocked by the active/lock refs. Keep a
  // short guard only for the initial edge; stop clears it so a new cloud
  // recording can start immediately after the previous one is ended.
  const transcriptionCooldownRef = useRef(0);
  const startTranscription = useCallback(async (isTest?: boolean) => {
    if (activeTranscriptionRef.current || transcriptionLockRef.current) return;
    const now = Date.now();
    if (now - transcriptionCooldownRef.current < TRANSCRIPTION_COOLDOWN_MS) return;
    transcriptionCooldownRef.current = now;
    transcriptionLockRef.current = true;
    isTestRecordingRef.current = !!isTest;
    if (!modelReadyRef.current) {
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
    } finally {
      transcriptionLockRef.current = false;
    }
  }, [modelStatus, selectedModel, selectedProvider, selectedLanguage, settings]);

  startFnRef.current = startTranscription;

  const stopTranscription = useCallback(() => {
    if (!activeTranscriptionRef.current) return;
    activeTranscriptionRef.current = false;
    transcriptionLockRef.current = false;
    transcriptionCooldownRef.current = 0;
    try {
      void window.__TAURI__.core.invoke("stop_python").catch((err: unknown) => {
        console.error("[REC] stop error:", err);
      });
    } catch (err) {
      console.error("[REC] stop error:", err);
    }
  }, []);
  stopFnRef.current = stopTranscription;

  // ── MODEL ACTION ──
  const handleModelAction = useCallback(
    async (modelId: string) => {
      const status = modelStatus[modelId] || { downloaded: false, loading: false };
      if (!status.downloaded) {
        updateModelStatus(modelId, { loading: true });
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
    [modelStatus, settings, persistSettings, updateModelStatus]
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

  const clearText = clearTranscriptionText;

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
    clearDownloadInfo();
  }, [clearDownloadInfo]);

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
