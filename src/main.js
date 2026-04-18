const { invoke } = window.__TAURI__.core;

let hotkeyInput;
let recordBtn;
let isRecording = false;
let selectedModel = "small";
let selectedLanguage = "it";
let computeDevice = "cpu";  // "cpu", "cuda", "auto"
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

// ─── CATALOGO MODELLI WHISPER (filtrato per: i5-11600K · 16GB RAM · RX 6500 XT) ──
const WHISPER_MODELS = [
  {
    id: "tiny",
    name: "Tiny",
    size: "75 MB",
    ram: "~1 GB",
    speed: 5,
    quality: 1,
    tag: null,
    description: "Velocissimo. Ideale per test rapidi o se hai mille altre app aperte. Precisione base sull'italiano.",
  },
  {
    id: "base",
    name: "Base",
    size: "145 MB",
    ram: "~1 GB",
    speed: 4,
    quality: 2,
    tag: null,
    description: "Leggero e reattivo. Buon punto di partenza per una dettatura informale.",
  },
  {
    id: "small",
    name: "Small",
    size: "466 MB",
    ram: "~2 GB",
    speed: 3,
    quality: 3,
    tag: "Consigliato",
    description: "Miglior equilibrio velocità/precisione per il tuo hardware. Ottimo per dettatura quotidiana in italiano.",
  },
  {
    id: "medium",
    name: "Medium",
    size: "1.5 GB",
    ram: "~5 GB",
    speed: 2,
    quality: 4,
    tag: null,
    description: "Alta precisione su accenti regionali e terminologia tecnica. Leggermente più lento, ma gestibile.",
  }
];

// ─── RENDER MODELLI ──────────────────────────────────────────────────────────
async function refreshAllModelStatus() {
  for (const m of WHISPER_MODELS) {
    const exists = await invoke("check_model_exists", { modelId: m.id });
    modelStatus[m.id] = { ...modelStatus[m.id], downloaded: exists };
  }
}

function renderModels() {
  const grid = document.querySelector(".model-grid");
  if (!grid) return;

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
    const m = WHISPER_MODELS.find(m => m.id === selectedModel);
    modelDisplay.textContent = m ? `Whisper ${m.name}` : selectedModel;
  }
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
    if (hotkeyInput) hotkeyInput.value = s.hotkey || "CommandOrControl+Space";
    
    const hotkeyDisplay = document.querySelector("#current-hotkey-display");
    if (hotkeyDisplay) hotkeyDisplay.textContent = s.hotkey || "CommandOrControl+Space";

    const minimizeTray = document.querySelector("#minimize-tray");
    const audioDevice  = document.querySelector("#audio-device");

    if (minimizeTray) minimizeTray.checked = s.minimizeTray ?? true;
    if (audioDevice && s.selectedDevice) audioDevice.value = s.selectedDevice;

    const langSelect = document.querySelector("#transcription-language");
    selectedLanguage = s.selectedLanguage || "it";
    if (langSelect) langSelect.value = selectedLanguage;

    const computeDeviceSelect = document.querySelector("#compute-device");
    computeDevice = s.computeDevice || "cpu";
    if (computeDeviceSelect) computeDeviceSelect.value = computeDevice;

    selectedModel = s.model || "small";
    await refreshAllModelStatus();
    renderModels();
    updateModelDisplay();

    console.log("[settings] Caricate:", s);
  } catch (err) {
    console.warn("[settings] Nessun file trovato, uso default.", err);
    await refreshAllModelStatus();
    renderModels();
    updateModelDisplay();
  }
}

async function loadStats() {
  try {
    const stats = await invoke("get_stats");
    const wordsEl = document.querySelector("#stat-words");
    const wpmEl   = document.querySelector("#stat-wpm");
    const timeEl  = document.querySelector("#stat-time");
    if (wordsEl) wordsEl.textContent = stats.total_words ?? 0;
    if (wpmEl)   wpmEl.textContent   = stats.avg_wpm     ?? 0;
    if (timeEl)  timeEl.textContent  = formatTime(stats.total_time ?? 0);
  } catch (err) {
    console.warn("[stats] Impossibile caricare stats:", err);
  }
}

