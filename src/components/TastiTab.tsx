import { useEffect, useRef } from "react";
import { useHotkey } from "../hooks/useHotkey";
import type { AppSettings } from "../types";

interface TastiTabProps {
  settings: AppSettings | null;
  isRecording: boolean;
  recordedKeys: string;
  holdToSpeak: boolean;
  widgetMode: string;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onHoldToSpeakChange: (value: boolean) => void;
  onWidgetModeChange: (value: string) => void;
  onSave: () => void;
  onSecondarySave: (value: string) => void;
}

export default function TastiTab({
  settings,
  isRecording,
  recordedKeys,
  holdToSpeak,
  widgetMode,
  onStartRecording,
  onStopRecording,
  onHoldToSpeakChange,
  onWidgetModeChange,
  onSave,
  onSecondarySave,
}: TastiTabProps) {
  const lastSavedHotkeyRef = useRef<string | null>(null);
  const secondary = useHotkey();
  const secondarySavedRef = useRef<string | null>(null);
  // Sync recordedKeys with hotkey display
  useEffect(() => {
    if (recordedKeys) {
      const input = document.getElementById("hotkey") as HTMLInputElement;
      if (input) {
        input.value = recordedKeys;
      }
    }
  }, [recordedKeys]);

  // Auto‑save when a hotkey recording completes with a valid combination
  useEffect(() => {
    if (
      !isRecording &&
      recordedKeys &&
      !recordedKeys.includes("...") &&
      lastSavedHotkeyRef.current !== recordedKeys
    ) {
      lastSavedHotkeyRef.current = recordedKeys;
      onSave();
    }
  }, [isRecording, recordedKeys, onSave]);

  useEffect(() => {
    if (secondary.recordedKeys) {
      const input = document.getElementById("secondary-hotkey") as HTMLInputElement;
      if (input) input.value = secondary.recordedKeys;
    }
  }, [secondary.recordedKeys]);

  useEffect(() => {
    if (
      !secondary.isRecording &&
      secondary.recordedKeys &&
      !secondary.recordedKeys.includes("...") &&
      secondarySavedRef.current !== secondary.recordedKeys
    ) {
      secondarySavedRef.current = secondary.recordedKeys;
      onSecondarySave(secondary.recordedKeys);
    }
  }, [secondary.isRecording, secondary.recordedKeys, onSecondarySave]);

  const currentHotkey = settings?.hotkey || "CommandOrControl+Space";

  return (
    <div className="tab-slide-in max-w-[700px] mx-auto w-full">
      <header className="mb-6"><h1 className="page-title m-0">Scorciatoie</h1><p className="m-0 mt-2 text-[.84rem] text-[var(--muted)]">Configura il gesto che avvia la dettatura anche fuori dall'app.</p></header>

      <div className="panel p-5 mb-6">
        {/* Hotkey */}
        <h3 className="text-[0.65rem] text-[var(--quiet)] font-bold uppercase tracking-[0.1em] m-0 mb-3">
          Scorciatoia
        </h3>

        <div className="mb-6 flex flex-col gap-2">
          <label className="text-[0.9rem] font-bold text-[#ccc]" htmlFor="hotkey">
            Hotkey di Attivazione
          </label>
          <div className="flex gap-2.5 items-center">
            <div className="flex-1 relative">
              <input
                type="text"
                id="hotkey"
                placeholder={isRecording ? "Registrazione..." : "Premi i tasti..."}
                readOnly
                className={`field-control w-full font-mono font-bold text-[0.95rem] tracking-[0.08em] px-3.5 py-3 rounded-xl outline-none ${
                  recordedKeys
                    ? "bg-[rgba(255,140,0,0.08)] border-[rgba(255,140,0,0.25)] text-[var(--primary-orange)]"
                    : "bg-[rgba(0,0,0,0.6)] border-[rgba(255,255,255,0.08)] text-[#eee]"
                } border cursor-default`}
                aria-label="Combinazione tasti attuale"
                defaultValue={currentHotkey}
              />
            </div>
            <button
              id="record-btn"
              className={`w-11 h-11 flex items-center justify-center rounded-xl border cursor-pointer transition-all duration-200 ${
                isRecording
                  ? "bg-[rgba(255,68,68,0.15)] border-[rgba(255,68,68,0.3)] text-[#ff4444]"
                  : "bg-[#222] border-[rgba(255,255,255,0.08)] text-[#777] hover:text-[#ccc]"
              }`}
              aria-label="Registra nuova combinazione tasti"
              onClick={isRecording ? onStopRecording : onStartRecording}
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="w-5 h-5"
                aria-hidden="true"
              >
                <rect x="2" y="4" width="20" height="16" rx="2" />
                <path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M6 16h12" />
              </svg>
            </button>
          </div>
          <p className="text-[0.84rem] leading-5 text-[var(--muted)] m-0">
            Premi il pulsante per registrare una nuova combinazione. Supporta anche i tasti laterali
            del mouse (Mouse4/Mouse5).
          </p>
        </div>

        <div className="mb-6 flex flex-col gap-2">
          <label className="text-[0.9rem] font-bold text-[#ccc]" htmlFor="secondary-hotkey">
            Seconda hotkey (opzionale)
          </label>
          <div className="flex gap-2.5 items-center">
            <input
              type="text"
              id="secondary-hotkey"
              placeholder={secondary.isRecording ? "Registrazione..." : "Nessuna"}
              readOnly
              defaultValue={settings?.secondaryHotkey || ""}
               className="field-control flex-1 w-full font-mono font-bold text-[0.95rem] tracking-[0.08em] px-3.5 py-3 rounded-xl outline-none bg-[rgba(0,0,0,0.6)] border border-[rgba(255,255,255,0.08)] text-[#eee]"
              aria-label="Seconda combinazione tasti"
            />
            <button
              id="secondary-record-btn"
              className={`w-11 h-11 flex items-center justify-center rounded-xl border cursor-pointer transition-all duration-200 ${
                secondary.isRecording
                  ? "bg-[rgba(255,68,68,0.15)] border-[rgba(255,68,68,0.3)] text-[#ff4444]"
                  : "bg-[#222] border-[rgba(255,255,255,0.08)] text-[#777] hover:text-[#ccc]"
              }`}
              aria-label="Registra seconda combinazione tasti"
              onClick={secondary.isRecording ? secondary.stopRecording : secondary.startRecording}
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="w-5 h-5"
                aria-hidden="true"
              >
                <rect x="2" y="4" width="20" height="16" rx="2" />
                <path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M6 16h12" />
              </svg>
            </button>
          </div>
          <p className="text-[0.84rem] leading-5 text-[var(--muted)] m-0">
            Entrambe le shortcut avviano e fermano la dettatura allo stesso modo.
          </p>
        </div>

        <hr className="border-none h-px bg-[rgba(255,255,255,0.08)] my-5" />

        {/* Widget Visibility */}
        <h3 className="text-[0.65rem] text-[var(--quiet)] font-bold uppercase tracking-[0.1em] m-0 mb-3">
          Widget
        </h3>

        <div className="mb-6">
          <label className="text-[0.9rem] font-bold text-[#ccc] block mb-1">
            Visibilità widget
          </label>
          <p className="text-[0.84rem] leading-5 text-[var(--muted)] mb-3">
            Il widget appare quando la console principale è nascosta; puoi limitarlo alla sola attività di registrazione.
          </p>
          <div className="flex gap-3">
            <button
              className={`flex-1 py-2.5 px-4 rounded-xl border cursor-pointer transition-all duration-200 font-bold text-[0.85rem] ${
                widgetMode === "always"
                  ? "bg-[rgba(255,140,0,0.15)] border-[rgba(255,140,0,0.35)] text-[var(--primary-orange)]"
                  : "bg-[rgba(0,0,0,0.4)] border-[rgba(255,255,255,0.08)] text-[#888] hover:text-[#ccc] border-[rgba(255,255,255,0.12)]"
              }`}
              onClick={() => onWidgetModeChange("always")}
            >
              <div className="flex items-center gap-2 justify-center">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="w-4 h-4 flex-shrink-0"
                >
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="12" cy="12" r="2" />
                </svg>
                <span>Sempre visibile</span>
              </div>
            </button>
            <button
              className={`flex-1 py-2.5 px-4 rounded-xl border cursor-pointer transition-all duration-200 font-bold text-[0.85rem] ${
                widgetMode === "recording"
                  ? "bg-[rgba(255,140,0,0.15)] border-[rgba(255,140,0,0.35)] text-[var(--primary-orange)]"
                  : "bg-[rgba(0,0,0,0.4)] border-[rgba(255,255,255,0.08)] text-[#888] hover:text-[#ccc] border-[rgba(255,255,255,0.12)]"
              }`}
              onClick={() => onWidgetModeChange("recording")}
            >
              <div className="flex items-center gap-2 justify-center">
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="w-4 h-4 flex-shrink-0"
                >
                  <circle cx="12" cy="12" r="3" />
                  <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
                </svg>
                <span>Solo durante registrazione</span>
              </div>
            </button>
          </div>
        </div>

        <hr className="border-none h-px bg-[rgba(255,255,255,0.08)] my-5" />

        {/* Hold to Speak */}
        <h3 className="text-[0.65rem] text-[var(--quiet)] font-bold uppercase tracking-[0.1em] m-0 mb-3">
          Modalità
        </h3>

        <div className="mb-6 flex flex-row justify-between items-center">
          <div className="flex-1 min-w-0">
            <label
              className="text-[0.9rem] font-bold text-[#ccc] block mb-1"
              htmlFor="hold-to-speak"
            >
              Tieni premuto per parlare
            </label>
            <p className="text-[0.84rem] leading-5 text-[var(--muted)] m-0">
              Se disattivato, premi la scorciatoia una volta per avviare la registrazione e premila
              di nuovo per interromperla.
            </p>
          </div>
          <label className="relative inline-block w-11 h-6 cursor-pointer ml-4 flex-shrink-0">
            <input
              type="checkbox"
              id="hold-to-speak"
              className="opacity-0 w-0 h-0"
              checked={holdToSpeak}
              onChange={(e) => onHoldToSpeakChange(e.target.checked)}
            />
            <span
              className="absolute inset-0 rounded-[30px] transition-colors duration-300"
              style={{ backgroundColor: holdToSpeak ? "var(--primary-orange)" : "#333" }}
            >
              <span
                className="absolute h-[18px] w-[18px] left-[3px] bottom-[3px] bg-white rounded-full transition-transform duration-300"
                style={{
                  transform: holdToSpeak ? "translateX(20px)" : "translateX(0)",
                }}
              />
            </span>
          </label>
        </div>

      </div>
    </div>
  );
}
