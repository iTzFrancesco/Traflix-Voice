import { useState, useCallback } from "react";
import type { AppSettings } from "../types";

export function useSettings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const loadSettings = useCallback(async (): Promise<AppSettings | null> => {
    if (!window.__TAURI__?.core?.invoke) return null;

    for (let attempt = 0; attempt < 4; attempt++) {
      if (attempt > 0) {
        console.warn(
          `[settings] retrying loadSettings (attempt ${attempt + 1}/4)...`
        );
        await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
      }

      try {
        const loaded = (await window.__TAURI__.core.invoke(
          "load_settings"
        )) as AppSettings | null;
        if (!loaded || typeof loaded.hotkey === "undefined") {
          console.warn("[settings] invalid data:", JSON.stringify(loaded));
          continue;
        }
        console.log(
          "[settings] loaded provider:",
          loaded.provider,
          "model:",
          loaded.model,
          "hotkey:",
          loaded.hotkey
        );
        setSettings(loaded);
        return loaded;
      } catch (err) {
        console.warn("[settings] error:", err);
      }
    }

    return null;
  }, []);

  const persistSettings = useCallback(
    async (overrides?: Partial<AppSettings>): Promise<AppSettings | null> => {
      if (!window.__TAURI__?.core?.invoke || !settings) return null;

      const merged: AppSettings = { ...settings, ...overrides };
      try {
        await window.__TAURI__.core.invoke("save_settings", { settings: merged });
        setSettings(merged);
        return merged;
      } catch (err) {
        console.error("[settings] save error:", err);
        return null;
      }
    },
    [settings]
  );

  return {
    settings,
    setSettings,
    loadSettings,
    persistSettings,
  };
}
