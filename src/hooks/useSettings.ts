import { useState, useCallback, useRef } from "react";
import type { AppSettings } from "../types";

export function useSettings() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const loadedRef = useRef(false);

  const loadSettings = useCallback(async (): Promise<boolean> => {
    if (!window.__TAURI__?.core?.invoke) {
      console.warn("[settings] __TAURI__ not available");
      return false;
    }

    try {
      const s = (await window.__TAURI__.core.invoke("load_settings")) as AppSettings | null;
      if (!s || typeof s.hotkey === "undefined") {
        console.warn("[settings] invalid data from load_settings:", JSON.stringify(s));
        return false;
      }
      console.log("[settings] loaded provider:", s.provider, "model:", s.model, "hotkey:", s.hotkey);
      setSettings(s);
      loadedRef.current = true;
      return true;
    } catch (err) {
      console.warn("[settings] load_settings error:", err);
      return false;
    }
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

  const updateSettings = useCallback((partial: Partial<AppSettings>) => {
    setSettings((prev) => (prev ? { ...prev, ...partial } : prev));
  }, []);

  const retryLoadSettings = useCallback(async (): Promise<boolean> => {
    for (let attempt = 0; attempt < 4; attempt++) {
      if (attempt > 0) {
        console.warn(`[settings] retrying loadSettings (attempt ${attempt + 1}/4)...`);
        await new Promise((r) => setTimeout(r, 250 * (attempt + 1)));
      }
      const ok = await loadSettings();
      if (ok) {
        console.log("[settings] loaded successfully on attempt", attempt + 1);
        return true;
      }
    }
    return false;
  }, [loadSettings]);

  return {
    settings,
    setSettings,
    loadSettings,
    persistSettings,
    updateSettings,
    retryLoadSettings,
    loadedRef,
  };
}
