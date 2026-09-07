import { useEffect, useMemo, useState } from "react";
import type { AppSettings, AppStats, GroqUsage, TranscriptionEntry } from "../types";

export type MobileDestination = "overview" | "settings" | "history";
export type MobileSettingsScreen =
  | "input_method"
  | "microphone"
  | "notifications"
  | "battery"
  | "app";

export interface MobileUpdateInfo {
  available: true;
  tag: string;
  version: string;
  currentVersion: string;
  name: string;
  notes: string;
  publishedAt: string;
  assetName: string;
  size: number;
}

export type MobileUpdateState =
  | "idle"
  | "checking"
  | "available"
  | "installing"
  | "permission_required"
  | "installer_opened"
  | "error";

interface MobileDashboardProps {
  settings: AppSettings | null;
  stats: AppStats;
  historyEntries: TranscriptionEntry[];
  groqUsage: GroqUsage | null;
  transcriptionStatus: string;
  appVersion: string;
  holdToSpeak: boolean;
  onHoldToSpeakChange: (value: boolean) => Promise<void>;
  onSettingChange: (key: string, value: string | boolean) => Promise<void>;
  onClearHistory: () => Promise<void>;
  onHistoryClick: (text: string, index: number) => Promise<void>;
  onOpenAndroidSettings: (screen: MobileSettingsScreen) => Promise<void>;
  onReloadUsage: () => void;
  mobileUpdate: MobileUpdateInfo | null;
  mobileUpdateState: MobileUpdateState;
  mobileUpdateError: string;
  onInstallMobileUpdate: () => Promise<void>;
}

type IconName =
  | "overview"
  | "settings"
  | "history"
  | "cloud"
  | "keyboard"
  | "hold"
  | "tap"
  | "language"
  | "shield"
  | "android"
  | "arrow";

function MobileIcon({ name, size = 20 }: { name: IconName; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (name) {
    case "overview":
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
        </svg>
      );
    case "settings":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06A1.65 1.65 0 0 0 15 19.4a1.65 1.65 0 0 0-1 .6 1.65 1.65 0 0 0-.4 1.08V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 8.6 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-.6-1 1.65 1.65 0 0 0-1.08-.4H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 8.6a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-.6 1.65 1.65 0 0 0 .4-1.08V3a2 2 0 1 1 4 0v.09A1.65 1.65 0 0 0 15.4 4.6a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.16.39.38.73.6 1 .28.37.69.6 1.09.6H21a2 2 0 1 1 0 4h-.09A1.65 1.65 0 0 0 19.4 15Z" />
        </svg>
      );
    case "history":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
          <path d="M4 5v4h4" />
          <path d="M4.5 9A8.5 8.5 0 0 1 19 6" />
        </svg>
      );
    case "cloud":
      return (
        <svg {...common}>
          <path d="M7.5 18h9.1a4.4 4.4 0 0 0 .7-8.75A6 6 0 0 0 5.8 10.8 3.6 3.6 0 0 0 7.5 18Z" />
          <path d="m9 14 2.2 2.2L15.5 12" />
        </svg>
      );
    case "keyboard":
      return (
        <svg {...common}>
          <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
          <path d="M6 9h.01M9 9h.01M12 9h.01M15 9h.01M18 9h.01M6 13h.01M9 13h.01M12 13h.01M15 13h.01M18 13h.01" strokeWidth="2.4" />
          <path d="M7 16h10" />
        </svg>
      );
    case "hold":
      return (
        <svg {...common}>
          <path d="M8 11V6.7a1.45 1.45 0 0 1 2.9 0V11" />
          <path d="M10.9 11V5.4a1.45 1.45 0 0 1 2.9 0V11" />
          <path d="M13.8 11V6.5a1.45 1.45 0 0 1 2.9 0v6.2" />
          <path d="M16.7 12v-1a1.45 1.45 0 0 1 2.9 0v3.7A5.3 5.3 0 0 1 14.3 20h-1.4a5 5 0 0 1-3.54-1.47L6.2 15.38a1.5 1.5 0 0 1 2.12-2.12L10 14.94V11" />
        </svg>
      );
    case "tap":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="7" />
          <circle cx="12" cy="12" r="2" />
          <path d="M12 2v2M12 20v2M2 12h2M20 12h2" />
        </svg>
      );
    case "language":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
      );
    case "shield":
      return (
        <svg {...common}>
          <path d="M12 3 20 6v5.5c0 4.7-3.1 7.8-8 9.5-4.9-1.7-8-4.8-8-9.5V6l8-3Z" />
          <path d="m8.7 12 2.2 2.2 4.5-4.5" />
        </svg>
      );
    case "android":
      return (
        <svg {...common}>
          <path d="M7 9v7a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9" />
          <path d="M8.5 7.5h7a2.5 2.5 0 0 1 2.5 2.5H6a2.5 2.5 0 0 1 2.5-2.5Z" />
          <path d="m9 7-1.2-2M15 7l1.2-2M9.5 12v2M14.5 12v2M4 10v5M20 10v5" />
          <circle cx="10" cy="9.5" r=".55" fill="currentColor" stroke="none" />
          <circle cx="14" cy="9.5" r=".55" fill="currentColor" stroke="none" />
        </svg>
      );
    case "arrow":
      return (
        <svg {...common}>
          <path d="M5 12h13M13 6l6 6-6 6" />
        </svg>
      );
  }
}

