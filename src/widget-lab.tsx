import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import "./index.css";

/* =====================================================================
   Traflix Voice — Widget Lab: Liquid Glass (versione finale scelta)
   ===================================================================== */

type WidgetState = "idle" | "recording" | "processing";

const ORANGE_GRADIENT = "linear-gradient(180deg,#ff8c00 0%,#ffd27a 50%,#ff8c00 100%)";

/* ---------------- simulatore voce ---------------- */

function useVoiceSimulator(active: boolean, manualVolume: number, auto: boolean) {
  const [volume, setVolume] = useState(0);
  const tRef = useRef(0);
  useEffect(() => {
    if (!active) {
      setVolume(0);
      return;
    }
    if (!auto) {
      setVolume(manualVolume);
      return;
    }
    let raf = 0;
    let v = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      tRef.current += dt;
      const t = tRef.current;
      const syllable = Math.max(0, Math.sin(t * 7.3) * 0.5 + Math.sin(t * 13.7) * 0.3 + Math.sin(t * 2.1) * 0.4);
      const burst = Math.pow(Math.max(0, syllable), 1.2);
      const target = 18 + burst * 72 + Math.random() * 8;
      v += (target - v) * 0.25;
      setVolume(Math.max(0, Math.min(100, v)));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [active, auto, manualVolume]);
  return volume;
}

/* ---------------- barre animate (stessa fisica del widget vero) ---------------- */

function AnimatedBars({
  count,
  volume,
  active,
}: {
  count: number;
  volume: number;
  active: boolean;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const volRef = useRef(0);
  volRef.current = volume;
  const maxH = 28;
  const minH = 3;

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const bars = Array.from(wrap.children) as HTMLDivElement[];
    const jitters = bars.map(() => 0.68 + Math.random() * 0.34);
    const phases = bars.map((_, i) => i * 0.64 + Math.random() * 1.15);
    const speeds = bars.map(() => 0.82 + Math.random() * 0.48);
    const center = (count - 1) / 2;
    const factors = bars.map((_, i) => 0.52 + 0.48 * (1 - Math.abs(i - center) / center));
    const heights = new Array(count).fill(minH);
    const vols = new Array(count).fill(0);
    const hist = new Array(8).fill(0);
    let hIdx = 0;
    let cur = 0;
    let time = 0;
    let last = performance.now();
    let raf = 0;
    const LUT = (x: number) => (x <= 0 ? 0 : Math.min(1, Math.pow(x / 100, 0.68) * 1.12));

    const frame = (now: number) => {
      const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000));
      last = now;
      time += dt;
      const tgt = active ? volRef.current : 0;
      cur += (tgt - cur) * 0.22;
      if (cur < 0.5) cur = 0;
      const animated = Math.max(LUT(cur), active ? 0.028 : 0);
      hist[hIdx] = animated;
      hIdx = (hIdx + 1) % hist.length;
      for (let i = 0; i < count; i++) {
        const delayed = hist[(hIdx - 1 - Math.floor(i * 0.58) + hist.length * 2) % hist.length];
        const perBar = delayed * 0.62 + animated * 0.38;
        vols[i] += (perBar - vols[i]) * (0.19 + (i % 4) * 0.045);
        const wave = Math.sin(time * 3.7 * speeds[i] - i * 0.72 + phases[i]);
        const breath = Math.sin(time * 2.15 + phases[i] * 0.85);
        const detail = Math.sin(time * 5.0 * speeds[i] + phases[i] * 1.4 + i * 0.31);
        const motion = 0.76 + wave * 0.24 + breath * 0.09 + detail * 0.07;
        const shape = factors[i] * (0.9 + detail * 0.07);
        const target = minH + Math.pow(vols[i], 0.9) * (maxH - minH) * shape * jitters[i] * motion;
        heights[i] += (target - heights[i]) * 0.32;
        const h = Math.max(minH, Math.min(maxH, heights[i]));
        const drift = Math.sin(time * 2.3 + phases[i]) * vols[i] * 0.55;
        bars[i].style.transform = `translateY(${drift.toFixed(2)}px) scaleY(${(h / maxH).toFixed(3)})`;
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [active, count]);

  return (
    <div ref={wrapRef} style={{ display: "flex", alignItems: "center", gap: 2 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="gi-bar" style={{ height: maxH }} />
      ))}
    </div>
  );
}

