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

  const clearHistory = useCallback(async (): Promise<boolean> => {
    if (!window.__TAURI__?.core?.invoke) return false;
    const clearId = ++clearIdRef.current;
    ++mutationIdRef.current;
    ++loadIdRef.current;

    let cleared = false;
    try {
      await enqueueMutation(async () => {
        try {
          await window.__TAURI__.core.invoke("clear_history");
          if (clearId !== clearIdRef.current) return;
          setEntries([]);
          cleared = true;
        } catch (err) {
          if (clearId !== clearIdRef.current) return;
          console.error("[cronologia] Errore cancellazione:", err);
        }
      });
    } catch (err) {
      console.error("[cronologia] Errore coda cancellazione:", err);
    }
    return cleared;
  }, [enqueueMutation]);

  const deleteHistoryEntry = useCallback(
    async (entry: TranscriptionEntry, index: number): Promise<boolean> => {
      if (!window.__TAURI__?.core?.invoke) return false;
      ++mutationIdRef.current;
      ++loadIdRef.current;

      let deleted = false;
      try {
        await enqueueMutation(async () => {
          try {
            const result = await window.__TAURI__.core.invoke("delete_history_entry", {
              index,
              text: entry.text,
              timestamp: entry.timestamp,
              wordCount: entry.word_count,
            });
            if (result !== true) return;

            deleted = true;
            setEntries((previous) => {
              const matches = (candidate: TranscriptionEntry) => (
                candidate.text === entry.text
                && candidate.timestamp === entry.timestamp
                && candidate.word_count === entry.word_count
              );
              const indexedEntry = previous[index];
              const removeIndex = indexedEntry && matches(indexedEntry)
                ? index
                : previous.findIndex(matches);
              if (removeIndex < 0) return previous;
              return previous.filter((_, candidateIndex) => candidateIndex !== removeIndex);
            });
          } catch (err) {
            console.error("[cronologia] Errore cancellazione voce:", err);
          }
        });
      } catch (err) {
        console.error("[cronologia] Errore coda cancellazione voce:", err);
      }
      return deleted;
    },
    [enqueueMutation],
  );

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

  return {
    entries,
    setEntries,
    loadHistory,
    clearHistory,
    deleteHistoryEntry,
    saveTranscription,
  };
}
