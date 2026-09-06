import { useCallback, useEffect, useState } from "react";
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

  const invoke = useCallback(
    (command: string, args?: Record<string, unknown>) =>
      window.__TAURI__?.core?.invoke(command, args),
    [],
  );

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
      try {
        await invoke("plugin:voice-runtime|openAndroidSettings", { screen });
      } catch (error) {
        console.error("[android-settings] open error:", error);
      }
    },
    [invoke],
  );

  const checkMobileUpdate = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;

    setMobileUpdateState("checking");
    setMobileUpdateError("");
    try {
      const result = (await invoke("plugin:voice-runtime|checkMobileUpdate")) as Partial<MobileUpdateInfo> | null;
      if (
        result?.available === true &&
        typeof result.tag === "string" &&
        typeof result.version === "string" &&
        typeof result.currentVersion === "string" &&
        typeof result.name === "string" &&
        typeof result.notes === "string" &&
        typeof result.publishedAt === "string" &&
        typeof result.assetName === "string" &&
        typeof result.size === "number"
      ) {
        setMobileUpdate(result as MobileUpdateInfo);
        setMobileUpdateState("available");
      } else {
        setMobileUpdate(null);
        setMobileUpdateState("idle");
      }
    } catch (error) {
      console.warn("[android-update] check failed:", error);
      setMobileUpdateState("idle");
    }
  }, [invoke]);

  const installMobileUpdate = useCallback(async () => {
    if (!mobileUpdate || !window.__TAURI__?.core?.invoke) return;

    setMobileUpdateState("installing");
    setMobileUpdateError("");
    try {
      const result = (await invoke("plugin:voice-runtime|installMobileUpdate", {
        tag: mobileUpdate.tag,
      })) as { status?: string } | null;
      if (result?.status === "permission_required") {
        setMobileUpdateState("permission_required");
        return;
      }
      setMobileUpdateState("installer_opened");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setMobileUpdateError(message || "Aggiornamento non riuscito");
      setMobileUpdateState("error");
    }
  }, [invoke, mobileUpdate]);

  useEffect(() => {
    if (IS_DEV) document.title = "Traflix Voice [DEV]";

    let cancelled = false;
    const init = async () => {
      try {
        await loadSettings();
        loadStats();
        reloadGroqUsage();

        if (window.__TAURI__?.app?.getVersion) {
          try {
            setAppVersion(await window.__TAURI__.app.getVersion());
          } catch {
            // The dashboard can operate without a version string in dev shells.
          }
        }

        if (!cancelled) await loadHistory();
      } catch (error) {
        console.error("[android] startup data load failed:", error);
      }
    };

    void init();
    const updateTimer = window.setTimeout(() => {
      if (!cancelled) void checkMobileUpdate();
    }, 1500);
    return () => {
      cancelled = true;
      window.clearTimeout(updateTimer);
    };
  }, [checkMobileUpdate, loadHistory, loadSettings, loadStats, reloadGroqUsage]);

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
      onReloadUsage={reloadGroqUsage}
      mobileUpdate={mobileUpdate}
      mobileUpdateState={mobileUpdateState}
      mobileUpdateError={mobileUpdateError}
      onInstallMobileUpdate={installMobileUpdate}
    />
  );
}
