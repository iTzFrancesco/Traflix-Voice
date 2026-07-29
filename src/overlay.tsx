import { useEffect, useRef } from "react";
import ReactDOM from "react-dom/client";

function Overlay() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    let lastClick = 0;
    let currentVolume = 0;
    let targetVolume = 0;
    const barHeights = new Array(14).fill(3);
    const barTargets = new Array(14).fill(3);
    const bars: HTMLDivElement[] = [];
    let widgetMode = "always";
    let isListening = false;
    let isProcessing = false;
    let animationFrame = 0;
    let countdownTimer = 0;

    const startSound = new Audio("/assets/sounds/start.wav");
    const stopSound = new Audio("/assets/sounds/stop.wav");
    startSound.volume = 1.0;
    stopSound.volume = 1.0;

    const style = document.createElement("style");
    style.textContent = `
      * { margin:0; padding:0; box-sizing:border-box; }
      html,body { background:transparent; overflow:hidden; user-select:none; -webkit-user-select:none; }
      .shell { display:inline-flex; flex-direction:column; align-items:stretch; gap:6px; padding:2px; }
      @keyframes spin { to { transform:rotate(360deg); } }
      .ow { height:38px; background:rgba(18,19,17,0.96); border:1px solid rgba(255,157,36,0.4); border-radius:12px; display:inline-flex; align-items:center; gap:4px; padding:0 10px 0 8px; cursor:grab; position:relative; transition:all 0.3s cubic-bezier(0.4,0,0.2,1); }
      .ow:active { cursor:grabbing; }
      .ow:hover { border-color:rgba(255,140,0,0.5); box-shadow:0 0 10px rgba(255,140,0,0.1); }
      .ow.rec { border-color:rgba(255,140,0,0.5); box-shadow:0 0 12px rgba(255,140,0,0.12); }
      .ow.proc { border-color:rgba(255,140,0,0.3); }
      .lbl { font-size:0.82rem; font-weight:800; white-space:nowrap; letter-spacing:0.3px; background:linear-gradient(135deg,#ff8c00 0%,#ffb347 50%,#ff8c00 100%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; transition:opacity 0.25s ease,width 0.3s ease,margin 0.3s ease; overflow:hidden; }
      .ow.rec .lbl, .ow.proc .lbl { opacity:0; width:0px !important; margin:0; }
      .spw { display:flex; align-items:center; justify-content:center; width:0px; overflow:hidden; opacity:0; transition:width 0.3s cubic-bezier(0.4,0,0.2,1),opacity 0.25s ease; }
      .ow.proc .spw { width:20px; opacity:1; }
      .spr { width:16px; height:16px; border:2px solid transparent; border-top-color:#ff8c00; border-right-color:rgba(255,140,0,0.3); border-radius:50%; animation:spin 0.9s cubic-bezier(0.4,0,0.2,1) infinite; flex-shrink:0; }
      .vw { display:flex; align-items:center; justify-content:center; gap:2px; width:0px; overflow:hidden; opacity:0; transition:width 0.3s cubic-bezier(0.4,0,0.2,1),opacity 0.25s ease; }
      .ow.rec .vw { width:80px; opacity:1; }
      .bar { width:2.5px; background:#ff8c00; border-radius:2px; height:3px; transition:height 0.08s ease; box-shadow:0 0 4px rgba(255,140,0,0.35); flex-shrink:0; }
      .prompt-slot { display:flex; justify-content:flex-end; max-height:0; padding-right:5px; opacity:0; overflow:hidden; transform:translateY(-6px); pointer-events:none; transition:max-height .2s ease,opacity .15s ease,transform .2s ease; }
      .shell.expanded .prompt-slot { max-height:36px; opacity:1; transform:translateY(0); pointer-events:auto; }
      .prompt-action { height:27px; display:flex; align-items:center; gap:6px; border:0; background:transparent; border-radius:8px; color:#d8d0c5; cursor:pointer; padding:0 5px 0 2px; font:700 9px/1 "Segoe UI",sans-serif; letter-spacing:.04em; white-space:nowrap; transition:color .16s ease,background .16s ease,transform .16s ease; }
      .prompt-action:hover { color:#fff4df; background:rgba(255,157,36,.1); transform:translateY(-1px); }
      .prompt-action:disabled { color:#8a837a; cursor:default; }
      .prompt-icon { display:grid; width:21px; height:21px; place-items:center; border:1px solid rgba(255,157,36,.48); border-radius:50%; background:rgba(255,157,36,.13); color:#ffb14b; font-size:12px; box-shadow:0 0 12px rgba(255,140,0,.12); }
      .count { min-width:22px; color:#8f8a82; font:700 9px/1 "Segoe UI",sans-serif; text-align:right; }
      .preview { display:none; width:326px; border:1px solid rgba(255,157,36,.28); border-radius:12px; background:rgba(18,19,17,.98); padding:11px 12px; box-shadow:0 10px 34px rgba(0,0,0,.38); color:#e8e3db; font:11px/1.4 "Segoe UI",sans-serif; }
      .shell.show-preview .preview { display:block; }
      .preview-label { color:#ffad43; text-transform:uppercase; letter-spacing:.1em; font-size:9px; font-weight:800; }
      .preview-text { margin-top:5px; max-height:48px; overflow:hidden; color:#cfc9bf; }
      .preview-actions { display:flex; gap:7px; margin-top:9px; }
      .preview-actions button { border:1px solid rgba(255,255,255,.1); border-radius:7px; background:rgba(255,255,255,.05); color:#eee8df; padding:6px 9px; cursor:pointer; font:700 10px/1 "Segoe UI",sans-serif; }
      .preview-actions .undo { border-color:rgba(255,157,36,.35); color:#ffc26d; }
    `;
    document.head.appendChild(style);

    root.innerHTML = `
      <div class="shell" id="shell">
        <div class="ow" id="w" role="button" aria-label="Traflix Voice. Doppio clic per aprire la console" tabindex="0">
          <div style="width:26px;height:26px;flex-shrink:0"><img src="/assets/logo.png" alt="Traflix" draggable="false" style="width:26px;height:26px;border-radius:6px" /></div>
          <span class="lbl">Traflix Voice</span>
          <div class="spw"><div class="spr"></div></div>
          <div class="vw" id="vw"></div>
        </div>
        <div class="prompt-slot">
          <button class="prompt-action" id="prompt-engineer" type="button" title="Migliora l’ultima dettatura come prompt" disabled>
            <span class="prompt-icon">✦</span>
            <span>Migliora prompt</span>
            <span class="count" id="count"></span>
          </button>
        </div>
        <div class="preview" id="preview">
          <div class="preview-label">Trasformazione applicata</div>
          <div class="preview-text" id="preview-text"></div>
          <div class="preview-actions"><button class="undo" id="undo-transform" type="button">↶ Ripristina originale</button><button id="close-preview" type="button">Chiudi</button></div>
        </div>
      </div>
    `;

    const shell = root.querySelector("#shell") as HTMLDivElement;
    const widget = root.querySelector("#w") as HTMLDivElement;
    const vizWrap = widget.querySelector(".vw") as HTMLDivElement;
    const promptButton = shell.querySelector("#prompt-engineer") as HTMLButtonElement;
    const count = shell.querySelector("#count") as HTMLSpanElement;
    const previewText = shell.querySelector("#preview-text") as HTMLDivElement;
    const undoTransform = shell.querySelector("#undo-transform") as HTMLButtonElement;
    const closePreview = shell.querySelector("#close-preview") as HTMLButtonElement;
    let transformAvailable = false;

    for (let i = 0; i < 14; i++) {
      const bar = document.createElement("div");
      bar.className = "bar";
      vizWrap.appendChild(bar);
      bars.push(bar);
    }

    function resizeToFit() {
      requestAnimationFrame(() => {
        const w = Math.max(50, shell.scrollWidth + 4);
        const h = Math.max(50, shell.scrollHeight + 4);
        if (window.__TAURI__?.window?.getCurrentWindow) {
          const aw = window.__TAURI__.window.getCurrentWindow();
          if (window.__TAURI__.window?.LogicalSize) {
            aw.setSize(new window.__TAURI__.window.LogicalSize(w, h)).catch(() => {});
          }
        }
      });
    }

    // ── SHOW / HIDE WINDOW BASED ON WIDGET MODE ──
    async function syncOverlayVisibility() {
      if (!window.__TAURI__?.window?.getCurrentWindow) return;
      const win = window.__TAURI__.window.getCurrentWindow();
      if (widgetMode === "recording") {
        // Show only if recording is active
        if (isListening || isProcessing) {
          await win.show().catch(() => {});
        } else {
          await win.hide().catch(() => {});
        }
      }
      // If mode is "always", visibility is managed by Rust (don't override)
    }

    // ── MOUSE CLICK (double-click to show main) ──
    widget.addEventListener("mousedown", (e: MouseEvent) => {
      const now = Date.now();
      if (now - lastClick < 300) {
        lastClick = 0;
        window.__TAURI__.event.emit("show_main_window", {}).catch(() => {});
        return;
      }
      lastClick = now;
      if (window.__TAURI__?.window?.getCurrentWindow) {
        window.__TAURI__.window.getCurrentWindow().startDragging().catch(() => {});
      }
    });
    shell.addEventListener("mouseenter", () => {
      shell.classList.add("expanded");
      setTimeout(resizeToFit, 20);
      setTimeout(resizeToFit, 220);
    });
    shell.addEventListener("mouseleave", () => {
      shell.classList.remove("expanded");
      setTimeout(resizeToFit, 220);
    });
    promptButton.addEventListener("mousedown", (e) => e.stopPropagation());
    promptButton.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!transformAvailable) return;
      promptButton.disabled = true;
      transformAvailable = false;
      shell.classList.remove("transform-ready", "expanded");
      window.clearInterval(countdownTimer);
      resizeToFit();
      window.__TAURI__.event.emit("enhance_prompt_request", {}).catch(() => {});
    });
    undoTransform.addEventListener("click", () => {
      undoTransform.disabled = true;
      window.__TAURI__.event.emit("restore_transform_request", {}).catch(() => {});
    });
    closePreview.addEventListener("click", () => {
      shell.classList.remove("show-preview");
      resizeToFit();
    });
    widget.addEventListener("keydown", (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        window.__TAURI__.event.emit("show_main_window", {}).catch(() => {});
      }
    });

    // ── EVENT LISTENERS ──
    let overlayCancelled = false;
    const unlistenFns: (() => void)[] = [];

    // Listen for widget_mode_updated
    window.__TAURI__.event
      .listen("widget_mode_updated", (event: { payload: unknown }) => {
        const mode = event.payload as string;
        widgetMode = mode === "recording" ? "recording" : "always";
        syncOverlayVisibility();
      })
      .then((fn) => {
        if (overlayCancelled) fn(); else unlistenFns.push(fn);
      });

    window.__TAURI__.event.listen("transform_available", (event: { payload: unknown }) => {
      transformAvailable = true;
      promptButton.disabled = false;
      if (!isListening && !isProcessing) shell.classList.add("transform-ready");
      if (shell.matches(":hover")) shell.classList.add("expanded");
      const expiresAt = Number((event.payload as { expiresAt?: number })?.expiresAt ?? Date.now());
      const updateCount = () => {
        const remaining = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
        count.textContent = `${remaining}s`;
        if (remaining === 0) {
          window.clearInterval(countdownTimer);
          transformAvailable = false;
          shell.classList.remove("transform-ready");
          resizeToFit();
        }
      };
      updateCount();
      window.clearInterval(countdownTimer);
      countdownTimer = window.setInterval(updateCount, 250);
      resizeToFit();
    }).then((fn) => { if (overlayCancelled) fn(); else unlistenFns.push(fn); });
    window.__TAURI__.event.listen("transform_finished", () => {
      promptButton.disabled = true;
      undoTransform.disabled = false;
      transformAvailable = false;
      shell.classList.remove("transform-ready");
      shell.classList.remove("show-preview");
      window.clearInterval(countdownTimer);
      resizeToFit();
    }).then((fn) => { if (overlayCancelled) fn(); else unlistenFns.push(fn); });
    window.__TAURI__.event.listen("transform_result", (event: { payload: unknown }) => {
      const result = event.payload as { original?: string; transformed?: string };
      previewText.textContent = `${result.original ?? ""}  →  ${result.transformed ?? ""}`;
      promptButton.disabled = true;
      transformAvailable = false;
      shell.classList.remove("transform-ready");
      shell.classList.add("show-preview");
      window.clearInterval(countdownTimer);
      resizeToFit();
    }).then((fn) => { if (overlayCancelled) fn(); else unlistenFns.push(fn); });

    // Listen for python_output
    window.__TAURI__.event
      .listen("python_output", (event: { payload: unknown }) => {
        try {
          const data = JSON.parse(event.payload as string);

          if (data.status === "listening") {
            isListening = true;
            isProcessing = false;
            widget.className = "ow rec";
            transformAvailable = false;
            promptButton.disabled = true;
            shell.classList.remove("show-preview", "transform-ready", "expanded");
            window.clearInterval(countdownTimer);
            widget.setAttribute("aria-label", "Traflix Voice. Registrazione in corso. Doppio clic per aprire la console");
            startSound.currentTime = 0;
            startSound.play().catch(() => {});
            syncOverlayVisibility();
            setTimeout(resizeToFit, 350);
          } else if (data.status === "processing") {
            isListening = false;
            isProcessing = true;
            widget.className = "ow proc";
            widget.setAttribute("aria-label", "Traflix Voice. Elaborazione della trascrizione. Doppio clic per aprire la console");
            targetVolume = 0;
            stopSound.currentTime = 0;
            stopSound.play().catch(() => {});
            syncOverlayVisibility();
            setTimeout(resizeToFit, 350);
          } else if (data.status === "result" || data.status === "ready") {
            isListening = false;
            isProcessing = false;
            if (widget.classList.contains("rec") || widget.classList.contains("proc")) {
              widget.className = "ow";
              widget.setAttribute("aria-label", "Traflix Voice pronta. Doppio clic per aprire la console");
              targetVolume = 0;
              syncOverlayVisibility();
              setTimeout(resizeToFit, 350);
            }
          } else if (data.status === "transforming") {
            widget.className = "ow proc";
            isProcessing = true;
            resizeToFit();
          } else if (data.status === "transformed" || data.status === "transform_error") {
            isProcessing = false;
            widget.className = "ow";
            promptButton.disabled = true;
            resizeToFit();
          } else if (data.status === "error" || data.status === "rate_limit") {
            isListening = false;
            isProcessing = false;
            if (widget.classList.contains("rec") || widget.classList.contains("proc")) {
              widget.className = "ow";
              widget.setAttribute("aria-label", "Traflix Voice pronta. Doppio clic per aprire la console");
              targetVolume = 0;
              syncOverlayVisibility();
              setTimeout(resizeToFit, 350);
            }
          } else if (data.status === "volume") {
            targetVolume = data.value;
          }
        } catch (_) {}
      })
      .then((fn) => {
        if (overlayCancelled) fn(); else unlistenFns.push(fn);
      });

    // ── LOAD INITIAL WIDGET MODE ──
    async function loadInitialMode() {
      try {
        if (window.__TAURI__?.core?.invoke) {
          const s = await window.__TAURI__.core.invoke("load_settings") as { widgetMode?: string };
          if (s && s.widgetMode === "recording") {
            widgetMode = "recording";
          }
          // Sync visibility with initial mode state
          await syncOverlayVisibility();
        }
      } catch (_) {}
    }
    loadInitialMode();

    // ── ANIMATION LOOP ──
    function animate() {
      animationFrame = requestAnimationFrame(animate);

      currentVolume += (targetVolume - currentVolume) * 0.2;
      if (currentVolume < 0.5) currentVolume = 0;

      const volNorm = currentVolume / 100;
      const maxH = 20;
      const minH = 3;

      for (let i = 0; i < 14; i++) {
        const center = 14 / 2;
        const dist = Math.abs(i - center) / center;
        const bellFactor = 1 - dist * 0.5;
        const jitter = 0.6 + Math.random() * 0.4;

        barTargets[i] = minH + volNorm * maxH * bellFactor * jitter;
        barHeights[i] += (barTargets[i] - barHeights[i]) * 0.25;

        const h = Math.max(minH, Math.min(maxH, barHeights[i]));
        bars[i].style.height = h + "px";
        const glow = (h / maxH) * 6;
        bars[i].style.boxShadow = `0 0 ${glow}px rgba(255, 140, 0, ${0.3 + (h / maxH) * 0.4})`;
      }
    }

    animate();
    resizeToFit();

    return () => {
      overlayCancelled = true;
      cancelAnimationFrame(animationFrame);
      window.clearInterval(countdownTimer);
      unlistenFns.forEach((fn) => fn());
      if (style.parentNode) style.parentNode.removeChild(style);
    };
  }, []);

  return <div ref={rootRef} />;
}

ReactDOM.createRoot(document.getElementById("overlay-root")!).render(
  <Overlay />
);
