export interface AppSettings {
  hotkey: string;
  secondaryHotkey?: string;
  model: string;
  autoPaste?: boolean | null;
  minimizeTray: boolean;
  selectedDevice: string;
  selectedLanguage: string;
  computeDevice: string;
  holdToSpeak: boolean;
  groqApiKey: string;
  provider: string;
  widgetMode?: string;
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
}

export type Provider = "local" | "cloud";
export type ComputeDevice = "cpu" | "cuda" | "auto";
export type ToastType = "success" | "error" | "info";

export interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

export const DEFAULT_LOCAL_MODEL = "parakeet-tdt-0.6b-v3-int8";

export const WHISPER_MODELS: WhisperModel[] = [
  {
    id: "parakeet-tdt-0.6b-v3-int8",
    name: "Parakeet TDT 0.6B V3",
    size: "~670 MB",
    ram: "~1.5 GB",
    speed: 5,
    quality: 4,
    tag: "Consigliato",
    description: "Modello NVIDIA rapidissimo su CPU con ottimo italiano. Richiede il pacchetto extra sherpa-onnx.",
  },
];
