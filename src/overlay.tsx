import { useEffect, useRef } from "react";
import ReactDOM from "react-dom/client";

const IS_DEV = import.meta.env.DEV || ["localhost", "127.0.0.1"].includes(window.location.hostname);
const WIDGET_EXIT_MS = 220;

const RESPONSIVE_VOLUME_LUT = Array.from({ length: 101 }, (_, index) => {
  const normalized = index / 100;
  return normalized === 0
    ? 0
    : Math.min(1, Math.pow(normalized, 0.68) * 1.12);
});

function responsiveVolume(value: number): number {
  const normalized = Math.min(1, Math.max(0, value / 100));
  if (normalized === 0) return 0;

  const scaled = normalized * 100;
  const lower = Math.floor(scaled);
  const upper = Math.min(100, lower + 1);
  const fraction = scaled - lower;
  return (
    RESPONSIVE_VOLUME_LUT[lower] +
    (RESPONSIVE_VOLUME_LUT[upper] - RESPONSIVE_VOLUME_LUT[lower]) * fraction
  );
}

function compactVolumeFromPayload(payload: unknown): number | null {
  if (typeof payload !== "string") return null;
  const compactPrefix = '{"status":"volume","value":';
  const legacyPrefix = '{"status": "volume", "value":';
  const prefix = payload.startsWith(compactPrefix)
    ? compactPrefix
    : payload.startsWith(legacyPrefix)
      ? legacyPrefix
      : null;
  if (!prefix) return null;
  const end = payload.indexOf("}", prefix.length);
  const value = Number(payload.slice(prefix.length, end < 0 ? undefined : end));
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
}

const COMPACT_STATUS_PREFIXES: ReadonlyArray<readonly [string, string]> = [
  ['{"status":"listening"', "listening"],
  ['{"status": "listening"', "listening"],
  ['{"status":"processing"', "processing"],
  ['{"status": "processing"', "processing"],
  ['{"status":"result"', "result"],
  ['{"status": "result"', "result"],
  ['{"status":"ready"', "ready"],
  ['{"status": "ready"', "ready"],
  ['{"status":"error"', "error"],
  ['{"status": "error"', "error"],
  ['{"status":"rate_limit"', "rate_limit"],
  ['{"status": "rate_limit"', "rate_limit"],
];

