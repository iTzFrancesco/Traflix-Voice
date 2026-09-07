import { useCallback, useRef, useState } from "react";
import type { GroqUsage } from "../types";

const EMPTY_USAGE = (
  date: string,
  hour = Math.floor(Date.now() / 3600000),
): GroqUsage => ({
  date,
  audio_seconds: 0,
  audio_seconds_hourly: 0,
  hourly_reset: "",
  _lastHour: hour,
});

const IS_ANDROID_RUNTIME =
  typeof navigator !== "undefined" && /Android/i.test(navigator.userAgent);

function localDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function normalizeUsage(
  parsed: GroqUsage | null | undefined,
  now = Date.now()
): GroqUsage | null {
  if (!parsed || typeof parsed !== "object") return null;
  const today = localDateKey(new Date(now));
  if (parsed.date !== today) return null;

  const usage = { ...parsed };
  const audioSeconds = Number(usage.audio_seconds);
  const hourlySeconds = Number(usage.audio_seconds_hourly);
  usage.audio_seconds = Number.isFinite(audioSeconds) && audioSeconds >= 0
    ? audioSeconds
    : 0;
  usage.audio_seconds_hourly = Number.isFinite(hourlySeconds) && hourlySeconds >= 0
    ? hourlySeconds
    : 0;
  const thisHour = Math.floor(now / 3600000);
  const hourChanged = usage._lastHour !== thisHour;
  if (hourChanged) {
    usage.audio_seconds_hourly = 0;
    usage._lastHour = thisHour;
  }
  if (hourChanged || !usage.hourly_reset) {
    const nextHour = (thisHour + 1) * 3600000;
    usage.hourly_reset = new Date(nextHour).toLocaleTimeString("it-IT", {
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return usage;
}

function readUsage(now = Date.now()): GroqUsage | null {
  try {
    const raw = localStorage.getItem("groq_usage");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as GroqUsage;
    return normalizeUsage(parsed, now);
  } catch {
    return null;
  }
}

function normalizeExternalUsage(value: unknown): GroqUsage | null {
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  return normalizeUsage({
    date: typeof record.date === "string" ? record.date : "",
    audio_seconds: Number(record.audio_seconds),
    audio_seconds_hourly: Number(
      record.audio_seconds_hourly ?? record.audioSecondsHourly,
    ),
    hourly_reset: typeof record.hourly_reset === "string" ? record.hourly_reset : "",
  });
}

export function useGroqUsage() {
  const [groqUsage, setGroqUsage] = useState<GroqUsage | null>(null);
  const usageRef = useRef<GroqUsage | null>(null);

  const reloadGroqUsage = useCallback(async (): Promise<void> => {
    if (IS_ANDROID_RUNTIME && window.__TAURI__?.core?.invoke) {
      try {
        const value = await window.__TAURI__.core.invoke("get_groq_usage");
        const usage = normalizeExternalUsage(value);
        usageRef.current = usage;
        setGroqUsage(usage);
      } catch {
        const usage = readUsage();
        usageRef.current = usage;
        setGroqUsage(usage);
      }
      return;
    }
    const usage = readUsage();
    usageRef.current = usage;
    setGroqUsage(usage);
  }, []);

  const recordGroqUsage = useCallback((durationSecs: number) => {
    if (!Number.isFinite(durationSecs) || durationSecs <= 0) return;

    try {
      const now = Date.now();
      const today = localDateKey(new Date(now));
      // The result path already owns the in-memory value. Read localStorage
      // only on the first event or after a reload, avoiding a parse per cloud
      // transcription while preserving durable writes below.
      let usage = usageRef.current || readUsage(now);
      const currentHour = Math.floor(now / 3600000);
      usage = normalizeUsage(usage, now)
        || normalizeUsage(EMPTY_USAGE(today, currentHour), now)!;

      usage.audio_seconds = Math.round((usage.audio_seconds || 0) + durationSecs);
      usage.audio_seconds_hourly = Math.round(
        (usage.audio_seconds_hourly || 0) + durationSecs
      );

      localStorage.setItem("groq_usage", JSON.stringify(usage));
      usageRef.current = usage;
      setGroqUsage(usage);
    } catch {
      // Usage tracking must never interfere with transcription.
    }
  }, []);

  return { groqUsage, reloadGroqUsage, recordGroqUsage };
}
