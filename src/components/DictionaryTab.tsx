import { useState } from "react";
import type { DictionaryEntry } from "../types";

interface Props { entries: DictionaryEntry[]; enabled: boolean; removeFillers: boolean; onChange: (entries: DictionaryEntry[]) => void; onSettingChange: (key: "cloudPostProcessing" | "removeFillers", value: boolean) => void; }

const examples = ["Traflix Voice", "GitHub", "TypeScript", "Vercel"];

export default function DictionaryTab({ entries, enabled, removeFillers, onChange, onSettingChange }: Props) {
  const [term, setTerm] = useState("");
  const add = () => {
    const canonicalTerm = term.trim();
    if (!canonicalTerm) return;
    const alreadyExists = entries.some(
      (entry) => entry.replacement.toLocaleLowerCase() === canonicalTerm.toLocaleLowerCase(),
    );
    if (!alreadyExists) {
      onChange([
        {
          id: crypto.randomUUID(),
          spoken: canonicalTerm,
          replacement: canonicalTerm,
        },
        ...entries,
      ]);
    }
    setTerm("");
  };
  const updateTerm = (id: string, value: string) => onChange(entries.map((entry) => entry.id === id ? { ...entry, spoken: value, replacement: value } : entry));
  return <div className="tab-slide-in max-w-[760px] mx-auto w-full">
    <header className="mb-5"><p className="eyebrow m-0 mb-2">Cloud intelligence</p><h1 className="page-title m-0">Dizionario</h1><p className="m-0 mt-2 text-[.84rem] text-[var(--muted)]">Il tuo lessico personale e una correzione discreta, pensata per non cambiare ciò che dici.</p></header>
    <section className="relative overflow-hidden rounded-2xl border border-[rgba(255,157,36,.22)] bg-[radial-gradient(circle_at_78%_8%,rgba(255,157,36,.25),transparent_32%),linear-gradient(120deg,#2d211e,#172522)] p-6 mb-5">
      <p className="font-serif text-[1.8rem] leading-tight m-0 text-[#fff8ef]">La tua voce, scritta<br/><em>come la diresti tu.</em></p><p className="max-w-[560px] text-[.82rem] leading-5 text-[#e7ded2]">Quando usi il Cloud, Traflix corregge ortografia e punteggiatura e impara termini, brand e nomi importanti. Il testo non viene mai arricchito o riscritto.</p>
      <div className="flex flex-wrap gap-2 mt-4">{examples.map((word) => <button key={word} type="button" onClick={() => setTerm(word)} className="rounded-lg border border-white/10 bg-white/15 px-3 py-1.5 text-[.72rem] text-white hover:bg-white/25">{word}</button>)}</div>
    </section>
    <section className="panel p-5 mb-4"><div className="flex justify-between gap-4"><div><h2 className="m-0 text-[1rem]">Miglioramento testo</h2><p className="m-0 mt-1 text-[.75rem] text-[var(--muted)]">Solo provider Cloud · Llama 3.1 8B Instant</p></div><label className="inline-flex items-center gap-2 text-[.75rem] font-bold"><input type="checkbox" checked={enabled} onChange={(e) => onSettingChange("cloudPostProcessing", e.target.checked)} /> Attivo</label></div><label className="mt-4 flex items-center gap-2 text-[.8rem] text-[var(--ink)]"><input type="checkbox" checked={removeFillers} disabled={!enabled} onChange={(e) => onSettingChange("removeFillers", e.target.checked)} /> Rimuovi esitazioni come “ehm” e “cioè”</label></section>
    <section className="panel p-5 min-w-0"><div className="mb-4"><h2 className="m-0 text-[1rem]">Parole personali</h2><p className="m-0 mt-1 text-[.75rem] text-[var(--muted)]">Scrivi soltanto la grafia corretta. Traflix riconoscerà automaticamente come la pronunci.</p></div>
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-2 mb-3"><input value={term} onChange={(e) => setTerm(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="Aggiungi una parola, un nome o un brand…" className="min-w-0 w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-[.8rem] outline-none focus:border-[var(--accent)]"/><button type="button" onClick={add} disabled={!term.trim()} className="shrink-0 rounded-lg bg-[var(--accent)] px-3 py-2 text-[.75rem] font-bold text-black disabled:opacity-40">Aggiungi</button></div>
      <div className="overflow-hidden rounded-xl border border-white/[.08]">{entries.length ? entries.map((entry) => <div key={entry.id} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b border-white/[.07] p-2 last:border-0"><input value={entry.replacement} onChange={(e) => updateTerm(entry.id, e.target.value)} aria-label={`Grafia corretta di ${entry.replacement}`} className="min-w-0 w-full bg-transparent px-2 py-1.5 text-[.8rem] outline-none"/><button type="button" onClick={() => onChange(entries.filter((item) => item.id !== entry.id))} className="px-2 text-[.8rem] text-[#ff8d91]" aria-label={`Rimuovi ${entry.replacement}`}>×</button></div>) : <p className="m-0 p-5 text-center text-[.8rem] text-[var(--muted)]">Aggiungi il primo termine importante.</p>}</div>
    </section>
  </div>;
}
