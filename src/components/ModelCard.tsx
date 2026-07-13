import type { WhisperModel } from "../types";

interface ModelCardProps {
  model: WhisperModel;
  isActive: boolean;
  isDownloaded: boolean;
  isLoading: boolean;
  onAction: (modelId: string) => void;
}

function renderDots(filled: number, total: number, color: string) {
  return Array.from({ length: total }, (_, i) => (
    <span
      key={i}
      className={`w-2 h-2 rounded-full transition-[background,box-shadow] duration-200 ${
        i < filled ? "" : "bg-[#2a2a2a]"
      }`}
      style={
        i < filled
          ? {
              background: color,
              boxShadow: `0 0 6px ${color}80`,
              border: "1px solid transparent",
            }
          : { border: "1px solid #333" }
      }
    />
  ));
}

export default function ModelCard({
  model,
  isActive,
  isDownloaded,
  isLoading,
  onAction,
}: ModelCardProps) {
  let buttonLabel = "Seleziona";
  let buttonClass =
    "w-full text-center py-2 px-4 rounded-xl border font-bold text-[0.78rem] transition-all duration-200 cursor-pointer";

  if (isActive) {
    buttonLabel = "Attivo";
    buttonClass += " bg-[rgba(34,197,94,0.1)] text-[#22c55e] border-[rgba(34,197,94,0.3)]";
  } else if (isLoading) {
    buttonLabel = "Download...";
    buttonClass +=
      " bg-[#222] text-[#666] border-[rgba(255,140,0,0.2)] animate-[pulseOpacity_1.5s_infinite] cursor-wait";
  } else if (!isDownloaded) {
    buttonLabel = "Scarica";
    buttonClass +=
      " bg-transparent text-[var(--primary-orange)] border-[var(--primary-orange)]";
  } else {
    buttonClass += " bg-[#1e1e1e] text-[#888] border-[rgba(255,255,255,0.08)]";
  }

  return (
    <div
      className={`
        bg-[rgba(34,34,34,0.6)] p-4 rounded-2xl border transition-all duration-250
        ease-[cubic-bezier(0.4,0,0.2,1)] flex flex-col gap-3
        ${isActive ? "border-[var(--primary-orange)] bg-[rgba(255,140,0,0.06)] shadow-[0_4px_20px_rgba(255,140,0,0.1)]" : "border-[rgba(255,255,255,0.08)]"}
        ${!isDownloaded && !isActive ? "opacity-80 grayscale-[40%]" : ""}
      `}
      data-model-id={model.id}
    >
      <div className="flex-1 min-w-0">
        <div className="flex justify-between items-start mb-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="m-0 text-[0.95rem] font-bold text-[#eee]">{model.name}</h3>
            {model.tag && (
              <span className="text-[0.62rem] font-bold px-[7px] py-[2px] rounded-full whitespace-nowrap bg-[rgba(255,140,0,0.15)] text-[var(--primary-orange)] border border-[rgba(255,140,0,0.3)]">
                {model.tag}
              </span>
            )}
          </div>
          <div className="flex flex-col items-end gap-[2px]">
            <span className="text-[0.72rem] text-[#555] font-semibold whitespace-nowrap">
              {model.size}
            </span>
            <span className="text-[0.65rem] text-[#444] whitespace-nowrap">
              RAM {model.ram}
            </span>
          </div>
        </div>

        <p className="m-0 mb-2.5 text-[0.75rem] text-[#666] leading-[1.45]">
          {model.description}
        </p>

        <div className="flex gap-5">
          <div className="flex items-center gap-1.5">
            <span className="text-[0.65rem] text-[#555] font-bold uppercase tracking-[0.04em] whitespace-nowrap">
              Velocità
            </span>
            <div className="flex gap-1 items-center">
              {renderDots(model.speed, 5, "var(--primary-orange)")}
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[0.65rem] text-[#555] font-bold uppercase tracking-[0.04em] whitespace-nowrap">
              Precisione
            </span>
            <div className="flex gap-1 items-center">
              {renderDots(model.quality, 5, "#4fc3f7")}
            </div>
          </div>
        </div>
      </div>

      <button
        className={buttonClass}
        data-model-id={model.id}
        disabled={isLoading}
        onClick={() => onAction(model.id)}
      >
        {isActive && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="inline-block -mt-0.5 mr-1">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
        {buttonLabel}
      </button>
    </div>
  );
}
