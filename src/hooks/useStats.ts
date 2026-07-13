import { useState, useCallback } from "react";
import type { AppStats } from "../types";

export function useStats() {
  const [stats, setStats] = useState<AppStats>({
    total_words: 0,
    avg_wpm: 0,
    total_time: 0,
  });

  const loadStats = useCallback(async () => {
    if (!window.__TAURI__?.core?.invoke) return;

    let lastError: unknown;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const s = (await window.__TAURI__.core.invoke("get_stats")) as AppStats;
        setStats({
          total_words: s.total_words ?? 0,
          avg_wpm: s.avg_wpm ?? 0,
          total_time: s.total_time ?? 0,
        });
        return;
      } catch (err) {
        lastError = err;
        if (attempt < 2) await new Promise((r) => setTimeout(r, 500));
      }
    }
    console.warn("[stats] Impossibile caricare stats dopo 3 tentativi:", lastError);
  }, []);

  return { stats, loadStats };
}
