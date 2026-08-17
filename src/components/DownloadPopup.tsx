import { useEffect } from "react";

interface DownloadInfo {
  modelName: string;
  progress: number; // 0-100, 0 = indeterminate
  title?: string;
  message?: string;
  isError?: boolean;
}

interface DownloadPopupProps {
  download: DownloadInfo | null;
  onClose: () => void;
}

export default function DownloadPopup({ download, onClose }: DownloadPopupProps) {
  useEffect(() => {
    if (!download) return;

    // Auto-close after error
    if (download.isError) {
      const timer = setTimeout(() => {
        onClose();
      }, 3000);
      return () => clearTimeout(timer);
    }

    // Auto-close after complete
    if (download.progress >= 100) {
      const timer = setTimeout(() => {
        onClose();
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [download, onClose]);

  if (!download) return null;

  const isComplete = download.progress >= 100;
  const isIndeterminate = download.progress === 0 && !isComplete;
  const title = download.title || `Scaricando ${download.modelName}...`;

  return (
    <div
      className="fixed inset-0 bg-black/80 backdrop-blur-[10px] flex items-center justify-center z-[1000] transition-opacity duration-300"
      role="dialog"
      aria-labelledby="download-title"
      aria-modal="true"
    >
      <div className="modal-surface p-7 rounded-3xl border border-[rgba(255,255,255,0.1)] w-[80%] max-w-[400px] text-center">
        <h3
          id="download-title"
          className="text-[#eee] text-lg font-bold m-0 mb-4"
          style={download.isError ? { color: "#ff4444" } : undefined}
        >
          {download.isError ? "Errore nel Download" : title}
        </h3>

        <div className="bg-[#222] h-3 rounded-[6px] overflow-hidden my-6 relative">
          <div
            className={`h-full transition-[width] duration-300 ease-linear ${
              isIndeterminate
                ? "w-full animate-[indeterminateProgress_1.5s_linear_infinite]"
                : ""
            }`}
            style={{
              width: isIndeterminate ? "100%" : `${download.progress}%`,
              background: isIndeterminate
                ? "linear-gradient(90deg, #222 0%, var(--primary-orange) 25%, var(--primary-orange) 50%, #222 75%, #222 100%)"
                : download.isError
                ? "#ff4444"
                : "var(--primary-orange)",
              backgroundSize: isIndeterminate ? "200% 100%" : undefined,
            }}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={download.progress}
            aria-label="Progresso download"
          />
        </div>

        <p className="text-[#888] text-sm m-0" aria-live="polite">
          {download.isError
            ? download.message || "Si è verificato un errore durante il download."
            : download.progress > 0
            ? `Scaricando modello... ${Math.round(download.progress)}%`
            : "Scaricando modello..."}
        </p>

        {!download.isError && (
          <p className="text-[#666] text-[0.95rem] mt-2 m-0">
            Non chiudere l'applicazione durante il download.
          </p>
        )}
      </div>
    </div>
  );
}
