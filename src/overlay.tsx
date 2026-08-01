import { useEffect, useRef } from "react";
import ReactDOM from "react-dom/client";

const IS_DEV = import.meta.env.DEV;

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

    const startSound = new Audio("/assets/sounds/start.wav");
    const stopSound = new Audio("/assets/sounds/stop.wav");
    startSound.volume = 1.0;
    stopSound.volume = 1.0;

    const style = document.createElement("style");
    style.textContent = `
      * { margin:0; padding:0; box-sizing:border-box; }
      html,body { background:transparent; overflow:hidden; user-select:none; -webkit-user-select:none; }
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
      .hint { position:absolute; top:calc(100% + 7px); left:0; display:flex; align-items:center; gap:6px; color:rgba(245,243,239,.72); font:600 10px/1 "Segoe UI",sans-serif; letter-spacing:.03em; white-space:nowrap; opacity:0; transform:translateY(-2px); pointer-events:none; transition:opacity .18s ease,transform .18s ease; text-shadow:0 1px 5px #000; }
      .ow:hover .hint { opacity:1; transform:translateY(0); }
      .devbadge { color:#ff626b; background:rgba(255,98,107,.15); border-radius:4px; padding:3px 5px; font-weight:800; letter-spacing:.12em; box-shadow:0 0 10px rgba(255,98,107,.16); }
    `;
    document.head.appendChild(style);

    root.innerHTML = `
      <div class="ow" id="w" role="button" aria-label="Traflix Voice. Doppio clic per aprire la console" tabindex="0">
        <div style="width:26px;height:26px;flex-shrink:0"><img src="/assets/logo.png" alt="Traflix" draggable="false" style="width:26px;height:26px;border-radius:6px" /></div>
        <span class="lbl">Traflix Voice</span>
        <div class="spw"><div class="spr"></div></div>
        <div class="vw" id="vw"></div>
        <span class="hint">${IS_DEV ? '<span class="devbadge">DEV</span>' : ""}<span id="version-meta">v…</span><span>· Doppio clic per aprire</span></span>
      </div>
    `;

    const widget = root.firstElementChild as HTMLDivElement;
    const vizWrap = widget.querySelector(".vw") as HTMLDivElement;
    const lbl = widget.querySelector(".lbl") as HTMLSpanElement;
    const versionMeta = widget.querySelector("#version-meta") as HTMLSpanElement;

    if (window.__TAURI__?.app?.getVersion) {
      window.__TAURI__.app.getVersion().then((version: string) => {
        versionMeta.textContent = `v${version}`;
      }).catch(() => {});
    }

    for (let i = 0; i < 14; i++) {
      const bar = document.createElement("div");
      bar.className = "bar";
      vizWrap.appendChild(bar);
      bars.push(bar);
    }

    function resizeToFit() {
      requestAnimationFrame(() => {
        const w = widget.offsetWidth + 4;
        const h = widget.offsetHeight + 4;
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

    // Listen for python_output
    window.__TAURI__.event
      .listen("python_output", (event: { payload: unknown }) => {
        try {
          const data = JSON.parse(event.payload as string);

          if (data.status === "listening") {
            isListening = true;
            isProcessing = false;
            widget.className = "ow rec";
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
      unlistenFns.forEach((fn) => fn());
      if (style.parentNode) style.parentNode.removeChild(style);
    };
  }, []);

  return <div ref={rootRef} />;
}

ReactDOM.createRoot(document.getElementById("overlay-root")!).render(
  <Overlay />
);