/* ================= Liquid Glass ================= */

function GlassIslandWidget({
  state,
  volume,
  enterKey,
  onDoubleClick,
}: {
  state: WidgetState;
  volume: number;
  enterKey: number;
  onDoubleClick: () => void;
}) {
  const lastClick = useRef(0);
  const rec = state === "recording";
  const proc = state === "processing";
  return (
    <div
      key={enterKey}
      role="button"
      tabIndex={0}
      onMouseDown={() => {
        const now = Date.now();
        if (now - lastClick.current < 300) {
          lastClick.current = 0;
          onDoubleClick();
          return;
        }
        lastClick.current = now;
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onDoubleClick();
        }
      }}
      className={`gi widget-enter ${rec ? "is-rec" : ""} ${proc ? "is-proc" : ""}`}
      aria-label={rec ? "Registrazione in corso" : proc ? "Elaborazione trascrizione" : "Traflix Voice pronta"}
      title="Doppio clic per aprire la console"
    >
      <span className="gi-glow" aria-hidden />
      <span className="gi-logo">
        <img src="/assets/logo.png" alt="" draggable={false} />
      </span>
      <span className="gi-label">Traflix Voice</span>
      <span className={`gi-spinner-wrap ${proc ? "show" : ""}`}>
        <span className="gi-spinner" />
        <span className="gi-proc-label">Trascrivo…</span>
      </span>
      <span className={`gi-sep ${rec ? "show" : ""}`} />
      <span className={`gi-viz ${rec ? "show" : ""}`}>
        <AnimatedBars count={16} volume={volume} active={rec} />
      </span>
      <span className="gi-hint">Doppio clic per aprire</span>
    </div>
  );
}

/* ---------------- timeline video 8s ---------------- */

type TlStep = { t: number; label: string; state: WidgetState; vol: number };

const SCRIPT: TlStep[] = [
  { t: 0.0, label: "Fermo", state: "idle", vol: 0 },
  { t: 1.0, label: "Hotkey → registra", state: "recording", vol: 8 },
  { t: 2.2, label: "Parli", state: "recording", vol: 62 },
  { t: 3.6, label: "Pausa", state: "recording", vol: 6 },
  { t: 4.6, label: "Parli forte", state: "recording", vol: 78 },
  { t: 5.8, label: "Elaboro…", state: "processing", vol: 0 },
  { t: 7.4, label: "Fatto ✓", state: "idle", vol: 0 },
];

