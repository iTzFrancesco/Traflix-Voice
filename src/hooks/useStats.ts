import { useState, useCallback, useRef } from "react";
import type { AppStats } from "../types";

function normalizeStats(value: Partial<AppStats> | null | undefined): AppStats {
  return {
    total_words: value?.total_words ?? 0,
    avg_wpm: value?.avg_wpm ?? 0,
    total_time: value?.total_time ?? 0,
  };
}

export function useStats() {
  const [stats, setStats] = useState<AppStats>({
    total_words: 0,
    avg_wpm: 0,
    total_time: 0,
  });
  const updateQueueRef = useRef(Promise.resolve());

  const enqueueStatsOperation = useCallback(
    (operation: () => Promise<unknown>) => {
      const scheduled = updateQueueRef.current.then(operation);
      updateQueueRef.current = scheduled.then(
        () => undefined,
        () => undefined,
      );
      return scheduled;
    },
    [],
  );

  const loadStats = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;

    await enqueueStatsOperation(async () => {
      let lastError: unknown;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const s = (await window.__TAURI__.core.invoke("get_stats")) as AppStats;
          setStats(normalizeStats(s));
          return;
        } catch (err) {
          lastError = err;
          if (attempt < 2) await new Promise((r) => setTimeout(r, 500));
        }
      }
      console.warn("[stats] Impossibile caricare stats dopo 3 tentativi:", lastError);
    });
  }, [enqueueStatsOperation]);

  const updateStats = useCallback(
    async (words: number, wpm: number, timeDelta: number) => {
      if (!window.__TAURI__?.core?.invoke) return null;

      return enqueueStatsOperation(async () => {
        const updated = (await window.__TAURI__.core.invoke("update_stats", {
          words,
          wpm,
          timeDelta,
        })) as AppStats;
        const normalized = normalizeStats(updated);
        setStats(normalized);
        return normalized;
      });
    },
    [enqueueStatsOperation],
  );

  const runStatsMutation = useCallback(
    (mutation: () => Promise<unknown>) => {
      // Clear operations are queued behind every already-submitted stats
      // update and become the barrier before all later updates. This prevents
      // an old result from being written after clear_history completes.
      return enqueueStatsOperation(mutation);
    },
    [enqueueStatsOperation],
  );

  return { stats, loadStats, updateStats, runStatsMutation };
}
