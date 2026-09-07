import { useCallback, useEffect, useRef, useState } from "react";
import MobileDashboard, {
  type MobileUpdateInfo,
  type MobileUpdateState,
  type MobileSettingsScreen,
} from "./MobileDashboard";
import "./mobile.css";
import { useGroqUsage } from "../hooks/useGroqUsage";
import { useHistory } from "../hooks/useHistory";
import { useSettings } from "../hooks/useSettings";
import { useStats } from "../hooks/useStats";
import type { AppSettings } from "../types";

const IS_DEV = import.meta.env.DEV;
const MOBILE_VERSION_PATTERN = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
const RESUME_UPDATE_CHECK_INTERVAL_MS = 60_000;
const RUNTIME_STATUS_POLL_INTERVAL_MS = 1_000;
const MOBILE_RUNTIME_STATES = new Set([
  "idle",
  "starting",
  "listening",
  "processing",
  "ready",
  "result",
  "error",
  "rate_limit",
]);

type MobileStartupState = "loading" | "ready" | "error";
type MobileNativeSettings = {
  recordingMode: "hold_to_speak" | "toggle";
  language: string;
  groqApiKey: string;
};

function normalizeRuntimeState(value: unknown): string | null {
  return typeof value === "string" && MOBILE_RUNTIME_STATES.has(value)
    ? value
    : null;
}

function MobileStartup({
  state,
  message,
  onRetry,
}: {
  state: MobileStartupState;
  message: string;
  onRetry: () => void;
}) {
  const isLoading = state === "loading";
  return (
    <main className="mobile-startup" role="status" aria-live="polite" aria-busy={isLoading}>
      <span className="mobile-startup-mark" aria-hidden="true" />
      <h1>{isLoading ? "Preparazione" : "Traflix Voice non è pronto"}</h1>
      <p>{message}</p>
      {!isLoading && (
        <button type="button" className="mobile-primary-button" onClick={onRetry}>
          Riprova
        </button>
      )}
    </main>
  );
}

function normalizeMobileVersion(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const version = value.trim();
  return MOBILE_VERSION_PATTERN.test(version) ? version : null;
}

