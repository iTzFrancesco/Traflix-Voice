import { useState, useCallback } from "react";
import type { TranscriptionEntry } from "../types";

export function useHistory() {
  const [entries, setEntries] = useState<TranscriptionEntry[]>([]);

  const loadHistory = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;

    try {
      const result = (await window.__TAURI__.core.invoke("get_history")) as TranscriptionEntry[];
      setEntries(result || []);
    } catch (err) {
      console.error("[cronologia] Errore caricamento:", err);
      setEntries([]);
    }
  }, []);

  const clearHistory = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;

    try {
      await window.__TAURI__.core.invoke("clear_history");
      setEntries([]);
    } catch (err) {
      console.error("[cronologia] Errore cancellazione:", err);
    }
  }, []);

  const saveTranscription = useCallback(
    async (text: string, timestamp: string, wordCount: number) => {
      if (!window.__TAURI__?.core?.invoke) return;

      try {
        await window.__TAURI__.core.invoke("save_transcription", {
          text,
          timestamp,
          wordCount,
        });
      } catch (err) {
        console.error("[cronologia] Errore salvataggio:", err);
      }
    },
    []
  );

  return { entries, setEntries, loadHistory, clearHistory, saveTranscription };
}