function TimelinePlayer({
  onScrub,
}: {
  onScrub: (s: WidgetState, v: number, idx: number) => void;
}) {
  const DUR = 8;
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rafRef = useRef(0);
  const lastRef = useRef(0);

  const idx = useMemo(() => {
    let k = 0;
    SCRIPT.forEach((s, i) => {
      if (time >= s.t) k = i;
    });
    return k;
  }, [time]);

  useEffect(() => {
    const a = SCRIPT[idx];
    const b = SCRIPT[Math.min(idx + 1, SCRIPT.length - 1)];
    const f = a === b ? 0 : Math.min(1, Math.max(0, (time - a.t) / (b.t - a.t)));
    onScrub(a.state, a.vol + (b.vol - a.vol) * f, idx);
  }, [time, idx, onScrub]);

  useEffect(() => {
    if (!playing) return;
    lastRef.current = performance.now();
    const loop = (now: number) => {
      setTime((t) => {
        const n = t + (now - lastRef.current) / 1000;
        lastRef.current = now;
        if (n >= DUR) {
          setPlaying(false);
          return DUR;
        }
        return n;
      });
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [playing]);

  return (
    <div className="tl">
      <div className="tl-controls">
        <button className="btn primary" onClick={() => (time >= DUR ? (setTime(0), setPlaying(true)) : setPlaying((p) => !p))}>
          {playing ? "⏸ Pausa" : time >= DUR ? "↺ Replay" : "▶ Play"}
        </button>
        <span className="tl-time">{time.toFixed(1)}s / 8s</span>
      </div>
      <input
        className="tl-scrub"
        type="range"
        min={0}
        max={DUR}
        step={0.05}
        value={time}
        onChange={(e) => {
          setPlaying(false);
          setTime(Number(e.target.value));
        }}
        aria-label="Scrub timeline"
      />
      <ol className="tl-steps">
        {SCRIPT.map((s, i) => (
          <li key={s.t} className={i === idx ? "on" : ""}>
            <button onClick={() => { setPlaying(false); setTime(s.t + 0.01); }}>
              <b>{s.label}</b>
              <span>{s.t.toFixed(1)}s</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ---------------- drag vero per testare ---------------- */

function Draggable({ children, showCoords }: { children: ReactNode; showCoords?: boolean }) {
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const drag = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);

  return (
    <div className="dcol">
      <div
        className="dragwrap"
        style={{ transform: `translate(${pos.x}px, ${pos.y}px)` }}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          drag.current = { sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y };
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          const dx = e.clientX - d.sx;
          const dy = e.clientY - d.sy;
          if (Math.hypot(dx, dy) < 5) return;
          setPos({ x: Math.round(d.ox + dx), y: Math.round(d.oy + dy) });
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        {children}
      </div>
      {showCoords && (
        <div className="dragbar">
          <button className="btn mini" onClick={() => setPos({ x: 0, y: 0 })}>↺ centra</button>
          <code>
            x {pos.x} · y {pos.y}
          </code>
        </div>
      )}
    </div>
  );
}

/* ================= APP ================= */

function WidgetLab() {
  const [state, setState] = useState<WidgetState>("idle");
  const [manualVolume, setManualVolume] = useState(55);
  const [autoVoice, setAutoVoice] = useState(true);
  const [sounds, setSounds] = useState(true);
  const [enterKey, setEnterKey] = useState(0);
  const [lastEvent, setLastEvent] = useState("Premi “Registra” per iniziare.");
  const [tlState, setTlState] = useState<WidgetState>("idle");
  const [tlVol, setTlVol] = useState(0);
  const [tlIdx, setTlIdx] = useState(0);

  const volume = useVoiceSimulator(state === "recording", manualVolume, autoVoice);

  const playSound = useCallback(
    (which: "start" | "stop") => {
      if (!sounds) return;
      try {
        void new Audio(`/assets/sounds/${which}.wav`).play().catch(() => {});
      } catch { /* noop */ }
    },
    [sounds],
  );

  const goRecording = useCallback(() => {
    setState("recording");
    setEnterKey((k) => k + 1);
    playSound("start");
    setLastEvent("● Registrazione — parla, le barre si muovono.");
  }, [playSound]);

  const goProcessing = useCallback(() => {
    setState("processing");
    playSound("stop");
    setLastEvent("◌ Elaborazione della trascrizione…");
  }, [playSound]);

  const goIdle = useCallback(() => {
    setState("idle");
    setLastEvent("✓ Testo incollato — widget fermo.");
  }, []);

  const openMain = useCallback(() => {
    setLastEvent("⤢ Doppio clic — si aprirebbe la console.");
  }, []);

  const onScrub = useCallback((s: WidgetState, v: number, i: number) => {
    setTlState(s);
    setTlVol(v);
    setTlIdx(i);
  }, []);

  return (
    <div className="lab">
      <style>{LAB_CSS}</style>

      <header className="lab-hero">
        <div>
          <div className="eyebrow">Traflix Voice · Widget Lab</div>
          <h1>
            Il nuovo widget <em>Liquid Glass</em>
          </h1>
          <p>Premi <b>Registra</b>, <b>trascina</b> il widget dove vuoi e fai <b>doppio clic</b> sopra.</p>
        </div>
        <div className="hero-card">
          <div className="ctrl-row">
            <button className={`btn ${state === "idle" ? "on" : ""}`} onClick={goIdle}>Fermo</button>
            <button className={`btn rec ${state === "recording" ? "on" : ""}`} onClick={goRecording}>● Registra</button>
            <button className={`btn proc ${state === "processing" ? "on" : ""}`} onClick={goProcessing}>◌ Elaboro</button>
          </div>
          <div className="ctrl-row">
            <label className="switch">
              <input type="checkbox" checked={autoVoice} onChange={(e) => setAutoVoice(e.target.checked)} />
              <span>voce finta {autoVoice ? "ON" : "OFF"}</span>
            </label>
            <label className="switch">
              <input type="checkbox" checked={sounds} onChange={(e) => setSounds(e.target.checked)} />
              <span>suoni</span>
            </label>
          </div>
          {!autoVoice && state === "recording" && (
            <label className="vol-row">
              volume {manualVolume}
              <input type="range" min={0} max={100} value={manualVolume} onChange={(e) => setManualVolume(Number(e.target.value))} />
            </label>
          )}
          <p className="last-event">{lastEvent}</p>
        </div>
      </header>

      <section className="stage">
        <div className="desktop-mock">
          <div className="dm-canvas">
            <div className="dm-orb orb-a" />
            <div className="dm-orb orb-b" />
            <div className="dm-widget">
              <Draggable showCoords>
                <GlassIslandWidget state={state} volume={volume} enterKey={enterKey} onDoubleClick={openMain} />
              </Draggable>
            </div>
          </div>
        </div>
      </section>

      <section className="panel-block">
        <div className="eyebrow">Video: il ciclo completo in 8 secondi</div>
        <h2>Premi play — oppure trascina la barra</h2>
        <div className="tl-grid">
          <div className="tl-demo">
            <Draggable>
              <GlassIslandWidget state={tlState} volume={tlVol} enterKey={tlIdx} onDoubleClick={openMain} />
            </Draggable>
            <div className="tl-now">{SCRIPT[tlIdx].label}</div>
          </div>
          <TimelinePlayer onScrub={onScrub} />
        </div>
      </section>

      <footer className="lab-foot">Widget Lab · Liquid Glass · http://localhost:1420/widget-lab.html</footer>
    </div>
  );
}

const LAB_CSS = `
html, body { overflow-y:auto !important; overflow-x:hidden; height:auto !important; min-height:100%; }
body { display:block !important; }
#widget-lab-root { min-height:100vh; }
.lab { min-height:100vh; background: radial-gradient(900px 500px at 85% -5%, rgba(255,125,25,.14), transparent 60%), #0e0f0e; color:#f5f3ef; font-family:"Satoshi","Segoe UI",sans-serif; padding:28px clamp(16px,4vw,56px) 60px; }
.lab-hero { display:grid; grid-template-columns: 1fr 1fr; gap:26px; align-items:start; max-width:1100px; margin:0 auto 26px; }
@media (max-width:900px){ .lab-hero{grid-template-columns:1fr;} }
.lab-hero h1 { font-size:clamp(1.8rem,4vw,2.6rem); letter-spacing:-.03em; margin:.35rem 0 .5rem; font-weight:800; }
.lab-hero h1 em { font-style:normal; background:linear-gradient(180deg,#ff8c00,#ffd27a); -webkit-background-clip:text; background-clip:text; color:transparent; }
.lab-hero p { color:#b9b6b0; }
.hero-card { background:#161715; border:1px solid rgba(255,255,255,.1); border-radius:18px; padding:18px; }
.ctrl-row { display:flex; gap:8px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
.btn { background:rgba(255,255,255,.07); color:#f5f3ef; border:1px solid rgba(255,255,255,.12); border-radius:10px; padding:10px 16px; font-weight:700; cursor:pointer; font-size:.95rem; }
.btn:hover { border-color:rgba(255,157,36,.5); }
.btn.on { border-color:#ff9d24; box-shadow:0 0 0 3px rgba(255,157,36,.25); }
.btn.primary { background:linear-gradient(180deg,#ff8c00,#e06f00); border-color:#ffb45e; color:#1a1206; }
.btn.rec.on { border-color:#ff626b; box-shadow:0 0 0 3px rgba(255,98,107,.25); }
.switch { display:inline-flex; gap:7px; align-items:center; color:#cfccc6; font-size:.85rem; cursor:pointer; }
.switch input { accent-color:#ff8c00; width:16px; height:16px; }
.vol-row { display:flex; gap:10px; align-items:center; color:#b9b6b0; font-size:.85rem; margin-bottom:10px; }
.vol-row input { flex:1; accent-color:#ff8c00; }
.last-event { margin:4px 0 0; color:#ffd9a3; font-size:.88rem; min-height:1.4em; }
.stage { max-width:1100px; margin:0 auto; background:#141514; border:1px solid rgba(255,157,36,.55); box-shadow:0 0 0 1px rgba(255,157,36,.25), 0 18px 50px rgba(255,140,0,.12); border-radius:20px; overflow:hidden; }
.desktop-mock { margin:16px; border-radius:14px; overflow:hidden; border:1px solid rgba(255,255,255,.08); }
.dm-canvas { position:relative; min-height:170px; display:flex; align-items:center; justify-content:center; padding:34px 30px; background: linear-gradient(120deg,#1c2b26,#2b1e14 70%,#191423); overflow:hidden; }
.dm-orb { position:absolute; border-radius:50%; filter:blur(46px); opacity:.75; animation:drift 9s ease-in-out infinite alternate; }
.orb-a { width:260px; height:260px; background:radial-gradient(circle,#ff8c00,transparent 70%); top:-70px; right:8%; }
.orb-b { width:220px; height:220px; background:radial-gradient(circle,#3b82f6,transparent 70%); bottom:-80px; left:30%; animation-delay:-3s; }
@keyframes drift { to { transform:translate(26px,18px) scale(1.08); } }
.dm-widget { position:relative; z-index:2; }
.panel-block { max-width:1100px; margin:22px auto 0; background:#141514; border:1px solid rgba(255,255,255,.09); border-radius:20px; padding:22px; }
.panel-block h2 { margin:.3rem 0 1rem; letter-spacing:-.02em; }
.tl-grid { display:grid; grid-template-columns: 1fr 1fr; gap:20px; }
@media (max-width:900px){ .tl-grid{grid-template-columns:1fr;} }
.tl-demo { background:linear-gradient(120deg,#1c2b26,#2b1e14); border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:30px 22px; min-height:130px; display:flex; flex-direction:column; align-items:center; }
.tl-now { margin-top:14px; color:#ffd9a3; font-weight:800; font-size:1.1rem; }
.tl-controls { display:flex; gap:10px; align-items:center; margin-bottom:10px; }
.tl-time { margin-left:auto; color:#8f8c87; font-variant-numeric:tabular-nums; }
.tl-scrub { width:100%; accent-color:#ff8c00; height:28px; }
.tl-steps { list-style:none; margin:14px 0 0; padding:0; display:grid; gap:8px; }
.tl-steps li { border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:9px 12px; }
.tl-steps li.on { border-color:#ff9d24; background:rgba(255,157,36,.09); }
.tl-steps button { all:unset; cursor:pointer; display:flex; gap:10px; align-items:baseline; width:100%; }
.tl-steps b { color:#ffd9a3; }
.tl-steps button span { margin-left:auto; color:#8f8c87; font-size:.78rem; }
.lab-foot { max-width:1100px; margin:26px auto 0; color:#74716c; font-size:.78rem; text-align:center; }
.eyebrow { color:#ff9d24; font-size:.7rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }

/* ===== drag & drop test ===== */
.dcol { display:flex; flex-direction:column; align-items:center; gap:12px; }
.dragwrap { touch-action:none; cursor:grab; user-select:none; -webkit-user-select:none; }
.dragwrap:active { cursor:grabbing; }
.dragbar { display:flex; gap:10px; align-items:center; color:#8f8c87; font-size:.8rem; }
.dragbar code { background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.1); padding:3px 10px; border-radius:8px; font-variant-numeric:tabular-nums; }
.btn.mini { padding:6px 12px; font-size:.78rem; border-radius:8px; }

/* ===== liquid glass widget ===== */
.gi { position:relative; height:42px; display:inline-flex; align-items:center; gap:8px; padding:0 14px 0 8px; border-radius:99px; cursor:grab;
  background:linear-gradient(145deg,rgba(40,38,32,.72),rgba(16,17,15,.78)); backdrop-filter:blur(18px) saturate(1.3); -webkit-backdrop-filter:blur(18px) saturate(1.3);
  border:1px solid rgba(255,255,255,.14); box-shadow:inset 0 1px 0 rgba(255,255,255,.14), 0 10px 30px rgba(0,0,0,.45); transition:border-color .25s, transform .25s; }
.gi:hover { transform:translateY(-1px); border-color:rgba(255,157,36,.55); }
.gi:active { transform:scale(.98); }
.gi.is-rec { border-color:rgba(255,98,107,.6); box-shadow:0 0 0 3px rgba(255,98,107,.14), 0 10px 34px rgba(255,98,107,.25); }
.gi-glow { position:absolute; inset:-1px; border-radius:99px; padding:1px; background:conic-gradient(from var(--ga,0deg), transparent 0 70%, rgba(255,140,0,.7) 82%, rgba(255,210,122,.9) 88%, transparent 96%); -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0); -webkit-mask-composite:xor; mask-composite:exclude; opacity:0; transition:opacity .3s; pointer-events:none; animation:grot 2.4s linear infinite; }
.gi.is-rec .gi-glow, .gi.is-proc .gi-glow { opacity:1; }
@property --ga { syntax:'<angle>'; initial-value:0deg; inherits:false; }
@keyframes grot { to { --ga:360deg; } }
.gi-logo { position:relative; width:28px; height:28px; }
.gi-logo img { width:28px; height:28px; border-radius:50%; display:block; }
.gi-label { font-size:.84rem; font-weight:800; line-height:1; background:${ORANGE_GRADIENT}; -webkit-background-clip:text; background-clip:text; color:transparent; max-width:110px; overflow:hidden; white-space:nowrap; transition:max-width .35s cubic-bezier(.22,1,.36,1),opacity .25s; }
.gi.is-rec .gi-label, .gi.is-proc .gi-label { max-width:0; opacity:0; margin:0; }
.gi-spinner-wrap { display:flex; gap:7px; align-items:center; max-width:0; opacity:0; overflow:hidden; white-space:nowrap; transition:max-width .35s,opacity .25s; }
.gi-spinner-wrap.show { max-width:150px; opacity:1; }
.gi-spinner { width:16px; height:16px; border-radius:50%; border:2px solid rgba(255,210,122,.25); border-top-color:#ffd27a; animation:spin .8s linear infinite; }
.gi-proc-label { font-size:.78rem; color:#ffd9a3; font-weight:700; }
.gi-sep { width:0; height:18px; border-radius:99px; background:linear-gradient(180deg,transparent,rgba(255,98,107,.9),transparent); opacity:0; transition:width .3s,opacity .25s; }
.gi-sep.show { width:2px; opacity:1; }
.gi-viz { display:flex; align-items:center; max-width:0; opacity:0; overflow:hidden; transition:max-width .35s cubic-bezier(.22,1,.36,1),opacity .25s; }
.gi-viz.show { max-width:130px; opacity:1; }
.gi-bar { width:3px; border-radius:99px; background:${ORANGE_GRADIENT}; transform:scaleY(.1); transform-origin:center; box-shadow:0 0 8px rgba(255,170,60,.6); }
.gi-hint { position:absolute; top:calc(100% + 7px); left:0; color:rgba(245,243,239,.72); font:600 10px/1 "Segoe UI",sans-serif; white-space:nowrap; opacity:0; pointer-events:none; transition:opacity .18s; text-shadow:0 1px 5px #000; }
.gi:hover .gi-hint { opacity:1; }

@keyframes spin { to { transform:rotate(360deg); } }
.widget-enter { animation:widget-enter .42s cubic-bezier(.22,1,.36,1) both; }
@keyframes widget-enter { 0%{opacity:0; transform:translate3d(0,8px,0) scale(.92);} 58%{opacity:1; transform:translate3d(0,-1px,0) scale(1.018);} 100%{opacity:1; transform:none;} }
`;

ReactDOM.createRoot(document.getElementById("widget-lab-root")!).render(<WidgetLab />);
