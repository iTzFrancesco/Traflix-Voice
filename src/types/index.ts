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
  cloudPostProcessing?: boolean;
  removeFillers?: boolean;
  dictionaryEntries?: DictionaryEntry[];
}

export interface DictionaryEntry {
  id: string;
  spoken: string;
  replacement: string;
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
  request_id?: string;
}

export type Provider = "local" | "cloud";
export type ComputeDevice = "cpu" | "cuda" | "auto";
export type ToastType = "success" | "error" | "info";

export interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

export const WHISPER_MODELS: WhisperModel[] = [
  {
    id: "base",
    name: "Base",
    size: "145 MB",
    ram: "~1 GB",
    speed: 4,
    quality: 2,
    tag: "Veloce",
    description: "Leggero e reattivo. Buona scelta per dettatura rapida con hardware limitato.",
  },
  {
    id: "small",
    name: "Small",
    size: "466 MB",
    ram: "~2 GB",
    speed: 3,
    quality: 3,
    tag: "Consigliato",
    description: "Miglior equilibrio velocità/precisione. Ottimo per dettatura quotidiana in italiano.",
  },
];
