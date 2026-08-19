import { useState, useCallback, useRef } from "react";
import type { TranscriptionEntry } from "../types";

export function useHistory() {
  const [entries, setEntries] = useState<TranscriptionEntry[]>([]);
  const loadIdRef = useRef(0);
  const mutationIdRef = useRef(0);
  const clearIdRef = useRef(0);
  const mutationQueueRef = useRef(Promise.resolve());

  const enqueueMutation = useCallback(
    (mutation: () => Promise<unknown>) => {
      const scheduled = mutationQueueRef.current.then(mutation);
      mutationQueueRef.current = scheduled.then(
        () => undefined,
        () => undefined,
      );
      return scheduled;
    },
    [],
  );

  const loadHistory = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;
    const loadId = ++loadIdRef.current;
    const mutationId = mutationIdRef.current;

    try {
      const result = (await enqueueMutation(async () => (
        (await window.__TAURI__.core.invoke("get_history")) as TranscriptionEntry[]
      ))) as TranscriptionEntry[];
      if (
        loadId !== loadIdRef.current ||
        mutationId !== mutationIdRef.current
      ) return;
      setEntries(result || []);
    } catch (err) {
      if (
        loadId !== loadIdRef.current ||
        mutationId !== mutationIdRef.current
      ) return;
      console.error("[cronologia] Errore caricamento:", err);
      setEntries([]);
    }
  }, [enqueueMutation]);

  const clearHistory = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;
    const clearId = ++clearIdRef.current;
    ++mutationIdRef.current;
    ++loadIdRef.current;

    await enqueueMutation(async () => {
      try {
        await window.__TAURI__.core.invoke("clear_history");
        if (clearId !== clearIdRef.current) return;
        setEntries([]);
      } catch (err) {
        if (clearId !== clearIdRef.current) return;
        console.error("[cronologia] Errore cancellazione:", err);
      }
    });
  }, [enqueueMutation]);

  const saveTranscription = useCallback(
    async (text: string, timestamp: string, wordCount: number) => {
      if (!window.__TAURI__?.core?.invoke) return;
      const clearId = clearIdRef.current;
      ++mutationIdRef.current;

      await enqueueMutation(async () => {
        // A clear invalidates saves that were already queued. Saves submitted
        // after clear are queued behind the clear operation and remain valid.
        if (clearId !== clearIdRef.current) return;
        try {
          await window.__TAURI__.core.invoke("save_transcription", {
            text,
            timestamp,
            wordCount,
          });
          if (clearId !== clearIdRef.current) return;
          const entry: TranscriptionEntry = { text, timestamp, word_count: wordCount };
          setEntries((previous) => [entry, ...previous].slice(0, 50));
        } catch (err) {
          if (clearId !== clearIdRef.current) return;
          console.error("[cronologia] Errore salvataggio:", err);
        }
      });
    },
    [enqueueMutation]
  );

  return { entries, setEntries, loadHistory, clearHistory, saveTranscription };
}
