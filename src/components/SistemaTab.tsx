import type { AudioDeviceInfo, AppSettings } from "../types";

interface SistemaTabProps {
  settings: AppSettings | null;
  devices: AudioDeviceInfo[];
  appVersion: string;
  onSettingChange: (key: string, value: string | boolean) => void;
}

export default function SistemaTab({
  settings,
  devices,
  appVersion,
  onSettingChange,
}: SistemaTabProps) {
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
        Configurazione Sistema
      </h2>

      <div className="bg-[rgba(34,34,34,0.6)] p-6 rounded-[20px] border border-[rgba(255,255,255,0.08)] mb-6">
        {/* Audio Device */}
        <div className="mb-6 flex flex-col gap-2">
          <label className="text-[0.9rem] font-bold text-[#ccc]" htmlFor="audio-device">
            Sorgente Audio (Microfono)
          </label>
          <select
            id="audio-device"
            className="bg-[rgba(0,0,0,0.5)] border border-[rgba(255,255,255,0.08)] px-3.5 py-3 rounded-xl text-white outline-none font-inherit"
            aria-label="Seleziona sorgente audio"
            value={settings?.selectedDevice || "default"}
            onChange={(e) => onSettingChange("selectedDevice", e.target.value)}
          >
            <option value="default">Predefinito di sistema</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>

        {/* Language */}
        <div className="mb-6 flex flex-col gap-2">
          <label className="text-[0.9rem] font-bold text-[#ccc]" htmlFor="transcription-language">
            Lingua Trascrizione
          </label>
          <select
            id="transcription-language"
            className="bg-[rgba(0,0,0,0.5)] border border-[rgba(255,255,255,0.08)] px-3.5 py-3 rounded-xl text-white outline-none font-inherit"
            aria-label="Seleziona lingua di trascrizione"
            value={settings?.selectedLanguage || "it"}
            onChange={(e) => onSettingChange("selectedLanguage", e.target.value)}
          >
            <option value="it">Italiano</option>
            <option value="en">English</option>
            <option value="fr">Français</option>
            <option value="de">Deutsch</option>
            <option value="es">Español</option>
            <option value="pt">Português</option>
            <option value="auto">Auto-detect</option>
          </select>
        </div>

        {/* Compute Device */}
        <div className="mb-6 flex flex-col gap-2">
          <label className="text-[0.9rem] font-bold text-[#ccc]" htmlFor="compute-device">
            Dispositivo di Calcolo
          </label>
          <select
            id="compute-device"
            className="bg-[rgba(0,0,0,0.5)] border border-[rgba(255,255,255,0.08)] px-3.5 py-3 rounded-xl text-white outline-none font-inherit"
            aria-label="Seleziona dispositivo di calcolo"
            value={settings?.computeDevice || "cpu"}
            onChange={(e) => onSettingChange("computeDevice", e.target.value)}
          >
            <option value="cpu">CPU (Predefinito)</option>
            <option value="cuda">GPU (CUDA)</option>
            <option value="auto">Auto-detect</option>
          </select>
          <p id="gpu-status" className="text-[0.95rem] text-[#666] m-0">
            Dispositivo in uso: CPU
          </p>
        </div>

        {/* Groq API Key */}
        <div className="flex flex-col gap-2">
          <label className="text-[0.9rem] font-bold text-[#ccc]" htmlFor="groq-api-key">
            Groq API Key (Cloud)
          </label>
          <input
            type="password"
            id="groq-api-key"
            className="bg-[rgba(0,0,0,0.5)] border border-[rgba(255,255,255,0.08)] px-3.5 py-3 rounded-xl text-white outline-none font-inherit"
            placeholder="gsk_..."
            autoComplete="off"
            aria-label="Chiave API Groq"
            value={settings?.groqApiKey || ""}
            onChange={(e) => onSettingChange("groqApiKey", e.target.value)}
          />
          <p className="text-[0.95rem] text-[#666] m-0">
            Inserisci la tua API key da{" "}
            <a
              href="https://console.groq.com/keys"
              target="_blank"
              style={{ color: "var(--primary-orange)" }}
              rel="noreferrer"
            >
              console.groq.com/keys
            </a>
          </p>
        </div>
      </div>

      <div className="bg-[rgba(34,34,34,0.6)] p-6 rounded-[20px] border border-[rgba(255,255,255,0.08)] mt-4">
        <p className="text-[0.95rem] text-center opacity-40 text-[#666] m-0">
          Traflix Voice v{appVersion}
        </p>
      </div>
    </div>
  );
}
