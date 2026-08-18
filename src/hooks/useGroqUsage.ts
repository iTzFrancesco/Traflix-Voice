import { useCallback, useState } from "react";
import type { GroqUsage } from "../types";

const EMPTY_USAGE = (date: string): GroqUsage => ({
  date,
  audio_seconds: 0,
  audio_seconds_hourly: 0,
  hourly_reset: "",
});

function readUsage(): GroqUsage | null {
  try {
    const raw = localStorage.getItem("groq_usage");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GroqUsage;
    const today = new Date().toISOString().split("T")[0];
    return parsed.date === today ? parsed : null;
  } catch {
    return null;
  }
}

export function useGroqUsage() {
  const [groqUsage, setGroqUsage] = useState<GroqUsage | null>(null);

  const reloadGroqUsage = useCallback(() => {
    setGroqUsage(readUsage());
  }, []);

  const recordGroqUsage = useCallback((durationSecs: number) => {
    if (!durationSecs) return;

    try {
      const today = new Date().toISOString().split("T")[0];
      const raw = localStorage.getItem("groq_usage");
      let usage: GroqUsage;

      if (raw) {
        try {
          usage = JSON.parse(raw) as GroqUsage;
        } catch {
          usage = EMPTY_USAGE(today);
        }
      } else {
        usage = EMPTY_USAGE(today);
      }

      if (usage.date !== today) usage = EMPTY_USAGE(today);

      const now = Date.now();
      const thisHour = Math.floor(now / 3600000);
      if (usage._lastHour !== thisHour) {
        usage.audio_seconds_hourly = 0;
        usage._lastHour = thisHour;
      }

      usage.audio_seconds = Math.round((usage.audio_seconds || 0) + durationSecs);
      usage.audio_seconds_hourly = Math.round(
        (usage.audio_seconds_hourly || 0) + durationSecs
      );
      const nextHour = (Math.floor(now / 3600000) + 1) * 3600000;
      usage.hourly_reset = new Date(nextHour).toLocaleTimeString("it-IT", {
        hour: "2-digit",
        minute: "2-digit",
      });

      localStorage.setItem("groq_usage", JSON.stringify(usage));
      setGroqUsage(usage);
    } catch {
      // Usage tracking must never interfere with transcription.
    }
  }, []);

  return { groqUsage, reloadGroqUsage, recordGroqUsage };
}