export default function MobileApp() {
  const {
    settings,
    setSettings,
    loadSettings: loadStoredSettings,
    persistSettings: persistStoredSettings,
  } = useSettings();
  const { stats, loadStats, runStatsMutation } = useStats();
  const {
    entries: historyEntries,
    loadHistory,
    clearHistory: clearStoredHistory,
  } = useHistory();
  const { groqUsage, reloadGroqUsage } = useGroqUsage();

  const [appVersion, setAppVersion] = useState("");
  const [holdToSpeak, setHoldToSpeak] = useState(false);
  const [mobileUpdate, setMobileUpdate] = useState<MobileUpdateInfo | null>(null);
  const [mobileUpdateState, setMobileUpdateState] = useState<MobileUpdateState>("idle");
  const [mobileUpdateError, setMobileUpdateError] = useState("");
  const [androidSettingsError, setAndroidSettingsError] = useState("");
  const [startupState, setStartupState] = useState<MobileStartupState>("loading");
  const [startupError, setStartupError] = useState("");
  const [transcriptionStatus, setTranscriptionStatus] = useState("idle");
  const mobileUpdateRef = useRef<MobileUpdateInfo | null>(null);
  const autoUpdateAttemptedTagRef = useRef<string | null>(null);
  const autoUpdatePermissionPendingRef = useRef(false);
  const installerOpenRef = useRef(false);
  const appReadyRef = useRef(false);
  const mobileDataRefreshInFlightRef = useRef<Promise<boolean> | null>(null);
  const lastDataRefreshAtRef = useRef(0);
  const syncedNativeSettingsRef = useRef<Partial<MobileNativeSettings>>({});
  const lastRuntimeStateRef = useRef<string | null>(null);
  const runtimeStateErrorLoggedRef = useRef(false);
  const runtimeStateRefreshInFlightRef = useRef<Promise<void> | null>(null);
  const mobileUpdateCheckInFlightRef = useRef<Promise<void> | null>(null);
  const lastMobileUpdateCheckAtRef = useRef(0);

  const invoke = useCallback(
    (command: string, args?: Record<string, unknown>) =>
      window.__TAURI__?.core?.invoke(command, args),
    [],
  );

  const loadAppVersion = useCallback(async (): Promise<void> => {
    if (!window.__TAURI__?.app?.getVersion) return;
    try {
      const version = normalizeMobileVersion(await window.__TAURI__.app.getVersion());
      if (version) setAppVersion(version);
    } catch {
      // The dashboard can operate without a version string in dev shells.
    }
  }, []);

  const loadRuntimeState = useCallback((): Promise<void> => {
    if (!window.__TAURI__?.core?.invoke) return Promise.resolve();
    const inFlight = runtimeStateRefreshInFlightRef.current;
    if (inFlight) return inFlight;

    let refreshPromise: Promise<void>;
    refreshPromise = (async () => {
      try {
        const value: unknown = await invoke("plugin:voice-runtime|getRuntimeState");
        const rawState =
          value !== null && typeof value === "object" && "state" in value
            ? value.state
            : null;
        const state = normalizeRuntimeState(rawState);
        if (state && lastRuntimeStateRef.current !== state) {
          lastRuntimeStateRef.current = state;
          setTranscriptionStatus(state);
        }
        runtimeStateErrorLoggedRef.current = false;
      } catch (error) {
        // Older preview builds do not expose the optional snapshot command.
        if (!runtimeStateErrorLoggedRef.current) {
          console.debug("[android-runtime] state snapshot unavailable", error);
          runtimeStateErrorLoggedRef.current = true;
        }
      }
    })().finally(() => {
      if (runtimeStateRefreshInFlightRef.current === refreshPromise) {
        runtimeStateRefreshInFlightRef.current = null;
      }
    });
    runtimeStateRefreshInFlightRef.current = refreshPromise;
    return refreshPromise;
  }, [invoke]);

  const loadSettings = useCallback(async (): Promise<AppSettings | null> => {
    const loaded = await loadStoredSettings();
    if (!loaded) return null;

    setHoldToSpeak(loaded.holdToSpeak ?? false);

    const nativeSettings: MobileNativeSettings = {
      recordingMode: loaded.holdToSpeak ? "hold_to_speak" : "toggle",
      language: loaded.selectedLanguage || "it",
      groqApiKey: loaded.groqApiKey || "",
    };
    const previous = syncedNativeSettingsRef.current;
    const syncOperations: Array<{
      key: keyof MobileNativeSettings;
      promise: Promise<unknown>;
    }> = [];

    if (previous.recordingMode !== nativeSettings.recordingMode) {
      syncOperations.push({
        key: "recordingMode",
        promise: Promise.resolve(invoke("plugin:voice-runtime|setRecordingMode", {
          mode: nativeSettings.recordingMode,
        })),
      });
    }
    if (previous.language !== nativeSettings.language) {
      syncOperations.push({
        key: "language",
        promise: Promise.resolve(invoke("plugin:voice-runtime|setTranscriptionLanguage", {
          language: nativeSettings.language,
        })),
      });
    }
    if (previous.groqApiKey !== nativeSettings.groqApiKey) {
      syncOperations.push({
        key: "groqApiKey",
        promise: Promise.resolve(invoke("plugin:voice-runtime|setGroqApiKey", {
          apiKey: nativeSettings.groqApiKey,
        })),
      });
    }

    if (syncOperations.length > 0) {
      const results = await Promise.allSettled(syncOperations.map(({ promise }) => promise));
      const next = { ...previous };
      let nativeSyncOk = true;
      results.forEach((result, index) => {
        const operation = syncOperations[index];
        if (result.status === "fulfilled") {
          if (operation.key === "recordingMode") {
            next.recordingMode = nativeSettings.recordingMode;
          } else if (operation.key === "language") {
            next.language = nativeSettings.language;
          } else {
            next.groqApiKey = nativeSettings.groqApiKey;
          }
        } else {
          nativeSyncOk = false;
          console.error(`[android-settings] initial sync error (${operation.key}):`, result.reason);
        }
      });
      syncedNativeSettingsRef.current = next;
      if (!nativeSyncOk) return null;
    }

    if (loaded.provider !== "cloud") {
      const normalized = { ...loaded, provider: "cloud" as const };
      try {
        await invoke("save_settings", { settings: normalized });
      } catch (error) {
        console.error("[android-settings] provider normalization error:", error);
      }
      setSettings(normalized);
      return normalized;
    }

    return loaded;
  }, [invoke, loadStoredSettings, setSettings]);

  const refreshMobileData = useCallback((): Promise<boolean> => {
    if (!window.__TAURI__?.core?.invoke) return Promise.resolve(true);
    const now = Date.now();
    const inFlight = mobileDataRefreshInFlightRef.current;
    if (inFlight) return inFlight;
    if (now - lastDataRefreshAtRef.current < 750) {
      return Promise.resolve(true);
    }

    lastDataRefreshAtRef.current = now;
    let refreshPromise: Promise<boolean>;
    refreshPromise = Promise.allSettled([
      loadSettings(),
      loadStats(),
      loadHistory(),
      reloadGroqUsage(),
      loadAppVersion(),
      loadRuntimeState(),
    ]).then(([settingsResult]) => (
      settingsResult.status === "fulfilled" && settingsResult.value !== null
    )).finally(() => {
      if (mobileDataRefreshInFlightRef.current === refreshPromise) {
        mobileDataRefreshInFlightRef.current = null;
      }
    });
    mobileDataRefreshInFlightRef.current = refreshPromise;
    return refreshPromise;
  }, [loadAppVersion, loadHistory, loadRuntimeState, loadSettings, loadStats, reloadGroqUsage]);

  const persistSettings = useCallback(
    (overrides?: Partial<AppSettings>) => persistStoredSettings(overrides),
    [persistStoredSettings],
  );

  const clearHistory = useCallback(async () => {
    const cleared = await runStatsMutation(() => clearStoredHistory());
    await loadStats();
    if (cleared !== true) throw new Error("Impossibile cancellare la cronologia");
  }, [clearStoredHistory, loadStats, runStatsMutation]);

  const handleSettingChange = useCallback(
    async (key: string, value: string | boolean) => {
      if (!settings) return;

      const updated = { ...settings, [key]: value };
      setSettings(updated);

      try {
        if (key === "groqApiKey") {
          await invoke("plugin:voice-runtime|setGroqApiKey", {
            apiKey: typeof value === "string" ? value : "",
          });
          syncedNativeSettingsRef.current = {
            ...syncedNativeSettingsRef.current,
            groqApiKey: typeof value === "string" ? value : "",
          };
        }
        if (key === "selectedLanguage" && typeof value === "string") {
          await invoke("plugin:voice-runtime|setTranscriptionLanguage", {
            language: value,
          });
          syncedNativeSettingsRef.current = {
            ...syncedNativeSettingsRef.current,
            language: value,
          };
        }
      } catch (error) {
        console.error("[android-settings] setting sync error:", error);
      }

      await persistSettings(updated);
    }, [invoke, persistSettings, setSettings, settings],
  );

  const openAndroidSettings = useCallback(
    async (screen: MobileSettingsScreen) => {
      setAndroidSettingsError("");
      if (!window.__TAURI__?.core?.invoke) {
        setAndroidSettingsError("I collegamenti alle impostazioni Android funzionano nell’app installata.");
        return;
      }

      try {
        await invoke("plugin:voice-runtime|openAndroidSettings", { screen });
      } catch (error) {
        console.error("[android-settings] open error:", error);
        const message =
          error && typeof error === "object" && "message" in error
            ? String((error as { message?: unknown }).message ?? "")
            : error instanceof Error
              ? error.message
              : String(error);
        setAndroidSettingsError(message || "Impossibile aprire le impostazioni Android.");
      }
    },
    [invoke],
  );

  const installMobileUpdate = useCallback(
    async (update: MobileUpdateInfo | null = mobileUpdateRef.current, automatic = false) => {
      if (!update || !window.__TAURI__?.core?.invoke) return;
      if (automatic && autoUpdateAttemptedTagRef.current === update.tag) return;

      if (automatic) autoUpdateAttemptedTagRef.current = update.tag;
      setMobileUpdateState("installing");
      setMobileUpdateError("");
      try {
        const result = (await invoke("plugin:mobile-update|installMobileUpdate", {
          tag: update.tag,
        })) as { status?: string } | null;
        if (result?.status === "permission_required") {
          autoUpdateAttemptedTagRef.current = null;
          autoUpdatePermissionPendingRef.current = automatic;
          setMobileUpdateState("permission_required");
          return;
        }
        autoUpdatePermissionPendingRef.current = false;
        installerOpenRef.current = true;
        setMobileUpdateState("installer_opened");
      } catch (error) {
        autoUpdatePermissionPendingRef.current = false;
        installerOpenRef.current = false;
        const message = error instanceof Error ? error.message : String(error);
        setMobileUpdateError(message || "Aggiornamento non riuscito");
        setMobileUpdateState("error");
      }
    },
    [invoke],
  );

  const checkMobileUpdate = useCallback(
    (automatic = false, force = false): Promise<void> => {
      if (!window.__TAURI__?.core?.invoke) return Promise.resolve();
      const inFlight = mobileUpdateCheckInFlightRef.current;
      if (inFlight) return inFlight;
      const now = Date.now();
      if (
        !force &&
        !automatic &&
        now - lastMobileUpdateCheckAtRef.current < RESUME_UPDATE_CHECK_INTERVAL_MS
      ) return Promise.resolve();

      lastMobileUpdateCheckAtRef.current = now;
      let checkPromise: Promise<void>;
      checkPromise = (async () => {
        setMobileUpdateState("checking");
        setMobileUpdateError("");
        try {
          const result = (await invoke("plugin:mobile-update|checkMobileUpdate")) as Partial<MobileUpdateInfo> | null;
          const currentVersion = normalizeMobileVersion(result?.currentVersion);
          const updateVersion = normalizeMobileVersion(result?.version);
          if (currentVersion) setAppVersion(currentVersion);
          if (
            result?.available === true &&
            typeof result.tag === "string" &&
            updateVersion !== null &&
            currentVersion !== null &&
            typeof result.name === "string" &&
            typeof result.notes === "string" &&
            typeof result.publishedAt === "string" &&
            typeof result.assetName === "string" &&
            typeof result.size === "number"
          ) {
            const update = {
              ...result,
              version: updateVersion,
              currentVersion,
            } as MobileUpdateInfo;
            mobileUpdateRef.current = update;
            setMobileUpdate(update);
            setMobileUpdateState("available");
            if (automatic) void installMobileUpdate(update, true);
          } else {
            mobileUpdateRef.current = null;
            setMobileUpdate(null);
            setMobileUpdateState("idle");
          }
        } catch (error) {
          console.warn("[android-update] check failed:", error);
          setMobileUpdateState("idle");
        }
      })().finally(() => {
        if (mobileUpdateCheckInFlightRef.current === checkPromise) {
          mobileUpdateCheckInFlightRef.current = null;
        }
      });
      mobileUpdateCheckInFlightRef.current = checkPromise;
      return checkPromise;
    },
    [installMobileUpdate, invoke],
  );

  const retryStartup = useCallback(async () => {
    setStartupState("loading");
    setStartupError("");
    lastDataRefreshAtRef.current = 0;
    const ready = await refreshMobileData();
    if (ready) {
      appReadyRef.current = true;
      setStartupState("ready");
      return;
    }
    setStartupError("Impossibile caricare le impostazioni Android. Verifica l’installazione e riprova.");
    setStartupState("error");
  }, [refreshMobileData]);

  useEffect(() => {
    const retryPendingAutomaticUpdate = () => {
      if (document.visibilityState !== "visible" || !autoUpdatePermissionPendingRef.current) return;
      autoUpdatePermissionPendingRef.current = false;
      void checkMobileUpdate(true, true);
    };

    document.addEventListener("visibilitychange", retryPendingAutomaticUpdate);
    window.addEventListener("focus", retryPendingAutomaticUpdate);
    return () => {
      document.removeEventListener("visibilitychange", retryPendingAutomaticUpdate);
      window.removeEventListener("focus", retryPendingAutomaticUpdate);
    };
  }, [checkMobileUpdate]);

  useEffect(() => {
    const refreshOnResume = () => {
      if (document.visibilityState !== "visible") return;
      void refreshMobileData();

      const now = Date.now();
      if (installerOpenRef.current) {
        installerOpenRef.current = false;
        void checkMobileUpdate(false, true);
      } else if (
        appReadyRef.current &&
        now - lastMobileUpdateCheckAtRef.current >= RESUME_UPDATE_CHECK_INTERVAL_MS
      ) {
        void checkMobileUpdate(true);
      }
    };

    document.addEventListener("visibilitychange", refreshOnResume);
    window.addEventListener("focus", refreshOnResume);
    window.addEventListener("pageshow", refreshOnResume);
    return () => {
      document.removeEventListener("visibilitychange", refreshOnResume);
      window.removeEventListener("focus", refreshOnResume);
      window.removeEventListener("pageshow", refreshOnResume);
    };
  }, [checkMobileUpdate, refreshMobileData]);

  useEffect(() => {
    if (!window.__TAURI__?.core?.invoke) return;
    const pollRuntimeState = () => {
      if (document.visibilityState === "visible" && appReadyRef.current) {
        void loadRuntimeState();
      }
    };
    const timer = window.setInterval(pollRuntimeState, RUNTIME_STATUS_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadRuntimeState]);

  useEffect(() => {
    if (IS_DEV) document.title = "Traflix Voice [DEV]";

    let cancelled = false;
    const init = async () => {
      try {
        const ready = await refreshMobileData();
        if (!cancelled) {
          if (ready) {
            appReadyRef.current = true;
            setStartupState("ready");
          } else {
            setStartupError("Impossibile caricare le impostazioni Android. Verifica l’installazione e riprova.");
            setStartupState("error");
          }
        }
      } catch (error) {
        console.error("[android] startup data load failed:", error);
        if (!cancelled) {
          setStartupError("Impossibile avviare Traflix Voice. Riprova.");
          setStartupState("error");
        }
      }
    };

    void init();
    const updateTimer = window.setTimeout(() => {
      if (!cancelled && appReadyRef.current) void checkMobileUpdate(true);
    }, 1500);
    return () => {
      cancelled = true;
      window.clearTimeout(updateTimer);
    };
  }, [checkMobileUpdate, refreshMobileData]);

  const handleMobileHoldToSpeakChange = useCallback(
    async (value: boolean) => {
      setHoldToSpeak(value);
      await persistSettings({ holdToSpeak: value, provider: "cloud" });
      try {
        await invoke("plugin:voice-runtime|setRecordingMode", {
          mode: value ? "hold_to_speak" : "toggle",
        });
        syncedNativeSettingsRef.current = {
          ...syncedNativeSettingsRef.current,
          recordingMode: value ? "hold_to_speak" : "toggle",
        };
      } catch (error) {
        console.error("[android-settings] recording mode error:", error);
      }
    },
    [invoke, persistSettings],
  );

  const handleHistoryClick = useCallback(async (text: string): Promise<boolean> => {
    try {
      if (!navigator.clipboard) return false;
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      console.error("[cronologia] Errore copia:", error);
      return false;
    }
  }, []);

  if (startupState !== "ready") {
    return (
      <MobileStartup
        state={startupState}
        message={startupState === "loading" ? "Caricamento dei dati locali…" : startupError}
        onRetry={() => void retryStartup()}
      />
    );
  }

  return (
    <MobileDashboard
      settings={settings}
      stats={stats}
      historyEntries={historyEntries}
      groqUsage={groqUsage}
      transcriptionStatus={transcriptionStatus}
      appVersion={appVersion}
      holdToSpeak={holdToSpeak}
      onHoldToSpeakChange={handleMobileHoldToSpeakChange}
      onSettingChange={handleSettingChange}
      onClearHistory={clearHistory}
      onHistoryClick={handleHistoryClick}
      onOpenAndroidSettings={openAndroidSettings}
      androidSettingsError={androidSettingsError}
      onReloadUsage={reloadGroqUsage}
      mobileUpdate={mobileUpdate}
      mobileUpdateState={mobileUpdateState}
      mobileUpdateError={mobileUpdateError}
      onInstallMobileUpdate={installMobileUpdate}
    />
  );
}