function compactStatusFromPayload(payload: unknown): string | null {
  if (typeof payload !== "string") return null;
  for (const [prefix, status] of COMPACT_STATUS_PREFIXES) {
    if (payload.startsWith(prefix)) return status;
  }
  return null;
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
    const barJitters = Array.from(
      { length: 14 },
      () => 0.84 + Math.random() * 0.16,
    );
    const barPhases = Array.from(
      { length: 14 },
      (_, index) => index * 0.42 + Math.random() * 0.75,
    );
    const barSpeeds = Array.from(
      { length: 14 },
      () => 0.9 + Math.random() * 0.22,
    );
    const barFactors = Array.from({ length: 14 }, (_, i) => {
      const center = (14 - 1) / 2;
      return 1 - (Math.abs(i - center) / center) * 0.28;
    });
    const bars: HTMLDivElement[] = [];
    let widgetMode = "always";
    let isListening = false;
    let isProcessing = false;
    let animationFrame = 0;
    let animationTime = 0;
    let lastFrameTime = performance.now();
    let widgetMotion: "enter" | "exit" | null = null;
    let isOpeningMain = false;

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
      @keyframes widget-enter { 0% { opacity:0; transform:translate3d(0,8px,0) scale(.92); filter:blur(2px); } 58% { opacity:1; transform:translate3d(0,-1px,0) scale(1.018); filter:blur(0); } 100% { opacity:1; transform:translate3d(0,0,0) scale(1); filter:blur(0); } }
      @keyframes widget-exit { 0% { opacity:1; transform:translate3d(0,0,0) scale(1); filter:blur(0); } 100% { opacity:0; transform:translate3d(0,-5px,0) scale(.94); filter:blur(1.5px); } }
      .ow { height:38px; background:rgba(18,19,17,0.96); border:1px solid rgba(255,157,36,0.4); border-radius:12px; display:inline-flex; align-items:center; gap:4px; padding:0 10px 0 8px; cursor:grab; position:relative; transition:border-color 0.3s cubic-bezier(0.4,0,0.2,1),box-shadow 0.3s cubic-bezier(0.4,0,0.2,1); }
      .ow.widget-enter { animation:widget-enter .42s cubic-bezier(.22,1,.36,1) both; }
      .ow.widget-exit { animation:widget-exit .22s cubic-bezier(.4,0,1,1) both; pointer-events:none; }
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
      .bar { width:2.5px; background:var(--voice-gradient); border-radius:2px; height:30px; transform:scaleY(.1); transform-origin:center; box-shadow:0 0 5px rgba(255,190,90,0.48); flex-shrink:0; will-change:transform; }
      .sep { width:0px; height:16px; flex-shrink:0; background:var(--separator-gradient); border-radius:99px; box-shadow:0 0 6px rgba(255,98,107,0.42); opacity:0; visibility:hidden; transition:width 0.3s cubic-bezier(0.4,0,0.2,1),opacity 0.25s ease,margin-left 0.3s cubic-bezier(0.4,0,0.2,1); }
      .ow.rec .sep { width:2.5px; opacity:1; visibility:visible; margin-left:-8px; }
      .hint { position:absolute; top:calc(100% + 7px); left:0; display:flex; align-items:center; gap:6px; color:rgba(245,243,239,.72); font:600 10px/1 "Segoe UI",sans-serif; letter-spacing:.03em; white-space:nowrap; opacity:0; transform:translateY(-2px); pointer-events:none; transition:opacity .18s ease,transform .18s ease; text-shadow:0 1px 5px #000; }
      .ow:hover .hint { opacity:1; transform:translateY(0); }
      .devbadge { color:#ff626b; background:rgba(255,98,107,.15); border-radius:4px; padding:3px 5px; font-weight:800; letter-spacing:.12em; box-shadow:0 0 10px rgba(255,98,107,.16); }
      .dev-slot { display:inline-flex; align-items:center; justify-content:center; height:100%; }
      .widget-devbadge { background:transparent; color:#ff7b83; font:800 9px/1 "Segoe UI",sans-serif; letter-spacing:.1em; padding:0 1px; text-shadow:0 0 6px rgba(255,98,107,.45); }
      @media (prefers-reduced-motion: reduce) { .ow.widget-enter, .ow.widget-exit { animation-duration:.001ms !important; } }
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

    function setWidgetStateClass(stateClass: "rec" | "proc" | "") {
      const motionClass = widgetMotion ? ` widget-${widgetMotion}` : "";
      widget.className = `ow${stateClass ? ` ${stateClass}` : ""}${motionClass}`;
    }

    function playWidgetEntry() {
      widgetMotion = "enter";
      widget.classList.remove("widget-exit", "widget-enter");
      void widget.offsetWidth;
      widget.classList.add("widget-enter");
    }

    function playWidgetExit() {
      widgetMotion = "exit";
      widget.classList.remove("widget-enter", "widget-exit");
      void widget.offsetWidth;
      widget.classList.add("widget-exit");
    }

    function handleWidgetAnimationEnd(event: AnimationEvent) {
      if (event.target !== widget || event.animationName !== "widget-enter") return;
      if (widgetMotion === "enter") {
        widgetMotion = null;
        widget.classList.remove("widget-enter");
      }
    }
    widget.addEventListener("animationend", handleWidgetAnimationEnd);

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
        setWidgetStateClass("rec");
        widget.setAttribute("aria-label", "Traflix Voice. Registrazione in corso. Doppio clic per aprire la console");
        startSound.currentTime = 0;
        startSound.play().catch(() => {});
      } else if (nextState === "processing") {
        setWidgetStateClass("proc");
        widget.setAttribute("aria-label", "Traflix Voice. Elaborazione della trascrizione. Doppio clic per aprire la console");
        stopSound.currentTime = 0;
        stopSound.play().catch(() => {});
      } else {
        setWidgetStateClass("");
        widget.setAttribute("aria-label", "Traflix Voice pronta. Doppio clic per aprire la console");
      }

      syncOverlayVisibility();
      scheduleAnimation();
    }

    async function requestMainWindow() {
      if (isOpeningMain) return;
      isOpeningMain = true;

      const currentWindow = window.__TAURI__?.window?.getCurrentWindow?.();
      const positionPromise = currentWindow?.outerPosition
        ? Promise.resolve().then(() => currentWindow.outerPosition()).catch(() => null)
        : Promise.resolve(null);
      const exitDelay = new Promise<void>((resolve) => {
        window.setTimeout(resolve, WIDGET_EXIT_MS);
      });

      playWidgetExit();

      try {
        const [position] = await Promise.all([positionPromise, exitDelay]);
        const payload = position && Number.isFinite(position.x) && Number.isFinite(position.y)
          ? { x: Math.round(position.x), y: Math.round(position.y) }
          : {};
        await window.__TAURI__.event.emit("show_main_window", payload);
      } catch (_) {
        widgetMotion = null;
        widget.classList.remove("widget-exit");
      } finally {
        isOpeningMain = false;
      }
    }

    // ── MOUSE CLICK (double-click to show main) ──
    widget.addEventListener("mousedown", (e: MouseEvent) => {
      const now = Date.now();
      if (now - lastClick < 300) {
        lastClick = 0;
        void requestMainWindow();
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
        void requestMainWindow();
      }
    });

    // ── EVENT LISTENERS ──
    let overlayCancelled = false;
    const unlistenFns: (() => void)[] = [];

    window.__TAURI__.event
      .listen("overlay_appearing", () => {
        playWidgetEntry();
      })
      .then((fn) => {
        if (overlayCancelled) fn(); else unlistenFns.push(fn);
      });

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
          const compactVolume = compactVolumeFromPayload(event.payload);
          if (compactVolume !== null) {
            targetVolume = compactVolume;
            scheduleAnimation();
            return;
          }

          const compactStatus = compactStatusFromPayload(event.payload);
          if (compactStatus !== null) {
            if (compactStatus === "listening") {
              applyVisualState("recording");
            } else if (compactStatus === "processing") {
              applyVisualState("processing");
            } else {
              applyVisualState("idle");
            }
            return;
          }

          if (typeof event.payload !== "string") return;

          const data = JSON.parse(event.payload);

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

    function animate(frameTime: number) {
      animationFrame = 0;

      const elapsed = Math.min(
        0.05,
        Math.max(0.001, (frameTime - lastFrameTime) / 1000),
      );
      lastFrameTime = frameTime;
      animationTime += elapsed;

      currentVolume += (targetVolume - currentVolume) * 0.2;
      if (currentVolume < 0.5) currentVolume = 0;

      const volNorm = responsiveVolume(currentVolume);
      // Keep a very small living motion while recording, even between meter
      // packets. The real volume still controls the overall amplitude.
      const animatedVolume = Math.max(
        volNorm,
        isListening ? 0.035 : 0,
      );
      const maxH = 30;
      const minH = 3;

      for (let i = 0; i < 14; i++) {
        const phase = barPhases[i];
        const speed = barSpeeds[i];
        const travellingWave = Math.sin(
          animationTime * 3.2 * speed - i * 0.58 + phase,
        );
        const breathingWave = Math.sin(animationTime * 1.8 + phase * 0.7);
        const innerWave = Math.sin(
          animationTime * 2.45 + phase + (1 - Math.abs(i - 6.5) / 6.5) * 1.2,
        );
        const motion = 0.86 + travellingWave * 0.1 + breathingWave * 0.04;
        const shape = barFactors[i] * (0.96 + innerWave * 0.08);
        const target =
          minH +
          animatedVolume *
            (maxH - minH) *
            shape *
            barJitters[i] *
            motion;

        barHeights[i] += (target - barHeights[i]) * 0.25;

        const h = Math.max(minH, Math.min(maxH, barHeights[i]));
        const drift = Math.sin(animationTime * 2.1 + phase) * animatedVolume * 0.7;
        bars[i].style.transform = `translateY(${drift}px) scaleY(${h / maxH})`;
      }

      if (visualState !== "idle" || currentVolume >= 0.5) {
        scheduleAnimation();
      }
    }

    return () => {
      overlayCancelled = true;
      cancelAnimationFrame(animationFrame);
      widget.removeEventListener("animationend", handleWidgetAnimationEnd);
      unlistenFns.forEach((fn) => fn());
      if (style.parentNode) style.parentNode.removeChild(style);
    };
  }, []);

  return <div ref={rootRef} />;
}

ReactDOM.createRoot(document.getElementById("overlay-root")!).render(
  <Overlay />
);
