import { useCallback, useEffect, useState } from "react";
import MobileDashboard, {
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
      await invoke("save_settings", { settings: normalized });
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

  useEffect(() => {
    if (IS_DEV) document.title = "Traflix Voice [DEV]";

    let cancelled = false;
    const init = async () => {
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
    };

    void init();
    return () => {
      cancelled = true;
    };
  }, [loadHistory, loadSettings, loadStats, reloadGroqUsage]);

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
    />
  );
}
