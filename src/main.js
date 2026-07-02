const { invoke } = window.__TAURI__.core;

let hotkeyInput;
let recordBtn;
let isRecording = false;
let selectedModel = "small";
let selectedLanguage = "it";
let computeDevice = "cpu";  // "cpu", "cuda", "auto"
let selectedProvider = "local"; // "local" | "cloud"
const modelStatus = {}; // { modelId: { downloaded: bool, loading: bool } }

// ─── TOAST NOTIFICATION SYSTEM ───────────────────────────────────────────────
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;

  const icons = {
    success: "✓",
    error: "✕",
    info: "ℹ"
  };

  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || icons.info}</span>
    <span class="toast-message">${message}</span>
  `;

  container.appendChild(toast);

  // Auto-remove after 3 seconds
  setTimeout(() => {
    toast.classList.add("fade-out");
    setTimeout(() => {
      if (toast.parentElement) {
        toast.parentElement.removeChild(toast);
      }
    }, 300);
  }, 3000);
}

// ─── CATALOGO MODELLI WHISPER ──────────────────────────────────────────────────
const WHISPER_MODELS = [
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

// ─── RENDER MODELLI ──────────────────────────────────────────────────────────
async function refreshAllModelStatus() {
  const results = await Promise.all(
    WHISPER_MODELS.map(m =>
      invoke("check_model_exists", { modelId: m.id })
        .then(exists => ({ id: m.id, exists }))
    )
  );
  for (const { id, exists } of results) {
    modelStatus[id] = { ...modelStatus[id], downloaded: exists };
  }
}

function renderModels() {
  const grid = document.querySelector(".model-grid");
  if (!grid) return;

  if (selectedProvider === "cloud") {
    grid.innerHTML = `
      <div class="model-card active" data-model-id="cloud">
        <div class="model-main">
          <div class="model-header">
            <div class="model-title-row">
              <h3>Whisper Large V3 Turbo</h3>
              <span class="model-tag" style="background:rgba(79,195,247,0.15);color:#4fc3f7;border-color:rgba(79,195,247,0.3);">Cloud</span>
            </div>
            <div class="model-meta">
              <span class="model-size">~3 GB (remoto)</span>
              <span class="model-ram">0 GB RAM locale</span>
            </div>
          </div>
          <p class="model-desc">Massima precisione su Groq LPU. 216x real-time — trascrive 1 minuto di audio in ~0.3 secondi. Supporto multilingua incluso italiano. Nessun download richiesto.</p>
          <div class="model-metrics">
            <div class="metric">
              <span class="metric-label">Velocità</span>
              <div class="dots">${renderDots(5, 5, "var(--primary-orange)")}</div>
            </div>
            <div class="metric">
              <span class="metric-label">Precisione</span>
              <div class="dots">${renderDots(5, 5, "#4fc3f7")}</div>
            </div>
          </div>
        </div>
        <button class="model-btn select">
          ✓ Attivo
        </button>
      </div>
    `;
    return;
  }

  grid.innerHTML = WHISPER_MODELS.map(m => {
    const isActive = m.id === selectedModel;
    const status = modelStatus[m.id] || { downloaded: false, loading: false };
    
    const speedDots   = renderDots(m.speed,   5, "var(--primary-orange)");
    const qualityDots = renderDots(m.quality, 5, "#4fc3f7");

    let buttonLabel = "Seleziona";
    let buttonClass = "select";
    
    if (isActive) {
      buttonLabel = "✓ Attivo";
    } else if (status.loading) {
      buttonLabel = "Download...";
      buttonClass = "downloading";
    } else if (!status.downloaded) {
      buttonLabel = "Scarica";
      buttonClass = "download";
    }

    return `
      <div class="model-card ${isActive ? "active" : ""} ${!status.downloaded ? "not-downloaded" : ""}" data-model-id="${m.id}">
        <div class="model-main">
          <div class="model-header">
            <div class="model-title-row">
              <h3>${m.name}</h3>
              ${m.tag ? `<span class="model-tag">${m.tag}</span>` : ""}
            </div>
            <div class="model-meta">
              <span class="model-size">${m.size}</span>
              <span class="model-ram">RAM ${m.ram}</span>
            </div>
          </div>
          <p class="model-desc">${m.description}</p>
          <div class="model-metrics">
            <div class="metric">
              <span class="metric-label">Velocità</span>
              <div class="dots">${speedDots}</div>
            </div>
            <div class="metric">
              <span class="metric-label">Precisione</span>
              <div class="dots">${qualityDots}</div>
            </div>
          </div>
        </div>
        <button class="model-btn ${buttonClass}" data-model-id="${m.id}" ${status.loading ? "disabled" : ""}>
          ${buttonLabel}
        </button>
      </div>
    `;
  }).join("");

  grid.querySelectorAll(".model-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-model-id");
      const status = modelStatus[id] || { downloaded: false, loading: false };

      if (!status.downloaded) {
        // Avvia download
        modelStatus[id].loading = true;
        renderModels();
        await invoke("send_to_python", { message: JSON.stringify({ command: "download", model: id }) });
      } else {
        // Seleziona
        selectedModel = id;
        renderModels();
        updateModelDisplay();
        loadProviderDashboard();
      }
    });
  });
}

function renderDots(filled, total, color) {
  return Array.from({ length: total }, (_, i) =>
    `<span class="dot ${i < filled ? "filled" : ""}" style="${i < filled ? `background:${color};box-shadow:0 0 6px ${color}80` : ""}"></span>`
  ).join("");
}

function updateModelDisplay() {
  const modelDisplay = document.querySelector("#current-model-display");
  if (modelDisplay) {
    if (selectedProvider === "cloud") {
      modelDisplay.textContent = "Whisper Large V3 Turbo (Cloud)";
    } else {
      const m = WHISPER_MODELS.find(m => m.id === selectedModel);
      modelDisplay.textContent = m ? `Whisper ${m.name}` : selectedModel;
    }
  }
}

function loadProviderDashboard() {
  const dashboard = document.querySelector("#provider-dashboard");
  const content = document.querySelector("#provider-dashboard-content");
  if (!dashboard || !content) return;

  if (selectedProvider !== "cloud") {
    dashboard.style.display = "none";
    return;
  }

  dashboard.style.display = "block";
  renderCloudDashboard(content, loadGroqUsageFromStorage());
}

function loadGroqUsageFromStorage() {
  try {
    const raw = localStorage.getItem("groq_usage");
    if (!raw) return null;
    const usage = JSON.parse(raw);
    const today = new Date().toISOString().split("T")[0];
    if (usage.date !== today) return null;
    return usage;
  } catch (_) {
    return null;
  }
}

function recordGroqUsage(durationSecs) {
  if (selectedProvider !== "cloud" || !durationSecs) return;
  try {
    const today = new Date().toISOString().split("T")[0];
    let usage;
    try {
      const raw = localStorage.getItem("groq_usage");
      usage = raw ? JSON.parse(raw) : { date: today, audio_seconds: 0, audio_seconds_hourly: 0, hourly_reset: "" };
    } catch (_) {
      usage = { date: today, audio_seconds: 0, audio_seconds_hourly: 0, hourly_reset: "" };
    }

    if (usage.date !== today) {
      usage = { date: today, audio_seconds: 0, audio_seconds_hourly: 0, hourly_reset: "" };
    }

    const now = Date.now();
    const thisHour = Math.floor(now / 3600000);
    if (usage._lastHour !== thisHour) {
      usage.audio_seconds_hourly = 0;
      usage._lastHour = thisHour;
    }

    usage.audio_seconds = Math.round((usage.audio_seconds || 0) + durationSecs);
    usage.audio_seconds_hourly = Math.round((usage.audio_seconds_hourly || 0) + durationSecs);
    const nextHour = (Math.floor(now / 3600000) + 1) * 3600000;
    usage.hourly_reset = new Date(nextHour).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

    localStorage.setItem("groq_usage", JSON.stringify(usage));
  } catch (_) {}
}

function renderCloudDashboard(content, usage) {
  if (!usage) usage = {};

  const dailySecs = usage.audio_seconds || 0;
  const hourlySecs = usage.audio_seconds_hourly || 0;
  const dailyPct = Math.min(100, (dailySecs / 28800) * 100);
  const hourlyPct = Math.min(100, (hourlySecs / 7200) * 100);

  const warnColor = dailyPct > 80 || hourlyPct > 80;
  const dailyColor = warnColor ? "#ff4444" : "#4fc3f7";
  const hourlyColor = warnColor ? "#ff4444" : "var(--primary-orange)";

  content.innerHTML = `
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:0.5rem;">
      <span style="font-size:0.7rem;font-weight:700;color:#4fc3f7;text-transform:uppercase;letter-spacing:0.04em;">Utilizzo Cloud</span>
    </div>
    <div style="display:flex;gap:1rem;flex-wrap:wrap;">
      <div style="flex:1;min-width:130px;">
        <div style="display:flex;justify-content:space-between;font-size:0.68rem;color:#888;margin-bottom:2px;">
          <span>Giornaliero</span>
          <span>${Math.round(dailySecs)} / 28,800s</span>
        </div>
        <div class="progress-container" style="height:5px;margin:0;">
          <div class="progress-fill" style="width:${dailyPct}%;background:${dailyColor};"></div>
        </div>
      </div>
      <div style="flex:1;min-width:130px;">
        <div style="display:flex;justify-content:space-between;font-size:0.68rem;color:#888;margin-bottom:2px;">
          <span>Orario (reset ${usage.hourly_reset || "--:--"})</span>
          <span>${Math.round(hourlySecs)} / 7,200s</span>
        </div>
        <div class="progress-container" style="height:5px;margin:0;">
          <div class="progress-fill" style="width:${hourlyPct}%;background:${hourlyColor};"></div>
        </div>
      </div>
    </div>
  `;
}

// ─── HELPERS HOTKEY ──────────────────────────────────────────────────────────
function formatKey(key) {
  const map = {
    'Control': 'CommandOrControl',
    'Alt': 'Alt',
    'Shift': 'Shift',
    ' ': 'Space',
    'Meta': 'Super'
  };
  return map[key] || key.charAt(0).toUpperCase() + key.slice(1);
}

function formatTime(minutes) {
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

// ─── LOAD / SAVE ─────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const s = await invoke("load_settings");
    if (!s || typeof s.hotkey === "undefined") return;

    if (hotkeyInput) {
      hotkeyInput.value = s.hotkey || "CommandOrControl+Space";
      void hotkeyInput.offsetHeight;
    }
    const hotkeyDisplay = document.querySelector("#current-hotkey-display");
    if (hotkeyDisplay) hotkeyDisplay.textContent = s.hotkey || "CommandOrControl+Space";

    const minimizeTray = document.querySelector("#minimize-tray");
    const audioDevice  = document.querySelector("#audio-device");
    const holdToSpeakToggle = document.querySelector("#hold-to-speak");

    if (minimizeTray) minimizeTray.checked = s.minimizeTray ?? true;
    if (audioDevice && s.selectedDevice) audioDevice.value = s.selectedDevice;
    if (holdToSpeakToggle) holdToSpeakToggle.checked = s.holdToSpeak ?? false;

    const langSelect = document.querySelector("#transcription-language");
    selectedLanguage = s.selectedLanguage || "it";
    if (langSelect) langSelect.value = selectedLanguage;

    const computeDeviceSelect = document.querySelector("#compute-device");
    computeDevice = s.computeDevice || "cpu";
    if (computeDeviceSelect) computeDeviceSelect.value = computeDevice;

    selectedModel = s.model || "small";

    const groqApiKeyInput = document.querySelector("#groq-api-key");
    if (groqApiKeyInput) groqApiKeyInput.value = s.groqApiKey || "";

    selectedProvider = s.provider || "local";
    const providerToggle = document.querySelector("#provider-toggle");
    if (providerToggle) providerToggle.checked = selectedProvider === "cloud";
  } catch (err) {
    console.warn("[settings] Caricamento fallito, uso default:", err);
  }
}

async function loadStats() {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const stats = await invoke("get_stats");
      const wordsEl = document.querySelector("#stat-words");
      const wpmEl   = document.querySelector("#stat-wpm");
      const timeEl  = document.querySelector("#stat-time");
      if (wordsEl) wordsEl.textContent = stats.total_words ?? 0;
      if (wpmEl)   wpmEl.textContent   = stats.avg_wpm     ?? 0;
      if (timeEl)  timeEl.textContent  = formatTime(stats.total_time ?? 0);
      return;
    } catch (err) {
      lastError = err;
      if (attempt < 2) await new Promise(r => setTimeout(r, 500));
    }
  }
  console.warn("[stats] Impossibile caricare stats dopo 3 tentativi:", lastError);
}

async function persistSettings() {
  const settings = {
    hotkey:         hotkeyInput.value || "CommandOrControl+Space",
    model:          selectedModel,
    minimizeTray:   document.querySelector("#minimize-tray")?.checked ?? true,
    selectedDevice: document.querySelector("#audio-device").value,
    selectedLanguage: document.querySelector("#transcription-language")?.value || selectedLanguage,
    computeDevice: document.querySelector("#compute-device")?.value || computeDevice,
    holdToSpeak:    document.querySelector("#hold-to-speak")?.checked ?? true,
    groqApiKey:     document.querySelector("#groq-api-key")?.value || "",
    provider:        selectedProvider,
  };
  await invoke("save_settings", { settings });
  return settings;
}

async function loadAudioDevices() {
  try {
    const devices = await invoke("get_audio_devices");
    const select = document.querySelector("#audio-device");
    if (select) {
      select.innerHTML = '<option value="default">Predefinito di sistema</option>';
      devices.forEach(d => {
        const opt = document.createElement("option");
        opt.value = d.id;
        opt.textContent = d.name;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.error("[audio] Errore caricamento dispositivi:", err);
  }
}

// ─── AGGIORNAMENTI (placeholder) ─────────────────────────────────────────────
async function getAppVersion() {
  try {
    return await window.__TAURI__.app.getVersion();
  } catch (_) {
    return "unknown";
  }
}

async function checkForUpdates() {
  const statusEl = document.querySelector("#update-status");
  if (statusEl) {
    statusEl.textContent = "Aggiornamenti automatici non ancora configurati.";
  }
  console.log("[updater] Controllo aggiornamenti non ancora attivo.");
}

// ─── LOADING OVERLAY ─────────────────────────────────────────────────────────
function showLoadingOverlay() {
  const overlay = document.querySelector("#loading-overlay");
  if (overlay) overlay.style.display = "flex";
}

function hideLoadingOverlay() {
  const overlay = document.querySelector("#loading-overlay");
  if (overlay) overlay.style.display = "none";
}

// ─── INIT ────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  hotkeyInput = document.querySelector("#hotkey");
  recordBtn   = document.querySelector("#record-btn");
  const saveBtn       = document.querySelector("#save-btn");
  const navLinks      = document.querySelectorAll(".nav-links li");
  const tabContents   = document.querySelectorAll(".tab-content");

  // ── SETTINGS + STATS (immediati, non aspettano audio devices) ──
  loadSettings();
  loadStats();

  // ── ALTRO (audio, versione, modelli) ──
  const [appVersion] = await Promise.all([
    getAppVersion(),
    loadAudioDevices(),
  ]);

  // Re-sync audio device value after dropdown is populated
  (async () => {
    try {
      const s = await invoke("load_settings");
      const ad = document.querySelector("#audio-device");
      if (ad && s.selectedDevice) ad.value = s.selectedDevice;
    } catch (_) {}
  })();

  // Versione app (dopo Promise.all, appVersion è già risolta)
  const versionEl = document.querySelector("#app-version");
  if (versionEl) versionEl.textContent = appVersion;
  const footerVersion = document.querySelector("#footer-version");
  if (footerVersion) footerVersion.textContent = `Traflix Voice v${appVersion}`;

  // ── MODELS (4 checks in parallelo) ──
  await refreshAllModelStatus();
  renderModels();
  updateModelDisplay();

  // Pulsante Controlla Aggiornamenti
  const checkUpdatesBtn = document.querySelector("#check-updates-btn");
  if (checkUpdatesBtn) {
    checkUpdatesBtn.addEventListener("click", checkForUpdates);
  }

  // ── COMPUTE DEVICE SELECTOR ──
  const computeDeviceSelect = document.querySelector("#compute-device");
  if (computeDeviceSelect) {
    computeDeviceSelect.addEventListener("change", async () => {
      computeDevice = computeDeviceSelect.value;
      // Notify Python engine of the device change
      try {
        await invoke("send_to_python", {
          message: JSON.stringify({ command: "set_device", device: computeDevice })
        });
        await persistSettings();
        showToast("Impostazioni salvate", "info");
      } catch (err) {
        console.warn("[gpu] Impossibile inviare set_device a Python:", err);
        showToast("Errore nel salvataggio delle impostazioni", "error");
      }
    });
  }

  // ── AUDIO DEVICE AND LANGUAGE CHANGE LISTENERS ──
  const audioDeviceSelect = document.querySelector("#audio-device");
  if (audioDeviceSelect) {
    audioDeviceSelect.addEventListener("change", async () => {
      await persistSettings();
      showToast("Impostazioni salvate", "info");
    });
  }

  const languageSelect = document.querySelector("#transcription-language");
  if (languageSelect) {
    languageSelect.addEventListener("change", async () => {
      selectedLanguage = languageSelect.value;
      await persistSettings();
      showToast("Impostazioni salvate", "info");
    });
  }

  const minimizeTrayToggle = document.querySelector("#minimize-tray");
  if (minimizeTrayToggle) {
    minimizeTrayToggle.addEventListener("change", async () => {
      await persistSettings();
      showToast("Impostazioni salvate", "info");
    });
  }

  const holdToSpeakEl = document.querySelector("#hold-to-speak");
  if (holdToSpeakEl) {
    holdToSpeakEl.addEventListener("change", async () => {
      await persistSettings();
      const mode = holdToSpeakEl.checked ? "Tieni premuto" : "Click per toggle";
      showToast(`Modalità: ${mode}`, "info");
    });
  }

  const providerToggle = document.querySelector("#provider-toggle");
  if (providerToggle) {
    providerToggle.addEventListener("change", async () => {
      selectedProvider = providerToggle.checked ? "cloud" : "local";
      await persistSettings();
      renderModels();
      loadProviderDashboard();
      showToast(`Provider: ${selectedProvider === "cloud" ? "Cloud" : "Locale"}`, "info");
      // Notifica Python del cambio provider
      try {
        await invoke("send_to_python", {
          message: JSON.stringify({
            command: "set_provider",
            provider: selectedProvider,
            model: selectedModel,
          })
        });
      } catch (err) {
        console.warn("[provider] Impossibile inviare set_provider a Python:", err);
      }
    });
  }

  const groqApiKeyInput = document.querySelector("#groq-api-key");
  if (groqApiKeyInput) {
    groqApiKeyInput.addEventListener("change", async () => {
      await persistSettings();
      showToast("API key salvata", "info");
    });
  }

  let currentTab = "home";
  let dashboardInterval = null;

  navLinks.forEach(link => {
    link.addEventListener("click", async () => {
      const targetTab = link.getAttribute("data-tab");
      if (targetTab === currentTab) return;

      if (targetTab === "ia") { await loadSettings(); loadProviderDashboard(); }

      navLinks.forEach(l => l.classList.remove("active"));
      link.classList.add("active");
      tabContents.forEach(tab => {
        tab.classList.remove("active");
        if (tab.id === targetTab) tab.classList.add("active");
      });

      if (targetTab === "home") { loadStats(); updateModelDisplay(); }
      if (targetTab === "tasti") loadSettings();
      if (targetTab === "cronologia") loadHistory();

      clearInterval(dashboardInterval);
      if (targetTab === "ia" && selectedProvider === "cloud") {
        dashboardInterval = setInterval(loadProviderDashboard, 15000);
      }

      currentTab = targetTab;
    });
  });

  // ── HOTKEY RECORDING ──
  recordBtn.addEventListener("click", () => {
    isRecording = !isRecording;
    if (isRecording) {
      recordBtn.classList.add("recording");
      hotkeyInput.value = "";
      hotkeyInput.placeholder = "Premi combinazione...";
    } else {
      recordBtn.classList.remove("recording");
      hotkeyInput.placeholder = "Premi i tasti...";
    }
  });

  window.addEventListener("keydown", (e) => {
    if (!isRecording) return;
    e.preventDefault();
    
    const keys = [];
    if (e.ctrlKey)  keys.push("CommandOrControl");
    if (e.altKey)   keys.push("Alt");
    if (e.shiftKey) keys.push("Shift");
    if (e.metaKey)  keys.push("Super");
    
    const isModifier = ['Control', 'Alt', 'Shift', 'Meta'].includes(e.key);
    
    if (!isModifier) {
      // Tasto finale "reale"
      keys.push(formatKey(e.key));
      hotkeyInput.value = keys.join("+");
      isRecording = false;
      recordBtn.classList.remove("recording");
      hotkeyInput.placeholder = "Premi i tasti...";
    } else {
      // Sta ancora premendo solo modificatori, mostriamoli in anteprima
      hotkeyInput.value = keys.join("+") + "+...";
    }
  });

  // ── MOUSE BUTTON RECORDING ──
  window.addEventListener("mousedown", (e) => {
    if (!isRecording) return;

    let mouseKey = null;
    if (e.button === 3) mouseKey = "XBUTTON1";
    else if (e.button === 4) mouseKey = "XBUTTON2";
    else return;

    e.preventDefault();

    const keys = [];
    if (e.ctrlKey)  keys.push("CommandOrControl");
    if (e.altKey)   keys.push("Alt");
    if (e.shiftKey) keys.push("Shift");
    if (e.metaKey)  keys.push("Super");

    keys.push(mouseKey);
    hotkeyInput.value = keys.join("+");
    isRecording = false;
    recordBtn.classList.remove("recording");
    hotkeyInput.placeholder = "Premi i tasti...";
  });

  saveBtn.addEventListener("click", async () => {
    // Permettiamo specificamente "Control+Alt" (o CommandOrControl+Alt)
    const isControlAlt = hotkeyInput.value === "CommandOrControl+Alt+..." || 
                         hotkeyInput.value === "Control+Alt+...";

    if (hotkeyInput.value.includes("...") && !isControlAlt) {
      alert("La scorciatoia non è completa! Premi un tasto finale (es. Spazio o una lettera) mentre tieni premuto Control/Alt.");
      return;
    }

    if (isControlAlt) {
      hotkeyInput.value = "CommandOrControl+Alt";
    }

    try {
      const settings = await persistSettings();
      const hotkeyDisplay = document.querySelector("#current-hotkey-display");
      if (hotkeyDisplay) hotkeyDisplay.textContent = settings.hotkey;
      showToast("Scorciatoia salvata con successo", "success");
    } catch (err) {
      console.error("Errore salvataggio:", err);
      showToast("Errore nel salvataggio delle impostazioni", "error");
    }
  });

  // ── NOTIFICATION SOUNDS ──
  const startSound = new Audio("assets/sounds/start.wav");
  const stopSound = new Audio("assets/sounds/stop.wav");
  startSound.volume = 1.0;
  stopSound.volume = 1.0;

  // ── LISTENER OUTPUT PYTHON ──
  const { listen } = window.__TAURI__.event;
  // Flag per sapere se il modello è stato caricato e possiamo trascrivere
  let modelReady = true;

  const statusEl = document.querySelector("#transcription-status");

  const statusIcons = {
    starting: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg> Avvio motore vocale...`,
    loading_model: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></svg> Caricamento modello...`,
    listening: `<svg class="status-icon status-icon--pulse" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/></svg> Registrazione in corso...`,
    processing: `<svg class="status-icon status-icon--spin" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Elaborazione...`,
    ready: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg> Pronto`,
    result: `<svg class="status-icon" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg> Pronto`,
  };

  listen("python_output", async (event) => {
    try {
      const data = JSON.parse(event.payload);

      // Aggiorna lo stato di modelReady
      if (data.status === "starting" || data.status === "loading_model") {
        modelReady = false;
        showLoadingOverlay();
      } else if (data.status === "ready" || data.status === "result" || data.status === "error") {
        modelReady = true;
        hideLoadingOverlay();
      }

      if (statusEl && statusIcons[data.status]) {
        statusEl.innerHTML = statusIcons[data.status];
      }

      if (data.status === "listening") {
        startSound.currentTime = 0;
        startSound.play().catch(() => {});
      } else if (data.status === "processing") {
        stopSound.currentTime = 0;
        stopSound.play().catch(() => {});
      }

      // Gestione Download
      if (data.status === "downloading") {
        if (modelStatus[data.model]) modelStatus[data.model].loading = true;
        renderModels();

        // Show download modal with progress
        const modal = document.querySelector("#download-popup");
        const progressBar = document.querySelector("#progress-bar");
        const progressText = document.querySelector("#progress-text");
        const downloadTitle = document.querySelector("#download-title");

        if (modal) {
          modal.style.display = "flex";

          // Update title
          if (downloadTitle) {
            const modelName = WHISPER_MODELS.find(m => m.id === data.model)?.name || data.model;
            downloadTitle.textContent = `Scaricando ${modelName}...`;
          }

          // Update progress
          if (progressBar && progressText) {
            const percentage = data.progress || 0;

            if (percentage > 0) {
              // Known progress - show percentage
              progressBar.style.width = `${percentage}%`;
              progressBar.classList.remove("indeterminate");
              progressText.textContent = `Scaricando modello... ${Math.round(percentage)}%`;
            } else {
              // Unknown progress - indeterminate state
              progressBar.classList.add("indeterminate");
              progressText.textContent = "Scaricando modello...";
            }
          }
        }
      }
      if (data.status === "download_complete") {
        modelStatus[data.model] = { downloaded: true, loading: false };
        renderModels();

        // Show 100% briefly then close modal with fade-out
        const modal = document.querySelector("#download-popup");
        const progressBar = document.querySelector("#progress-bar");
        const progressText = document.querySelector("#progress-text");

        if (modal && progressBar && progressText) {
          progressBar.style.width = "100%";
          progressBar.classList.remove("indeterminate");
          progressText.textContent = "Scaricando modello... 100%";

          setTimeout(() => {
            modal.style.opacity = "0";
            setTimeout(() => {
              modal.style.display = "none";
              modal.style.opacity = "1";
            }, 300);
          }, 500);
        }

        // Show success toast
        const modelName = WHISPER_MODELS.find(m => m.id === data.model)?.name || data.model;
        showToast(`Modello ${modelName} scaricato con successo`, "success");
      } else if (data.status === "download_error") {
        // Handle download errors gracefully
        console.error("Download Error:", data.message);

        const modal = document.querySelector("#download-popup");
        const progressBar = document.querySelector("#progress-bar");
        const progressText = document.querySelector("#progress-text");
        const downloadTitle = document.querySelector("#download-title");

        if (modal && progressBar && progressText && downloadTitle) {
          // Show error state in modal
          downloadTitle.textContent = "Errore nel Download";
          progressBar.style.width = "100%";
          progressBar.style.background = "#ff4444";
          progressBar.classList.remove("indeterminate");
          progressText.textContent = data.message || "Si è verificato un errore durante il download.";
          progressText.style.color = "#ff4444";

          // Close modal after 3 seconds
          setTimeout(() => {
            modal.style.opacity = "0";
            setTimeout(() => {
              modal.style.display = "none";
              modal.style.opacity = "1";
              // Reset styles
              progressBar.style.background = "";
              progressText.style.color = "";
            }, 300);
          }, 3000);
        }

        // Reset model loading state
        for (let m in modelStatus) if (modelStatus[m].loading) modelStatus[m].loading = false;
        renderModels();

        // Show error toast
        showToast(data.message || "Errore durante il download del modello", "error");
      } else       if (data.status === "error") {
        console.error("Python Error:", data.message);
        if (statusEl) statusEl.textContent = "❌ Errore motore";
        for (let m in modelStatus) if (modelStatus[m].loading) modelStatus[m].loading = false;
        renderModels();

        // Show error toast for Python engine errors
        showToast(data.message || "Errore del motore Python", "error");
      }

      if (data.status === "rate_limit") {
        showToast(data.message, "error");
        updateModelDisplay();
        loadProviderDashboard();
      }

      // Gestione GPU Info
      if (data.status === "gpu_info") {
        const gpuStatusEl = document.querySelector("#gpu-status");
        if (gpuStatusEl) {
          const deviceLabel = data.current_device === "cuda" ? `GPU (${data.device_name})` : "CPU";
          const cudaLabel = data.cuda_available ? `CUDA disponibile (${data.device_name})` : "CUDA non disponibile";
          gpuStatusEl.textContent = `Dispositivo in uso: ${deviceLabel} | ${cudaLabel}`;
        }
      }

      // Gestione Volume (per visualizzatore)
      if (data.status === "volume") {
        targetVolume = data.value;
      }

      // Gestione Trascrizione Statistiche e Textbox
      if (data.status === "result" && data.text) {
        targetVolume = 0; // Reset visualizer
        // Update Box
        if (transcriptionBox) {
          const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          const newText = `[${timestamp}] ${data.text.trim()}\n`;
          transcriptionBox.value += newText;
          transcriptionBox.scrollTop = transcriptionBox.scrollHeight;
        }

        // Update Stats
        const wordCount = data.text.trim().split(/\s+/).filter(Boolean).length;
        if (wordCount > 0 && data.duration) {
          const wpm = Math.round((wordCount / data.duration) * 60);
          await invoke("update_stats", { words: wordCount, wpm, timeDelta: data.duration / 60 });
          await loadStats();
        }

        const historyTimestamp = new Date().toLocaleString("it-IT", {
          day: "2-digit", month: "2-digit", year: "numeric",
          hour: "2-digit", minute: "2-digit", second: "2-digit"
        });
        await invoke("save_transcription", {
          text: data.text.trim(),
          timestamp: historyTimestamp,
          wordCount: wordCount
        });

        await invoke("execute_paste", { text: data.text });

        if (selectedProvider === "cloud") { recordGroqUsage(data.duration); loadProviderDashboard(); }
      }
    } catch (err) {
      console.error("[python_output] Errore gestione evento:", err);
    }
  });

  listen("hotkey_error", (event) => {
    console.error("[hotkey] Errore:", event.payload);
    showToast(event.payload, "error");
  });

  // ── PULSANTE START REC (Anteprima Trascrizione) ──
  const startRecMain = document.querySelector("#start-rec-main");
  const transcriptionBox = document.querySelector("#transcription-box");
  const clearBtn = document.querySelector("#clear-text-btn");

  if (clearBtn && transcriptionBox) {
    clearBtn.addEventListener("click", () => {
      transcriptionBox.value = "";
    });
  }

  // ── INITIALIZE EXPORT FUNCTIONALITY ──
  initializeExportFunctionality(transcriptionBox, showToast);

  // ── GESTIONE TRASCRIZIONE UNIFICATA ──
  let activeTranscription = false;

  // Aggiorna aspetto del pulsante Trascrivi / Ferma
  function updateRecButton() {
    if (!startRecMain) return;
    const icon = startRecMain.querySelector(".icon");
    const text = startRecMain.querySelector(".text");
    if (activeTranscription) {
      startRecMain.classList.add("recording");
      if (icon) icon.textContent = "⏹️";
      if (text) text.textContent = "Ferma";
    } else {
      startRecMain.classList.remove("recording");
      if (icon) icon.textContent = "🎙️";
      if (text) text.textContent = "Trascrivi Ora";
    }
  }

  async function startTranscription() {
    if (activeTranscription) return;

    if (!modelReady) {
      showToast("Caricamento modello in corso, attendere...", "info");
      return;
    }

    activeTranscription = true;
    updateRecButton();
    console.log("[hold-to-speak] Inizio");

    const status = modelStatus[selectedModel] || { downloaded: false };
    if (selectedProvider !== "cloud" && !status.downloaded) {
      console.warn("[hold-to-speak] Modello non pronto.");
      activeTranscription = false;
      updateRecButton();
      showToast("Modello non scaricato. Scarica prima il modello dalla tab IA.", "error");
      return;
    }

    const device = document.querySelector("#audio-device").value;
    const language = document.querySelector("#transcription-language")?.value || selectedLanguage;
    await invoke("send_to_python", {
      message: JSON.stringify({
        command: "transcribe",
        model: selectedModel,
        device: device === "default" ? null : device,
        language: language,
        provider: selectedProvider,
      })
    });
  }

  async function stopTranscription() {
    if (!activeTranscription) return;
    activeTranscription = false;
    updateRecButton();
    console.log("[hold-to-speak] Fine");
    await invoke("send_to_python", {
      message: JSON.stringify({ command: "stop" })
    });
  }

  // ── PULSANTE TRASCRIVI ORA (click toggle) ──
  if (startRecMain) {
    startRecMain.addEventListener("click", () => {
      if (activeTranscription) {
        stopTranscription();
      } else {
        startTranscription();
      }
    });
  }

  // Legge la modalità hold-to-speak in tempo reale dal DOM
  function isHoldMode() {
    return document.querySelector("#hold-to-speak")?.checked ?? true;
  }

  // ── LISTENER EVENTI RUST ──
  console.log("[hotkey] Registrazione listener hotkey_pressed/released...");
  listen("hotkey_pressed", () => {
    if (!modelReady) {
      console.log("[hotkey] Ignorato: modello non ancora pronto");
      return;
    }
    console.log("[event] hotkey_pressed ricevuto da Rust, activeTranscription:", activeTranscription);
    if (isHoldMode()) {
      // Modalità "tieni premuto": avvia alla pressione
      startTranscription();
    } else {
      // Modalità "click toggle": alterna avvio/stop ad ogni pressione
      if (activeTranscription) {
        stopTranscription();
      } else {
        startTranscription();
      }
    }
  });

  listen("hotkey_released", () => {
    console.log("[event] hotkey_released ricevuto da Rust, activeTranscription:", activeTranscription);
    // In modalità hold: ferma al rilascio; in modalità toggle: nessuna azione
    if (isHoldMode()) {
      stopTranscription();
    }
  });
  console.log("[hotkey] Listener registrati OK");

  // ── LISTENER LOCALE (Fallback quando la finestra ha il focus) ──
  window.addEventListener("keydown", (e) => {
    const isControlAlt = e.ctrlKey && e.altKey;
    if (!isControlAlt || isRecording) return;
    if (!modelReady) {
      showToast("Caricamento modello in corso, attendere...", "info");
      return;
    }
    if (isHoldMode()) {
      startTranscription();
    } else {
      if (activeTranscription) {
        stopTranscription();
      } else {
        startTranscription();
      }
    }
  });

  window.addEventListener("keyup", (e) => {
    // In hold mode: ferma al rilascio di uno dei modificatori
    if (isHoldMode() && (e.key === "Control" || e.key === "Alt")) {
      stopTranscription();
    }
  });

  // ── VISUALIZZATORE REATTIVO (Volume-Driven) ──
  let canvas = document.getElementById("oscilloscope");
  let canvasCtx = canvas?.getContext("2d");
  let currentVolume = 0;
  let targetVolume = 0;
  let phase = 0;

  function draw() {
    requestAnimationFrame(draw);
    if (!canvas || !canvasCtx) return;

    // Smoothing del volume
    currentVolume += (targetVolume - currentVolume) * 0.15;
    if (currentVolume < 0.5) currentVolume = 0;

    canvasCtx.fillStyle = "#0a0a0a";
    canvasCtx.fillRect(0, 0, canvas.width, canvas.height);

    const centerY = canvas.height / 2;
    const volNorm = currentVolume / 100; // 0..1
    const amplitude = volNorm * (canvas.height / 2.5);

    canvasCtx.lineWidth = 2 + volNorm * 2;
    canvasCtx.strokeStyle = "#ff8c00";
    canvasCtx.shadowBlur = 8 + volNorm * 20;
    canvasCtx.shadowColor = "rgba(255, 140, 0, 0.8)";

    canvasCtx.beginPath();

    for (let x = 0; x < canvas.width; x += 2) {
      // Composite wave with pseudo-random variation driven by volume
      const mainWave = Math.sin(x * 0.05 + phase);
      const secondWave = Math.sin(x * 0.1 + phase * 1.5) * 0.5;
      const thirdWave = Math.sin(x * 0.02 + phase * 0.7) * 0.3;
      // Add jitter proportional to volume for a more organic, mic-like feel
      const jitter = volNorm * (Math.sin(x * 0.37 + phase * 3.1) * 0.4);

      const y = centerY + (mainWave + secondWave + thirdWave + jitter) * amplitude;

      if (x === 0) canvasCtx.moveTo(x, y);
      else canvasCtx.lineTo(x, y);
    }

    canvasCtx.stroke();
    // Wave moves faster when volume is higher
    phase += 0.05 + volNorm * 0.25;
  }

  function resizeCanvas() {
    if (canvas && canvas.parentElement) {
      canvas.width = canvas.parentElement.offsetWidth || 600;
      canvas.height = canvas.parentElement.offsetHeight || 90;
    }
  }
  
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();
  setTimeout(resizeCanvas, 500);
  draw();

  // ── CRONOLOGIA ──
  async function loadHistory() {
    const listEl = document.querySelector("#history-list");
    if (!listEl) return;

    try {
      const entries = await invoke("get_history");
      if (!entries || entries.length === 0) {
        listEl.innerHTML = '<p class="history-empty">Nessuna trascrizione salvata.</p>';
        return;
      }

      listEl.innerHTML = entries.map((entry, i) => {
        const preview = entry.text.length > 120 ? entry.text.substring(0, 120) + "..." : entry.text;
        return `
          <div class="history-card" data-index="${i}" title="Clicca per copiare">
            <div class="history-card-header">
              <span class="history-timestamp">${entry.timestamp}</span>
            </div>
            <p class="history-preview">${preview}</p>
          </div>
        `;
      }).join("");

      // Click per copiare negli appunti
      listEl.querySelectorAll(".history-card").forEach((card, i) => {
        card.addEventListener("click", async () => {
          const text = entries[i].text;
          try {
            await navigator.clipboard.writeText(text);
            card.classList.add("copied");
            const origHeader = card.querySelector(".history-timestamp").textContent;
            card.querySelector(".history-timestamp").textContent = "Copiato!";
            setTimeout(() => {
              card.classList.remove("copied");
              card.querySelector(".history-timestamp").textContent = origHeader;
            }, 1500);
          } catch (err) {
            console.error("[cronologia] Errore copia:", err);
          }
        });
      });
    } catch (err) {
      console.error("[cronologia] Errore caricamento:", err);
      listEl.innerHTML = '<p class="history-empty">Errore nel caricamento della cronologia.</p>';
    }
  }

  // Pulsante Cancella Cronologia
  const clearHistoryBtn = document.querySelector("#clear-history-btn");
  if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", async () => {
      try {
        await invoke("clear_history");
        const listEl = document.querySelector("#history-list");
        if (listEl) listEl.innerHTML = '<p class="history-empty">Nessuna trascrizione salvata.</p>';
        await loadStats();
      } catch (err) {
        console.error("[cronologia] Errore cancellazione:", err);
      }
    });
  }

});