const statusMeta: Record<string, { label: string; tone: string }> = {
  starting: { label: "Avvio", tone: "var(--accent)" },
  loading_model: { label: "Preparazione", tone: "var(--accent)" },
  listening: { label: "Registrazione", tone: "var(--danger)" },
  processing: { label: "Trascrizione", tone: "var(--accent)" },
  ready: { label: "Pronto", tone: "var(--signal)" },
  result: { label: "Pronto", tone: "var(--signal)" },
  error: { label: "Controlla impostazioni", tone: "var(--danger)" },
  rate_limit: { label: "Quota raggiunta", tone: "var(--accent)" },
  idle: { label: "Pronto", tone: "var(--signal)" },
};

function UsageMeter({
  label,
  value,
  limit,
  color,
}: {
  label: string;
  value: number;
  limit: number;
  color: string;
}) {
  const safeValue = Number.isFinite(value) && value > 0 ? value : 0;
  const percentage = Math.min(100, (safeValue / limit) * 100);
  return (
    <div className="mobile-usage-meter">
      <div className="mobile-usage-label">
        <span>{label}</span>
        <strong style={{ color }}>{Math.round(safeValue).toLocaleString("it-IT")}s</strong>
      </div>
      <div className="mobile-meter-track" aria-hidden="true">
        <span style={{ width: `${percentage}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

function SettingShortcut({
  icon,
  title,
  description,
  onClick,
}: {
  icon: IconName;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className="mobile-shortcut" onClick={onClick}>
      <span className="mobile-shortcut-icon"><MobileIcon name={icon} size={19} /></span>
      <span className="mobile-shortcut-copy">
        <strong>{title}</strong>
        <span>{description}</span>
      </span>
      <MobileIcon name="arrow" size={18} />
    </button>
  );
}

export default function MobileDashboard({
  settings,
  stats,
  historyEntries,
  groqUsage,
  transcriptionStatus,
  appVersion,
  holdToSpeak,
  onHoldToSpeakChange,
  onSettingChange,
  onClearHistory,
  onHistoryClick,
  onOpenAndroidSettings,
  onReloadUsage,
  mobileUpdate,
  mobileUpdateState,
  mobileUpdateError,
  onInstallMobileUpdate,
}: MobileDashboardProps) {
  const [destination, setDestination] = useState<MobileDestination>("overview");
  const [historyQuery, setHistoryQuery] = useState("");
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [apiKeyDraft, setApiKeyDraft] = useState(settings?.groqApiKey ?? "");

  useEffect(() => {
    setApiKeyDraft(settings?.groqApiKey ?? "");
  }, [settings?.groqApiKey]);

  useEffect(() => {
    const persistedKey = settings?.groqApiKey ?? "";
    if (apiKeyDraft === persistedKey) return;
    const timer = window.setTimeout(() => {
      void onSettingChange("groqApiKey", apiKeyDraft);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [apiKeyDraft, onSettingChange, settings?.groqApiKey]);

  const status = statusMeta[transcriptionStatus] ?? statusMeta.idle;
  const hasCloudKey = Boolean(settings?.groqApiKey?.trim());
  const language = settings?.selectedLanguage || "it";
  const visibleHistory = useMemo(() => {
    const normalized = historyQuery.trim().toLocaleLowerCase();
    return historyEntries
      .map((entry, originalIndex) => ({ entry, originalIndex }))
      .filter(({ entry }) => entry.text.toLocaleLowerCase().includes(normalized));
  }, [historyEntries, historyQuery]);

  const openDestination = (next: MobileDestination) => {
    setDestination(next);
    if (next === "overview") onReloadUsage();
  };

  const renderOverview = () => (
    <div className="mobile-page mobile-page-enter">
      <div className="mobile-page-heading">
        <div>
          <span className="mobile-eyebrow">Console mobile</span>
          <h1>Panoramica</h1>
          <p>Dettatura rapida, direttamente dalla tastiera.</p>
        </div>
        <span className="mobile-status-chip" style={{ color: status.tone }}>
          <span className="mobile-status-dot" style={{ backgroundColor: status.tone }} />
          {status.label}
        </span>
      </div>

      {mobileUpdate && (
        <section className="mobile-card mobile-update-card" aria-labelledby="mobile-update-title">
          <div className="mobile-card-header">
            <div className="mobile-icon-tile"><MobileIcon name="arrow" size={21} /></div>
            <div>
              <span className="mobile-eyebrow">Aggiornamento mobile</span>
              <h2 id="mobile-update-title">Traflix Voice {mobileUpdate.version}</h2>
            </div>
          </div>
          <p className="mobile-card-description">
            {mobileUpdate.notes || "È disponibile una nuova versione dell’app Android."}
          </p>
          <button
            type="button"
            className="mobile-primary-button"
            disabled={mobileUpdateState === "installing" || mobileUpdateState === "installer_opened"}
            onClick={() => void onInstallMobileUpdate()}
          >
            {mobileUpdateState === "installing"
              ? "Aggiornamento automatico…"
              : mobileUpdateState === "permission_required"
                ? "Riprova installazione"
                : mobileUpdateState === "installer_opened"
                  ? "Installer aperto"
                : "Installa aggiornamento"}
            <MobileIcon name="arrow" size={18} />
          </button>
          {mobileUpdateState === "permission_required" && (
            <p className="mobile-helper-text">Abilita l’installazione da questa app nelle impostazioni Android: al ritorno l’app riproverà automaticamente.</p>
          )}
          {mobileUpdateState === "installer_opened" && (
            <p className="mobile-helper-text">Download verificato. Conferma l’installazione nella schermata di sistema Android.</p>
          )}
          {mobileUpdateError && <p className="mobile-update-error">{mobileUpdateError}</p>}
        </section>
      )}

      <section className="mobile-card mobile-word-card" aria-label="Parole trascritte">
        <div className="mobile-card-kicker">Parole trascritte</div>
        <div className="mobile-word-value">{stats.total_words.toLocaleString("it-IT")}</div>
        <div className="mobile-stat-row">
          <span>Ritmo medio <strong>{stats.avg_wpm} WPM</strong></span>
          <span>Tempo attivo <strong>{stats.total_time < 60 ? `${Math.round(stats.total_time)} min` : `${(stats.total_time / 60).toFixed(1)} h`}</strong></span>
        </div>
      </section>

      <section className="mobile-card mobile-cloud-card" aria-label="Groq Cloud">
        <div className="mobile-card-header">
          <div className="mobile-icon-tile mobile-icon-tile--signal"><MobileIcon name="cloud" size={21} /></div>
          <div>
            <span className="mobile-eyebrow">Provider attivo</span>
            <h2>Groq Cloud</h2>
          </div>
          <span className={`mobile-connection-badge ${hasCloudKey ? "is-ready" : "is-pending"}`}>
            <span />{hasCloudKey ? "Connesso" : "Da configurare"}
          </span>
        </div>
        <p className="mobile-card-description">
          Un solo percorso cloud per tenere l’esperienza veloce e prevedibile.
        </p>
        <div className="mobile-usage-grid">
          <UsageMeter label="Oggi" value={groqUsage?.audio_seconds ?? 0} limit={28800} color="var(--signal)" />
          <UsageMeter label="Questa ora" value={groqUsage?.audio_seconds_hourly ?? 0} limit={7200} color="var(--accent)" />
        </div>
      </section>

      <section className="mobile-card mobile-keyboard-card" aria-label="Tastiera Traflix Voice">
        <div className="mobile-card-header">
          <div className="mobile-icon-tile"><MobileIcon name="keyboard" size={21} /></div>
          <div>
            <span className="mobile-eyebrow">Tastiera Traflix Voice</span>
            <h2>{holdToSpeak ? "Hold to Speak" : "Tocca per parlare"}</h2>
          </div>
        </div>
        <p className="mobile-card-description">
          {holdToSpeak
            ? "Tieni premuto il microfono e rilascia per inviare la trascrizione."
            : "Tocca il microfono per iniziare e toccalo di nuovo per fermarti."}
        </p>
        <button type="button" className="mobile-primary-button" onClick={() => void onOpenAndroidSettings("input_method")}>
          Configura tastiera <MobileIcon name="arrow" size={18} />
        </button>
      </section>
    </div>
  );

  const renderSettings = () => (
    <div className="mobile-page mobile-page-enter">
      <div className="mobile-page-heading">
        <div>
          <span className="mobile-eyebrow">Controlli essenziali</span>
          <h1>Impostazioni</h1>
          <p>Configura una volta. Poi torna alla tastiera.</p>
        </div>
      </div>

      <section className="mobile-card" aria-labelledby="recording-mode-title">
        <div className="mobile-section-heading">
          <div>
            <span className="mobile-eyebrow">Interazione</span>
            <h2 id="recording-mode-title">Modalità di registrazione</h2>
          </div>
          <span className="mobile-setting-value">{holdToSpeak ? "Hold" : "Toggle"}</span>
        </div>
        <div className="mobile-mode-grid" role="group" aria-label="Modalità di registrazione">
          <button
            type="button"
            className={`mobile-mode-option ${holdToSpeak ? "is-selected" : ""}`}
            aria-pressed={holdToSpeak}
            onClick={() => void onHoldToSpeakChange(true)}
          >
            <span className="mobile-mode-icon"><MobileIcon name="hold" size={21} /></span>
            <span><strong>Hold to Speak</strong><small>Premi e tieni premuto</small></span>
            <span className="mobile-radio" />
          </button>
          <button
            type="button"
            className={`mobile-mode-option ${!holdToSpeak ? "is-selected" : ""}`}
            aria-pressed={!holdToSpeak}
            onClick={() => void onHoldToSpeakChange(false)}
          >
            <span className="mobile-mode-icon"><MobileIcon name="tap" size={21} /></span>
            <span><strong>Tocca per parlare</strong><small>Premi per avviare e fermare</small></span>
            <span className="mobile-radio" />
          </button>
        </div>
      </section>

      <section className="mobile-card" aria-labelledby="language-title">
        <div className="mobile-section-heading">
          <div className="mobile-setting-leading"><span className="mobile-icon-tile"><MobileIcon name="language" size={19} /></span><div><span className="mobile-eyebrow">Output</span><h2 id="language-title">Lingua</h2></div></div>
        </div>
        <select
          className="mobile-field"
          value={language}
          aria-label="Lingua di trascrizione"
          onChange={(event) => void onSettingChange("selectedLanguage", event.target.value)}
        >
          <option value="it">Italiano</option>
          <option value="en">English</option>
          <option value="fr">Français</option>
          <option value="de">Deutsch</option>
          <option value="es">Español</option>
          <option value="pt">Português</option>
          <option value="auto">Rilevamento automatico</option>
        </select>
      </section>

      <section className="mobile-card" aria-labelledby="cloud-access-title">
        <div className="mobile-section-heading">
          <div className="mobile-setting-leading"><span className="mobile-icon-tile mobile-icon-tile--signal"><MobileIcon name="cloud" size={19} /></span><div><span className="mobile-eyebrow">Provider unico</span><h2 id="cloud-access-title">Accesso Groq Cloud</h2></div></div>
          <span className={`mobile-mini-state ${hasCloudKey ? "is-ready" : ""}`}>{hasCloudKey ? "Attivo" : "Manca la chiave"}</span>
        </div>
        <input
          className="mobile-field"
          type="password"
          value={apiKeyDraft}
          placeholder="gsk_…"
          autoComplete="off"
          aria-label="Chiave API Groq"
          onChange={(event) => setApiKeyDraft(event.target.value)}
          onBlur={() => {
            if (apiKeyDraft !== (settings?.groqApiKey ?? "")) void onSettingChange("groqApiKey", apiKeyDraft);
          }}
        />
        <p className="mobile-helper-text">La chiave viene usata solo per il percorso cloud configurato.</p>
      </section>

      <section className="mobile-card" aria-labelledby="android-title">
        <div className="mobile-section-heading">
          <div className="mobile-setting-leading"><span className="mobile-icon-tile"><MobileIcon name="android" size={19} /></span><div><span className="mobile-eyebrow">Sistema</span><h2 id="android-title">Accesso rapido</h2></div></div>
        </div>
        <div className="mobile-shortcuts">
          <SettingShortcut icon="keyboard" title="Tastiera Android" description="Attiva Traflix Voice come tastiera" onClick={() => void onOpenAndroidSettings("input_method")} />
          <SettingShortcut icon="android" title="Permesso microfono" description="Consenti la registrazione vocale" onClick={() => void onOpenAndroidSettings("microphone")} />
          <SettingShortcut icon="cloud" title="Notifiche" description="Mostra lo stato della registrazione" onClick={() => void onOpenAndroidSettings("notifications")} />
          <SettingShortcut icon="shield" title="Batteria" description="Riduci le limitazioni in background" onClick={() => void onOpenAndroidSettings("battery")} />
        </div>
      </section>

      <section className="mobile-privacy-note">
        <MobileIcon name="shield" size={18} />
        <p><strong>Cronologia locale.</strong> Le trascrizioni restano sul dispositivo e puoi eliminarle dalla sezione Cronologia.</p>
      </section>
    </div>
  );

  const renderHistory = () => (
    <div className="mobile-page mobile-page-enter">
      <div className="mobile-page-heading">
        <div>
          <span className="mobile-eyebrow">Solo sul dispositivo</span>
          <h1>Cronologia</h1>
          <p>{historyEntries.length} trascrizioni salvate localmente.</p>
        </div>
        {historyEntries.length > 0 && (
          <button
            type="button"
            className={`mobile-clear-button ${confirmingClear ? "is-confirming" : ""}`}
            onClick={() => {
              if (confirmingClear) {
                void onClearHistory();
                setConfirmingClear(false);
              } else {
                setConfirmingClear(true);
              }
            }}
          >
            {confirmingClear ? "Conferma" : "Cancella"}
          </button>
        )}
      </div>

      <label className="mobile-search-field">
        <MobileIcon name="history" size={18} />
        <span className="sr-only">Cerca nella cronologia</span>
        <input value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="Cerca una frase…" />
      </label>

      {confirmingClear && <p className="mobile-danger-note">La cancellazione rimuove definitivamente le trascrizioni locali.</p>}

      <div className="mobile-history-list" role="list" aria-label="Cronologia trascrizioni">
        {visibleHistory.length === 0 ? (
          <div className="mobile-empty-state">
            <span className="mobile-icon-tile"><MobileIcon name="history" size={21} /></span>
            <strong>{historyEntries.length === 0 ? "Nessuna trascrizione ancora" : "Nessun risultato"}</strong>
            <p>{historyEntries.length === 0 ? "Le prossime sessioni appariranno qui." : "Prova con una parola diversa."}</p>
          </div>
        ) : visibleHistory.map(({ entry, originalIndex }) => (
          <button
            type="button"
            className="mobile-history-entry"
            key={`${entry.timestamp}-${originalIndex}`}
            onClick={() => void onHistoryClick(entry.text, originalIndex)}
            title="Copia negli appunti"
            role="listitem"
          >
            <div className="mobile-history-meta"><span>{entry.timestamp}</span><span>{entry.word_count > 0 ? `${entry.word_count} parole` : "Trascrizione"}</span></div>
            <p>{entry.text.length > 190 ? `${entry.text.slice(0, 190)}…` : entry.text}</p>
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="mobile-shell">
      <header className="mobile-appbar">
        <div className="mobile-brand">
          <img src="/assets/logo.png" alt="" />
          <div><strong>Traflix Voice</strong><span>Mobile Hub <small>v{appVersion || "…"}</small></span></div>
        </div>
        <span className="mobile-cloud-pill"><span />Groq Cloud</span>
      </header>

      <main className="mobile-main">
        <div className="mobile-content">
          {destination === "overview" && renderOverview()}
          {destination === "settings" && renderSettings()}
          {destination === "history" && renderHistory()}
        </div>
      </main>

      <nav className="mobile-bottom-nav" aria-label="Navigazione mobile">
        {([
          ["overview", "Panoramica", "overview"],
          ["settings", "Impostazioni", "settings"],
          ["history", "Cronologia", "history"],
        ] as const).map(([id, label, icon]) => (
          <button
            key={id}
            type="button"
            className={destination === id ? "is-active" : ""}
            aria-current={destination === id ? "page" : undefined}
            onClick={() => openDestination(id)}
          >
            <MobileIcon name={icon} size={21} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
