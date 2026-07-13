import { useState, useCallback } from "react";
import type { AudioDeviceInfo } from "../types";

export function useAudioDevices() {
  const [devices, setDevices] = useState<AudioDeviceInfo[]>([]);

  const loadAudioDevices = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;

    try {
      const result = (await window.__TAURI__.core.invoke("get_audio_devices")) as AudioDeviceInfo[];
      setDevices(result || []);
    } catch (err) {
      console.error("[audio] Errore caricamento dispositivi:", err);
      setDevices([]);
    }
  }, []);

  return { devices, loadAudioDevices };
}
