import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

type Mode = "structure_and_design" | "design_only" | "structure_only";

type ReportResponse = {
  reportJson: unknown | null;
  css: string | null;
  excluded: string[];
  notes: string;
};

const MODES: { value: Mode; title: string; hint: string }[] = [
  { value: "structure_and_design", title: "Structure + design", hint: "JSON Editor.js + CSS charte client" },
  { value: "design_only", title: "Design seul", hint: "CSS uniquement, personnalisé à la charte du client" },
  { value: "structure_only", title: "Structure seule", hint: "JSON Editor.js uniquement" },
];

export const Route = createFileRoute("/builder")({
  staticData: { landing: true },
  component: BuilderPage,
});

async function postReport(payload: Record<string, unknown>): Promise<ReportResponse> {
  const res = await fetch("/api/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await res.json()) as ReportResponse & { detail?: unknown };
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "La génération a échoué.");
  }
  return data;
}

const ZeiMark = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 64 64" fill="none" className={className} aria-hidden="true">
    <circle cx="32" cy="32" r="32" className="fill-zei-mint" />
    <path
      d="M40.5 20.5c-8.5 1-14.5 5-16.5 12.5-.6 2.3-.4 4.6.4 6.5.3.8 1.4.9 1.9.2 2.6-3.4 6-5.6 10-6.9 1.3-.4 1.6-2 .5-2.7-3.2-2-5.3-4.4-6.4-8.6-.3-1.2-1.9-1.4-2.2-.3z"
      className="fill-white"
    />
    <path d="M24 44c2-6.5 6.5-11 12.5-13.5" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" />
  </svg>
);

const inputClass =
  "w-full rounded-xl border border-zei-ink/15 bg-white px-3 py-2 text-sm text-zei-ink outline-none placeholder:text-zei-ink/40 focus:border-zei-mint focus:ring-2 focus:ring-zei-mint/30";
const labelClass = "mb-1 block text-xs font-bold uppercase tracking-wide text-zei-ink/60";

