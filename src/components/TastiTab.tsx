import { useEffect } from "react";
import type { AppSettings } from "../types";

interface TastiTabProps {
  settings: AppSettings | null;
  isRecording: boolean;
  recordedKeys: string;
  holdToSpeak: boolean;
  onStartRecording: () => void;
  onStopRecording: () => void;
  onHoldToSpeakChange: (value: boolean) => void;
  onSave: () => void;
  onHotkeyChange: (value: string) => void;
}

export default function TastiTab({
  settings,
  isRecording,
  recordedKeys,
  holdToSpeak,
  onStartRecording,
  onStopRecording,
  onHoldToSpeakChange,
  onSave,
  onHotkeyChange,
}: TastiTabProps) {
  // Sync recordedKeys with hotkey display
  useEffect(() => {
    if (recordedKeys) {
      const input = document.getElementById("hotkey") as HTMLInputElement;
      if (input) {
        input.value = recordedKeys;
      }
    }
  }, [recordedKeys]);

  const currentHotkey = settings?.hotkey || "CommandOrControl+Space";

  const handleSave = () => {
    const input = document.getElementById("hotkey") as HTMLInputElement;
    if (!input) return;

    const value = input.value;
    const isControlAlt =
      value === "CommandOrControl+Alt+..." || value === "Control+Alt+...";

    if (value.includes("...") && !isControlAlt) {
      alert(
        "La scorciatoia non è completa! Premi un tasto finale (es. Spazio o una lettera) mentre tieni premuto Control/Alt."
      );
      return;
    }

    if (isControlAlt) {
      input.value = "CommandOrControl+Alt";
    }

    onSave();
  };

  return (
    <div className="tab-slide-in">
      <h2
        className="text-[#eee] text-[1.4rem] font-bold m-0 mb-6"
        style={{
          background: "linear-gradient(135deg, #ff4444 0%, #ff8c00 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        Scorciatoie
      </h2>

      <div className="bg-[rgba(34,34,34,0.6)] p-6 rounded-[20px] border border-[rgba(255,255,255,0.08)] mb-6">
        {/* Hotkey */}
        <h3 className="text-[0.65rem] text-[#555] font-bold uppercase tracking-[0.06em] m-0 mb-3">
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
                className={`w-full font-mono font-bold text-[0.95rem] tracking-[0.08em] px-3.5 py-3 rounded-xl outline-none ${
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
          <p className="text-[0.95rem] text-[#666] m-0">
            Premi il pulsante per registrare una nuova combinazione. Supporta anche i tasti laterali
            del mouse (Mouse4/Mouse5).
          </p>
        </div>

        <hr className="border-none h-px bg-[rgba(255,255,255,0.08)] my-5" />

        {/* Hold to Speak */}
        <h3 className="text-[0.65rem] text-[#555] font-bold uppercase tracking-[0.06em] m-0 mb-3">
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
            <p className="text-[0.95rem] text-[#666] m-0">
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

        <hr className="border-none h-px bg-[rgba(255,255,255,0.08)] my-5" />

        {/* Save */}
        <h3 className="text-[0.65rem] text-[#555] font-bold uppercase tracking-[0.06em] m-0 mb-3">
          Salvataggio
        </h3>

        <button
          id="save-btn"
          className="w-full py-3.5 rounded-xl font-extrabold cursor-pointer border-none text-white"
          style={{ background: "var(--primary-orange)" }}
          onClick={handleSave}
        >
          Salva Impostazioni
        </button>
      </div>
    </div>
  );
}
