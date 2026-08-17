import { useEffect, useRef } from "react";
import ReactDOM from "react-dom/client";

const IS_DEV = import.meta.env.DEV || ["localhost", "127.0.0.1"].includes(window.location.hostname);

function responsiveVolume(value: number): number {
  const normalized = Math.min(1, Math.max(0, value / 100));
  if (normalized === 0) return 0;

  // A sub-linear curve makes quiet speech visible while preserving headroom
  // for louder peaks instead of clipping the bars immediately.
  return Math.min(1, Math.pow(normalized, 0.68) * 1.12);
}

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
      html,body { width:100%; height:100%; background:transparent; overflow:hidden; user-select:none; -webkit-user-select:none; }
      #overlay-root { width:100%; height:100%; display:flex; align-items:center; justify-content:flex-start; }
      :root { --voice-gradient:linear-gradient(180deg,#ff8c00 0%,#ffd27a 50%,#ff8c00 100%); --separator-gradient:linear-gradient(180deg,rgba(255,98,107,0) 0%,rgba(255,98,107,.95) 50%,rgba(255,98,107,0) 100%); }
      @keyframes spin { to { transform:rotate(360deg); } }
      .ow { height:38px; background:rgba(18,19,17,0.96); border:1px solid rgba(255,157,36,0.4); border-radius:12px; display:inline-flex; align-items:center; gap:4px; padding:0 10px 0 8px; cursor:grab; position:relative; transition:border-color 0.3s cubic-bezier(0.4,0,0.2,1),box-shadow 0.3s cubic-bezier(0.4,0,0.2,1); }
      .ow:active { cursor:grabbing; }
      .ow:hover { border-color:rgba(255,140,0,0.5); box-shadow:0 0 10px rgba(255,140,0,0.1); }
      .ow.rec { border-color:rgba(255,140,0,0.5); box-shadow:0 0 12px rgba(255,140,0,0.12); }
      .ow.proc { border-color:rgba(255,140,0,0.3); }
      .lbl { font-size:0.82rem; font-weight:800; white-space:nowrap; letter-spacing:0.3px; background:var(--voice-gradient); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; max-width:90px; transition:opacity 0.25s ease,max-width 0.3s cubic-bezier(0.4,0,0.2,1),margin 0.3s ease; overflow:hidden; flex-shrink:0; }
      .ow.rec .lbl, .ow.proc .lbl { opacity:0; max-width:0; margin:0; }
      .spw { display:flex; align-items:center; justify-content:center; width:0px; overflow:hidden; opacity:0; transition:width 0.3s cubic-bezier(0.4,0,0.2,1),opacity 0.25s ease; }
      .ow.proc .spw { width:20px; opacity:1; }
      .spr { width:16px; height:16px; border:2px solid transparent; border-radius:50%; background:linear-gradient(rgba(18,19,17,.96),rgba(18,19,17,.96)) padding-box,conic-gradient(from 0deg,#ff8c00,#ffd27a,#ff8c00) border-box; animation:spin 0.9s cubic-bezier(0.4,0,0.2,1) infinite; flex-shrink:0; }
      .vw { display:flex; align-items:center; justify-content:center; gap:2px; width:0px; overflow:hidden; opacity:0; transition:width 0.3s cubic-bezier(0.4,0,0.2,1),opacity 0.25s ease; }
      .ow.rec .vw { width:80px; opacity:1; }
      .bar { width:2.5px; background:var(--voice-gradient); border-radius:2px; height:3px; transition:height 0.08s ease; box-shadow:0 0 4px rgba(255,190,90,0.38); flex-shrink:0; }
      .sep { width:0px; height:16px; flex-shrink:0; background:var(--separator-gradient); border-radius:99px; box-shadow:0 0 6px rgba(255,98,107,0.42); opacity:0; visibility:hidden; transition:width 0.3s cubic-bezier(0.4,0,0.2,1),opacity 0.25s ease,margin-left 0.3s cubic-bezier(0.4,0,0.2,1); }
      .ow.rec .sep { width:2.5px; opacity:1; visibility:visible; margin-left:-8px; }
      .hint { position:absolute; top:calc(100% + 7px); left:0; display:flex; align-items:center; gap:6px; color:rgba(245,243,239,.72); font:600 10px/1 "Segoe UI",sans-serif; letter-spacing:.03em; white-space:nowrap; opacity:0; transform:translateY(-2px); pointer-events:none; transition:opacity .18s ease,transform .18s ease; text-shadow:0 1px 5px #000; }
      .ow:hover .hint { opacity:1; transform:translateY(0); }
      .devbadge { color:#ff626b; background:rgba(255,98,107,.15); border-radius:4px; padding:3px 5px; font-weight:800; letter-spacing:.12em; box-shadow:0 0 10px rgba(255,98,107,.16); }
      .dev-slot { display:inline-flex; align-items:center; justify-content:center; height:100%; }
      .widget-devbadge { background:transparent; color:#ff7b83; font:800 9px/1 "Segoe UI",sans-serif; letter-spacing:.1em; padding:0 1px; text-shadow:0 0 6px rgba(255,98,107,.45); }
    `;
    document.head.appendChild(style);

    root.innerHTML = `
      <div class="ow" id="w" role="button" aria-label="Traflix Voice. Doppio clic per aprire la console" tabindex="0">
        <div style="width:26px;height:26px;flex-shrink:0"><img src="/assets/logo.png" alt="Traflix" draggable="false" style="width:26px;height:26px;border-radius:6px" /></div>
        <span class="lbl">Traflix Voice</span>
        <span class="dev-slot">${IS_DEV ? '<span class="devbadge widget-devbadge">DEV</span>' : ""}</span>
        <div class="spw"><div class="spr"></div></div>
        <div class="sep" id="sep"></div>
        <div class="vw" id="vw"></div>
        <span class="hint"><span id="version-meta">v…</span><span>· Doppio clic per aprire</span></span>
      </div>
    `;

    const widget = root.firstElementChild as HTMLDivElement;
    const vizWrap = widget.querySelector(".vw") as HTMLDivElement;
    const versionMeta = widget.querySelector("#version-meta") as HTMLSpanElement;

    if (!IS_DEV && window.__TAURI__?.core?.invoke) {
      window.__TAURI__.core.invoke("is_dev").then((isDev: unknown) => {
        if (isDev !== true) return;
        const slot = widget.querySelector(".dev-slot");
        if (!slot || slot.querySelector(".devbadge")) return;
        const badge = document.createElement("span");
        badge.className = "devbadge widget-devbadge";
        badge.textContent = "DEV";
        slot.appendChild(badge);
      }).catch(() => {});
    }

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

    // ── SHOW / HIDE WINDOW BASED ON WIDGET MODE ──
    let requestedVisibility: boolean | null = null;
    let visibilityQueue = Promise.resolve();

    function syncOverlayVisibility() {
      if (!window.__TAURI__?.window?.getCurrentWindow) return;

      // In "always" mode Rust owns visibility. Invalidating the requested
      // target prevents an older queued hide/show from winning after a mode
      // switch.
      if (widgetMode !== "recording") {
        requestedVisibility = null;
        return;
      }

      const shouldShow = isListening || isProcessing;
      if (requestedVisibility === shouldShow) return;
      requestedVisibility = shouldShow;

      const win = window.__TAURI__.window.getCurrentWindow();
      visibilityQueue = visibilityQueue
        .catch(() => {})
        .then(async () => {
          // A newer state may have superseded this request while it waited in
          // the queue. The newer request will perform the native operation.
          if (widgetMode !== "recording" || requestedVisibility !== shouldShow) return;
          if (shouldShow) await win.show();
          else await win.hide();
        })
        .catch(() => {});
    }

    type WidgetVisualState = "idle" | "recording" | "processing";
    let visualState: WidgetVisualState = "idle";

    function applyVisualState(nextState: WidgetVisualState) {
      const stateChanged = visualState !== nextState;
      visualState = nextState;
      isListening = nextState === "recording";
      isProcessing = nextState === "processing";
      targetVolume = nextState === "recording" ? targetVolume : 0;

      if (!stateChanged) {
        // Duplicate events must not replay sounds or trigger native work.
        return;
      }

      if (nextState === "recording") {
        widget.className = "ow rec";
        widget.setAttribute("aria-label", "Traflix Voice. Registrazione in corso. Doppio clic per aprire la console");
        startSound.currentTime = 0;
        startSound.play().catch(() => {});
      } else if (nextState === "processing") {
        widget.className = "ow proc";
        widget.setAttribute("aria-label", "Traflix Voice. Elaborazione della trascrizione. Doppio clic per aprire la console");
        stopSound.currentTime = 0;
        stopSound.play().catch(() => {});
      } else {
        widget.className = "ow";
        widget.setAttribute("aria-label", "Traflix Voice pronta. Doppio clic per aprire la console");
      }

      syncOverlayVisibility();
      scheduleAnimation();
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
        requestedVisibility = null;
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
            applyVisualState("recording");
          } else if (data.status === "processing") {
            applyVisualState("processing");
          } else if (data.status === "result" || data.status === "ready" || data.status === "error" || data.status === "rate_limit") {
            applyVisualState("idle");
          } else if (data.status === "volume") {
            targetVolume = data.value;
            scheduleAnimation();
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
    function scheduleAnimation() {
      if (!animationFrame) animationFrame = requestAnimationFrame(animate);
    }

    function animate() {
      animationFrame = 0;

      currentVolume += (targetVolume - currentVolume) * 0.2;
      if (currentVolume < 0.5) currentVolume = 0;

      const volNorm = responsiveVolume(currentVolume);
      const maxH = 30;
      const minH = 3;

      for (let i = 0; i < 14; i++) {
        const center = 14 / 2;
        const dist = Math.abs(i - center) / center;
        const bellFactor = 1 - dist * 0.5;
        const jitter = 0.6 + Math.random() * 0.4;

        barTargets[i] = minH + volNorm * (maxH - minH) * bellFactor * jitter;
        barHeights[i] += (barTargets[i] - barHeights[i]) * 0.25;

        const h = Math.max(minH, Math.min(maxH, barHeights[i]));
        bars[i].style.height = h + "px";
        const glow = (h / maxH) * 6;
        bars[i].style.boxShadow = `0 0 ${glow}px rgba(255, 190, 90, ${0.3 + (h / maxH) * 0.4})`;
      }

      if (visualState !== "idle" || currentVolume >= 0.5) {
        scheduleAnimation();
      }
    }

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
