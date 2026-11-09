export interface AppSettings {
  hotkey: string;
  secondaryHotkey?: string;
  model: string;
  autoPaste?: boolean | null;
  keepClipboardResult?: boolean;
  minimizeTray: boolean;
  selectedDevice: string;
  microphoneKeepReady?: boolean;
  selectedLanguage: string;
  computeDevice: string;
  holdToSpeak: boolean;
  groqApiKey: string;
  provider: string;
  widgetMode?: string;
  cloudCorrectionEnabled?: boolean;
  cloudVocabulary?: string;
  cloudSpeechFilter?: boolean;
}

export interface AppStats {
  total_words: number;
  avg_wpm: number;
  total_time: number;
}

export interface GroqUsage {
  date: string;
  audio_seconds: number;
  audio_seconds_hourly: number;
  hourly_reset: string;
  _lastHour?: number;
  llmInputTokens?: number;
  llmOutputTokens?: number;
  llmInputTokensHourly?: number;
  llmOutputTokensHourly?: number;
}

export interface TranscriptionEntry {
  text: string;
  timestamp: string;
  word_count: number;
}

export interface AudioDeviceInfo {
  id: string;
  name: string;
}

export interface WhisperModel {
  id: string;
  name: string;
  size: string;
  ram: string;
  speed: number;
  quality: number;
  tag: string;
  description: string;
}

export interface PythonEvent {
  status: string;
  message?: string;
  text?: string;
  duration?: number;
  value?: number;
  model?: string;
  progress?: number;
  current_device?: string;
  device_name?: string;
  cuda_available?: boolean;
  available?: boolean;
  model_loaded?: boolean;
  provider?: string;
}

export type Provider = "local" | "cloud";
export type ComputeDevice = "cpu" | "cuda" | "auto";
export type ToastType = "success" | "error" | "info";

export interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

export const DEFAULT_LOCAL_MODEL = "parakeet-ultra";

export const WHISPER_MODELS: WhisperModel[] = [
  {
    id: "parakeet-ultra",
    name: "Parakeet Ultra",
    size: "~740 MB",
    ram: "Variabile (CPU/GPU)",
    speed: 4,
    quality: 5,
    tag: "Consigliato",
    description: "Modello post-addestrato per una trascrizione più accurata. Supporta italiano e altre 24 lingue, con CPU/GPU automatici.",
  },
];