async function persistSettings() {
  const settings = {
    hotkey:         hotkeyInput.value || "CommandOrControl+Space",
    model:          selectedModel,
    minimizeTray:   true,
    selectedDevice: document.querySelector("#audio-device").value,
    selectedLanguage: document.querySelector("#transcription-language")?.value || selectedLanguage,
    computeDevice: document.querySelector("#compute-device")?.value || computeDevice,
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

// ─── INIT ────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  hotkeyInput = document.querySelector("#hotkey");
  recordBtn   = document.querySelector("#record-btn");
  const saveBtn       = document.querySelector("#save-btn");
  const navLinks      = document.querySelectorAll(".nav-links li");
  const tabContents   = document.querySelectorAll(".tab-content");

  // Mostra versione app
  const appVersion = await getAppVersion();
  const versionEl = document.querySelector("#app-version");
  if (versionEl) versionEl.textContent = appVersion;
  const footerVersion = document.querySelector("#footer-version");
  if (footerVersion) footerVersion.textContent = `Traflix Voice v${appVersion}`;

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

  await loadAudioDevices();
  await loadSettings();
  await loadStats();

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

  navLinks.forEach(link => {
    link.addEventListener("click", () => {
      const targetTab = link.getAttribute("data-tab");
      navLinks.forEach(l => l.classList.remove("active"));
      link.classList.add("active");
      tabContents.forEach(tab => {
        tab.classList.remove("active");
        if (tab.id === targetTab) tab.classList.add("active");
      });
      if (targetTab === "home") loadStats();
      if (targetTab === "cronologia") loadHistory();
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

  saveBtn.addEventListener("click", async () => {
    // Permettiamo specificamente "Control+Alt" (o CommandOrControl+Alt)
    const isControlAlt = hotkeyInput.value === "CommandOrControl+Alt+..." || 
                         hotkeyInput.value === "Control+Alt+...";

    if (hotkeyInput.value.includes("...") && !isControlAlt) {
      alert("La scorciatoia non è completa! Premi un tasto finale (es. Spazio o una lettera) mentre tieni premuto Control/Alt.");
      return;
    }

    // Se è Control+Alt, puliamo la stringa dai puntini prima di salvare
    if (isControlAlt) {
      hotkeyInput.value = "CommandOrControl+Alt";
    }

    saveBtn.disabled = true;
    saveBtn.textContent = "Salvataggio...";
    try {
      const settings = await persistSettings();
      const hotkeyDisplay = document.querySelector("#current-hotkey-display");
      if (hotkeyDisplay) hotkeyDisplay.textContent = settings.hotkey;
      saveBtn.textContent = "✅ Salvato!";
      showToast("Scorciatoia salvata con successo", "success");
    } catch (err) {
      console.error("Errore salvataggio:", err);
      saveBtn.textContent = "❌ Errore";
      showToast("Errore nel salvataggio delle impostazioni", "error");
    }
    setTimeout(() => {
      saveBtn.textContent = "Salva Impostazioni";
      saveBtn.disabled = false;
    }, 2000);
  });

  // ── NOTIFICATION SOUNDS ──
  const startSound = new Audio("assets/sounds/start.wav");
  const stopSound = new Audio("assets/sounds/stop.wav");
  startSound.volume = 1.0;
  stopSound.volume = 1.0;

  // ── LISTENER OUTPUT PYTHON ──
  const { listen } = window.__TAURI__.event;
  const statusEl = document.querySelector("#transcription-status");

  listen("python_output", async (event) => {
    try {
      const data = JSON.parse(event.payload);

      if (statusEl) {
        if (data.status === "listening")  statusEl.textContent = "🎤 Registrazione in corso...";
        if (data.status === "processing") statusEl.textContent = "⚙️ Elaborazione...";
        if (data.status === "ready")      statusEl.textContent = "✅ Pronto";
        if (data.status === "result")     statusEl.textContent = "✅ Pronto";
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
      } else if (data.status === "error") {
        console.error("Python Error:", data.message);
        if (statusEl) statusEl.textContent = "❌ Errore motore";
        for (let m in modelStatus) if (modelStatus[m].loading) modelStatus[m].loading = false;
        renderModels();

        // Show error toast for Python engine errors
        showToast(data.message || "Errore del motore Python", "error");
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
    activeTranscription = true;
    updateRecButton();
    console.log("[hold-to-speak] Inizio");

    const status = modelStatus[selectedModel] || { downloaded: false };
    if (!status.downloaded) {
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
        language: language
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

  // ── LISTENER EVENTI RUST ──
  console.log("[hotkey] Registrazione listener hotkey_pressed/released...");
  listen("hotkey_pressed", () => {
    console.log("[event] hotkey_pressed ricevuto da Rust, activeTranscription:", activeTranscription);
    startTranscription();
  });

  listen("hotkey_released", () => {
    console.log("[event] hotkey_released ricevuto da Rust, activeTranscription:", activeTranscription);
    stopTranscription();
  });
  console.log("[hotkey] Listener registrati OK");

  // ── LISTENER LOCALE (Fallback quando la finestra ha il focus) ──
  window.addEventListener("keydown", (e) => {
    // Se la scorciatoia salvata è Control+Alt, o se l'utente la sta forzando
    const isControlAlt = e.ctrlKey && e.altKey;
    if (isControlAlt && !isRecording) {
      startTranscription();
    }
  });

  window.addEventListener("keyup", (e) => {
    // Rilasciamo se uno dei due viene alzato
    if (e.key === "Control" || e.key === "Alt") {
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
