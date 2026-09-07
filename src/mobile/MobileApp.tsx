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
  const mobileUpdateRef = useRef<MobileUpdateInfo | null>(null);
  const autoUpdateAttemptedTagRef = useRef<string | null>(null);
  const autoUpdatePermissionPendingRef = useRef(false);
  const installerOpenRef = useRef(false);
  const appReadyRef = useRef(false);
  const mobileDataRefreshInFlightRef = useRef<Promise<void> | null>(null);
  const lastDataRefreshAtRef = useRef(0);
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

  const loadSettings = useCallback(async (): Promise<AppSettings | null> => {
    const loaded = await loadStoredSettings();
    if (!loaded) return null;

    setHoldToSpeak(loaded.holdToSpeak ?? false);

    try {
      await Promise.all([
        invoke("plugin:voice-runtime|setRecordingMode", {
          mode: loaded.holdToSpeak ? "hold_to_speak" : "toggle",
        }),
        invoke("plugin:voice-runtime|setTranscriptionLanguage", {
          language: loaded.selectedLanguage || "it",
        }),
        invoke("plugin:voice-runtime|setGroqApiKey", {
          apiKey: loaded.groqApiKey || "",
        }),
      ]);
    } catch (error) {
      console.error("[android-settings] initial sync error:", error);
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

  const refreshMobileData = useCallback((): Promise<void> => {
    if (!window.__TAURI__?.core?.invoke) return Promise.resolve();
    const now = Date.now();
    const inFlight = mobileDataRefreshInFlightRef.current;
    if (inFlight) return inFlight;
    if (now - lastDataRefreshAtRef.current < 750) return Promise.resolve();

    lastDataRefreshAtRef.current = now;
    let refreshPromise: Promise<void>;
    refreshPromise = Promise.allSettled([
      loadSettings(),
      loadStats(),
      loadHistory(),
      reloadGroqUsage(),
      loadAppVersion(),
    ]).then(() => undefined).finally(() => {
      if (mobileDataRefreshInFlightRef.current === refreshPromise) {
        mobileDataRefreshInFlightRef.current = null;
      }
    });
    mobileDataRefreshInFlightRef.current = refreshPromise;
    return refreshPromise;
  }, [loadAppVersion, loadHistory, loadSettings, loadStats, reloadGroqUsage]);

  const persistSettings = useCallback(
    (overrides?: Partial<AppSettings>) => persistStoredSettings(overrides),
    [persistStoredSettings],
  );

  const clearHistory = useCallback(async () => {
    await runStatsMutation(() => clearStoredHistory());
    await loadStats();
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
        }
        if (key === "selectedLanguage" && typeof value === "string") {
          await invoke("plugin:voice-runtime|setTranscriptionLanguage", {
            language: value,
          });
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
    if (IS_DEV) document.title = "Traflix Voice [DEV]";

    let cancelled = false;
    const init = async () => {
      try {
        await refreshMobileData();
        if (!cancelled) appReadyRef.current = true;
      } catch (error) {
        console.error("[android] startup data load failed:", error);
      }
    };

    void init();
    const updateTimer = window.setTimeout(() => {
      if (!cancelled) void checkMobileUpdate(true);
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
      } catch (error) {
        console.error("[android-settings] recording mode error:", error);
      }
    },
    [invoke, persistSettings],
  );

  const handleHistoryClick = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (error) {
      console.error("[cronologia] Errore copia:", error);
    }
  }, []);

  return (
    <MobileDashboard
      settings={settings}
      stats={stats}
      historyEntries={historyEntries}
      groqUsage={groqUsage}
      transcriptionStatus="idle"
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
