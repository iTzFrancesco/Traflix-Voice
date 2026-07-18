export default function LoadingOverlay({ show }: { show: boolean }) {
  if (!show) return null;

  return (
    <div
      className="fixed inset-0 bg-black/80 backdrop-blur-[10px] flex items-center justify-center z-[1000] transition-opacity duration-300"
      role="dialog"
      aria-labelledby="loading-title"
      aria-modal="true"
    >
      <div className="bg-[#1a1b19] p-7 rounded-3xl border border-[rgba(255,255,255,0.1)] w-[80%] max-w-[360px] text-center flex flex-col items-center gap-4 shadow-[0_18px_70px_rgba(0,0,0,.5)]">
        <div
          className="w-12 h-12 rounded-full animate-[spin_0.8s_linear_infinite]"
          style={{
            border: "4px solid #222",
            borderTopColor: "var(--primary-orange)",
            boxShadow: "0 0 20px rgba(255, 140, 0, 0.15)",
          }}
        />
        <h3 id="loading-title" className="text-[#eee] text-base font-bold m-0">
          Caricamento modello...
        </h3>
        <p className="text-[#666] text-[0.95rem] m-0">
          Attendi un momento: il motore sarà pronto automaticamente.
        </p>
      </div>
    </div>
  );
}
