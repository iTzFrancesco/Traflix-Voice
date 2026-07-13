import { useEffect, useRef } from "react";

interface OscilloscopeProps {
  currentVolume: number;
}

export default function Oscilloscope({ currentVolume }: OscilloscopeProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const phaseRef = useRef(0);
  const smoothVolumeRef = useRef(0);
  const animFrameRef = useRef<number>(0);
  const volumeRef = useRef(currentVolume);
  volumeRef.current = currentVolume;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      if (canvas && canvas.parentElement) {
        canvas.width = canvas.parentElement.offsetWidth || 600;
        canvas.height = canvas.parentElement.offsetHeight || 90;
      }
    };

    resize();
    window.addEventListener("resize", resize);

    const draw = () => {
      animFrameRef.current = requestAnimationFrame(draw);

      // Smoothing del volume (0.15 factor) — letto da ref, senza dipendenza
      smoothVolumeRef.current += (volumeRef.current - smoothVolumeRef.current) * 0.15;
      if (smoothVolumeRef.current < 0.5) smoothVolumeRef.current = 0;

      ctx.fillStyle = "#0a0a0a";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const centerY = canvas.height / 2;
      const volNorm = smoothVolumeRef.current / 100;
      const amplitude = volNorm * (canvas.height / 2.5);

      ctx.lineWidth = 2 + volNorm * 2;
      ctx.strokeStyle = "#ff8c00";
      ctx.shadowBlur = 8 + volNorm * 20;
      ctx.shadowColor = "rgba(255, 140, 0, 0.8)";

      ctx.beginPath();

      for (let x = 0; x < canvas.width; x += 2) {
        const mainWave = Math.sin(x * 0.05 + phaseRef.current);
        const secondWave = Math.sin(x * 0.1 + phaseRef.current * 1.5) * 0.5;
        const thirdWave = Math.sin(x * 0.02 + phaseRef.current * 0.7) * 0.3;
        const jitter =
          volNorm * (Math.sin(x * 0.37 + phaseRef.current * 3.1) * 0.4);

        const y =
          centerY + (mainWave + secondWave + thirdWave + jitter) * amplitude;

        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }

      ctx.stroke();
      phaseRef.current += 0.05 + volNorm * 0.25;
    };

    draw();

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animFrameRef.current);
    };
  }, []);

  return (
    <div className="relative h-[90px] bg-[rgba(0,0,0,0.4)] rounded-xl overflow-hidden border border-[rgba(255,140,0,0.1)]">
      <canvas
        ref={canvasRef}
        className="w-full h-full block"
        aria-label="Visualizzatore onde audio"
      />
    </div>
  );
}