function BuilderPage() {
  const [clientName, setClientName] = useState("");
  const [clientUrl, setClientUrl] = useState("");
  const [mode, setMode] = useState<Mode>("structure_and_design");
  const [organizationId, setOrganizationId] = useState("");
  const [networkId, setNetworkId] = useState("");
  const [exerciceId, setExerciceId] = useState("");
  const [yearN, setYearN] = useState("2025");
  const [yearNMinus1, setYearNMinus1] = useState("2024");
  const [pastExercices, setPastExercices] = useState("5");
  const [indicatorsText, setIndicatorsText] = useState("");
  const [formError, setFormError] = useState("");

  const generate = useMutation({
    mutationFn: (payload: Record<string, unknown>) => postReport(payload),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFormError("");

    let indicators: unknown[] = [];
    if (mode !== "design_only") {
      try {
        const parsed = JSON.parse(indicatorsText || "[]");
        if (!Array.isArray(parsed)) throw new Error("Le JSON doit être un tableau.");
        indicators = parsed;
        if (indicators.length === 0) throw new Error("Ajoutez au moins un indicateur.");
      } catch (error) {
        setFormError(`Indicateurs invalides : ${error instanceof Error ? error.message : String(error)}`);
        return;
      }
    }

    generate.mutate({
      mode,
      clientName,
      clientUrl,
      organizationId: Number(organizationId),
      networkId: Number(networkId),
      exerciceIdNMinus1: Number(exerciceId),
      yearN: Number(yearN),
      yearNMinus1: Number(yearNMinus1),
      pastExercices: Number(pastExercices),
      indicators,
    });
  };

  const result = generate.data;

  return (
    <main className="min-h-full bg-white">
      <header className="flex items-center gap-3 bg-zei-navy px-6 py-4">
        <ZeiMark className="h-9 w-9" />
        <div className="leading-tight">
          <p className="text-lg font-extrabold lowercase tracking-tight text-white">reporting builder</p>
          <p className="text-xs text-zei-mint">by Zei Professionnal Services</p>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
        <section className="rounded-2xl border border-zei-ink/10 p-5">
          <h1 className="mb-1 text-xl font-bold text-zei-navy">Générer un rapport client Zei</h1>
          <p className="mb-4 text-sm text-zei-ink/60">
            Structure Editor.js (blocs) et/ou CSS personnalisé à la charte du client, selon le skill zei-rapport-json.
          </p>

          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className={labelClass} htmlFor="clientName">Nom du client</label>
                <input id="clientName" className={inputClass} value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Ex. EDF" required />
              </div>
              <div>
                <label className={labelClass} htmlFor="clientUrl">Site web du client</label>
                <input id="clientUrl" className={inputClass} type="url" value={clientUrl} onChange={(e) => setClientUrl(e.target.value)} placeholder="https://…" required />
              </div>
            </div>

            <fieldset>
              <legend className={labelClass}>Livrable</legend>
              <div className="grid gap-2 sm:grid-cols-3">
                {MODES.map((m) => (
                  <button
                    type="button"
                    key={m.value}
                    onClick={() => setMode(m.value)}
                    className={`rounded-xl border px-3 py-2 text-left text-sm transition ${
                      mode === m.value
                        ? "border-zei-indigo bg-zei-indigo/10 ring-2 ring-zei-indigo/30"
                        : "border-zei-ink/15 bg-white hover:border-zei-mint"
                    }`}
                  >
                    <span className="block font-bold text-zei-navy">{m.title}</span>
                    <span className="block text-xs text-zei-ink/60">{m.hint}</span>
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <label className={labelClass} htmlFor="orgId">organizationId</label>
                <input id="orgId" className={inputClass} type="number" value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} required />
              </div>
              <div>
                <label className={labelClass} htmlFor="netId">networkId (à chaque usage)</label>
                <input id="netId" className={inputClass} type="number" value={networkId} onChange={(e) => setNetworkId(e.target.value)} required />
              </div>
              <div>
                <label className={labelClass} htmlFor="exoId">exerciceId N-1</label>
                <input id="exoId" className={inputClass} type="number" value={exerciceId} onChange={(e) => setExerciceId(e.target.value)} required />
              </div>
              <div>
                <label className={labelClass} htmlFor="yearN">Année N</label>
                <input id="yearN" className={inputClass} type="number" value={yearN} onChange={(e) => setYearN(e.target.value)} required />
              </div>
              <div>
                <label className={labelClass} htmlFor="yearNm1">Année N-1</label>
                <input id="yearNm1" className={inputClass} type="number" value={yearNMinus1} onChange={(e) => setYearNMinus1(e.target.value)} required />
              </div>
              <div>
                <label className={labelClass} htmlFor="past">Exercices passés (charts)</label>
                <input id="past" className={inputClass} type="number" min={1} max={20} value={pastExercices} onChange={(e) => setPastExercices(e.target.value)} required />
              </div>
            </div>

            {mode !== "design_only" && (
              <div>
                <label className={labelClass} htmlFor="indicators">Indicateurs (tableau JSON)</label>
                <textarea
                  id="indicators"
                  rows={6}
                  className={`${inputClass} font-mono`}
                  value={indicatorsText}
                  onChange={(e) => setIndicatorsText(e.target.value)}
                  placeholder='[{"theme":"Environnement","subTheme":"GES","category":"Scope 1","name":"Émissions GES","type":"Nombre","parentId":412225}]'
                  required
                />
                <p className="mt-1 text-xs text-zei-ink/50">
                  Champs : theme, subTheme, category, name, type (Narratif, Nombre, Pourcentage, …), parentId (ID Parent, sinon ID enfant), flag NA/NM à exclure.
                </p>
              </div>
            )}

            {formError && <p className="text-sm font-semibold text-red-600">{formError}</p>}
            {generate.isError && <p className="text-sm font-semibold text-red-600">{generate.error.message}</p>}

            <button
              type="submit"
              disabled={generate.isPending}
              className="self-start rounded-full bg-zei-indigo px-6 py-2.5 text-sm font-bold text-white transition hover:bg-zei-navy disabled:opacity-50"
            >
              {generate.isPending ? "Génération…" : "Générer le livrable"}
            </button>
          </form>
        </section>

        {result && (
          <section className="flex flex-col gap-4">
            {result.excluded.length > 0 && (
              <p className="rounded-xl bg-zei-mint/15 px-4 py-2 text-sm text-zei-ink">
                Indicateurs NA/NM exclus : {result.excluded.join(", ")}
              </p>
            )}
            {result.notes && <p className="text-sm text-zei-ink/60">{result.notes}</p>}
            {result.reportJson != null && (
              <ResultPanel title="Rapport JSON (Editor.js)" content={JSON.stringify(result.reportJson, null, 2)} language="json" />
            )}
            {result.css != null && <ResultPanel title="CSS du rapport" content={result.css} language="css" />}
          </section>
        )}
      </div>
    </main>
  );
}

function ResultPanel({ title, content, language }: { title: string; content: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="overflow-hidden rounded-2xl border border-zei-ink/10">
      <div className="flex items-center justify-between bg-zei-navy px-4 py-2">
        <h2 className="text-sm font-bold text-white">{title}</h2>
        <button onClick={copy} className="rounded-full bg-zei-mint px-3 py-1 text-xs font-bold text-zei-navy hover:opacity-90">
          {copied ? "Copié ✓" : "Copier"}
        </button>
      </div>
      <pre className={`max-h-96 overflow-auto bg-zei-ink/[0.04] p-4 text-xs leading-relaxed text-zei-ink`} data-lang={language}>
        {content}
      </pre>
    </div>
  );
}
