import { useMemo, useState } from "react";
import type { TranscriptionEntry } from "../types";

interface CronologiaTabProps { entries: TranscriptionEntry[]; onClear: () => void; onEntryClick: (text: string, index: number) => void; }

export default function CronologiaTab({ entries, onClear, onEntryClick }: CronologiaTabProps) {
  const [query, setQuery] = useState("");
  const [confirming, setConfirming] = useState(false);
  const visible = useMemo(() => entries.filter((entry) => entry.text.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [entries, query]);
  const clear = () => { if (confirming) { onClear(); setConfirming(false); } else setConfirming(true); };
  return <div className="tab-slide-in max-w-[700px] mx-auto w-full">
    <header className="mb-5"><p className="eyebrow m-0 mb-2">Archivio personale</p><div className="flex justify-between gap-3 items-end"><div><h1 className="page-title m-0">Cronologia</h1><p className="m-0 mt-2 text-[.82rem] text-[var(--muted)]">{entries.length} trascrizioni salvate sul dispositivo.</p></div><button id="clear-history-btn" type="button" onClick={clear} className={`shrink-0 rounded-lg border px-3 py-2 text-[.72rem] font-bold cursor-pointer transition-colors ${confirming ? "border-[#ff626b]/60 bg-[#ff626b]/10 text-[#ff8d91]" : "border-white/[.1] bg-white/[.03] text-[var(--muted)] hover:text-[var(--ink)]"}`}>{confirming ? "Conferma cancellazione" : "Cancella tutto"}</button></div>{confirming && <p className="m-0 mt-2 text-[.72rem] text-[#ff9a9d]">Questa azione rimuove definitivamente le trascrizioni locali.</p>}</header>
    <label className="block mb-4"><span className="sr-only">Cerca nella cronologia</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Cerca una parola o una frase…" className="w-full rounded-xl border border-white/[.09] bg-black/20 px-3.5 py-3 text-[.85rem] text-[var(--ink)] outline-none placeholder:text-[var(--quiet)] focus:border-[var(--accent)]" /></label>
    <div id="history-list" className="flex flex-col gap-2.5 overflow-y-auto pr-1" style={{ maxHeight: "calc(100vh - 260px)" }} role="list" aria-label="Lista cronologia trascrizioni">
      {visible.length === 0 ? <div className="panel-subtle p-8 text-center"><p className="m-0 text-[.85rem] text-[var(--muted)]">{entries.length === 0 ? "Le prossime trascrizioni appariranno qui." : "Nessun risultato per questa ricerca."}</p></div> : visible.map((entry) => {
        const originalIndex = entries.indexOf(entry); const preview = entry.text.length > 170 ? `${entry.text.substring(0, 170)}…` : entry.text;
        return <button key={`${entry.timestamp}-${originalIndex}`} type="button" data-index={originalIndex} title="Copia negli appunti" onClick={() => onEntryClick(entry.text, originalIndex)} className="panel text-left p-4 cursor-pointer transition-all hover:border-[rgba(255,157,36,.42)] hover:bg-white/[.04] focus:outline-none" role="listitem">
          <div className="flex justify-between gap-3 items-center mb-2"><span className="text-[.68rem] font-bold tracking-[.04em] text-[var(--accent)]">{entry.timestamp}</span><span className="text-[.64rem] text-[var(--quiet)]">{entry.word_count > 0 ? `${entry.word_count} parole · clicca per copiare` : "Clicca per copiare"}</span></div><p className="m-0 text-[.82rem] leading-6 text-[#d3d0c9] break-words">{preview}</p>
        </button>;
      })}
    </div>
  </div>;
}
