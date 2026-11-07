import { useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

type Mode = "structure_and_design" | "design_only" | "structure_only";

type Report = {
  reportJson: unknown | null;
  css: string | null;
  excluded: string[];
  notes: string;
};

type ChatTurn = { role: "user" | "assistant"; content: string };

const MODES: { value: Mode; title: string; icon: ReactNode }[] = [
  {
    value: "structure_and_design",
    title: "Construire et designer le rapport (JSON & CSS)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-8 w-8">
        <rect x="3" y="3" width="8" height="8" rx="2" />
        <rect x="13" y="3" width="8" height="5" rx="2" />
        <rect x="13" y="10" width="8" height="11" rx="2" />
        <path d="M3 15h8M3 19h5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    value: "structure_only",
    title: "Construire le rapport (JSON)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-8 w-8">
        <path d="M8 4c-2 0-3 1-3 3v2c0 1-1 2-2 2 1 0 2 1 2 2v2c0 2 1 3 3 3" strokeLinecap="round" />
        <path d="M16 4c2 0 3 1 3 3v2c0 1 1 2 2 2-1 0-2 1-2 2v2c0 2-1 3-3 3" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    value: "design_only",
    title: "Designer le rapport (CSS)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-8 w-8">
        <path d="M12 3a9 9 0 1 0 0 18c1.5 0 2-.8 2-2 0-1.5 1-2 2.5-2H19a2 2 0 0 0 2-2c0-5-4.5-12-9-12z" strokeLinejoin="round" />
        <circle cx="7.5" cy="11.5" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="10.5" cy="7.5" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="15" cy="7.5" r="1.2" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
];

const cssWanted = (mode: Mode) => mode !== "structure_only";
const jsonWanted = (mode: Mode) => mode !== "design_only";

// Jeu d'indicateurs de démonstration envoyé au builder quand l'utilisateur n'en fournit pas.
const DEMO_INDICATORS = [
  { theme: "Environnement", subTheme: "ESRS E1 — Énergie et émissions", category: "Énergie", name: "Consommation totale d'énergie", type: "Nombre", parentId: 412225 },
  { theme: "Environnement", subTheme: "ESRS E1 — Énergie et émissions", category: "Émissions", name: "Émissions GES scopes 1 & 2", type: "Nombre", parentId: 412226 },
  { theme: "Environnement", subTheme: "ESRS E5 — Économie circulaire", category: "Déchets", name: "Déchets non dangereux", type: "Nombre", parentId: 412230 },
  { theme: "Social", subTheme: "ESRS S1 — Personnel", category: "Diversité", name: "Part de femmes cadres", type: "Pourcentage", parentId: 412240 },
  { theme: "Social", subTheme: "ESRS S1 — Personnel", category: "Santé-sécurité", name: "Accidents du travail", type: "Nombre", parentId: 412241 },
  { theme: "Gouvernance", subTheme: "ESRS G1 — Conduite des affaires", category: "Éthique", name: "Politique anticorruption", type: "Narratif", parentId: 412250, flag: undefined },
];

export const Route = createFileRoute("/builder")({
  staticData: { landing: true },
  component: BuilderPage,
});

async function postJson(url: string, payload: Record<string, unknown>): Promise<Report> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await res.json()) as Report & { detail?: unknown };
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "La génération a échoué.");
  }
  return data;
}

const inputClass =
  "w-full rounded-xl border border-white/25 bg-white/10 px-3 py-2 text-sm text-white outline-none placeholder:text-white/50 focus:border-zei-mint focus:ring-2 focus:ring-zei-mint/40";
const labelClass = "mb-1 block text-xs font-semibold uppercase tracking-wide text-white/70";

function BuilderPage() {
  const [mode, setMode] = useState<Mode | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const workspaceRef = useRef<HTMLElement>(null);

  const pickMode = (value: Mode) => {
    setMode(value);
    setReport(null);
    setTurns([]);
    setTimeout(() => workspaceRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  const generate = useMutation({
    mutationFn: (payload: Record<string, unknown>) => postJson("/api/report", payload),
    onSuccess: (data) => setReport(data),
  });

  const refine = useMutation({
    mutationFn: (payload: Record<string, unknown>) => postJson("/api/report/refine", payload),
    onSuccess: (data, payload) => {
      setReport(data);
      setTurns((prev) => [...prev, { role: "assistant", content: data.notes || "Livrable mis à jour." }]);
      void payload;
    },
    onError: (error) => {
      setTurns((prev) => [...prev, { role: "assistant", content: `Erreur : ${error.message}` }]);
    },
  });

  return (
    <main className="zei-animated-bg min-h-full">
      <section className="mx-auto flex min-h-screen w-full max-w-3xl flex-col items-center justify-center gap-4 px-6 py-16">
        {(() => {
          const [main, ...rest] = MODES;
          const btnClass = (active: boolean, extra: string) =>
            `flex items-center justify-center gap-4 border text-center text-white transition hover:scale-[1.01] ${
              active
                ? "border-zei-mint bg-white/20 ring-2 ring-zei-mint"
                : "border-white/25 bg-white/10 hover:bg-white/20"
            } ${extra}`;
          return (
            <>
              <button
                key={main.value}
                type="button"
                onClick={() => pickMode(main.value)}
                className={btnClass(mode === main.value, "w-full rounded-2xl px-6 py-8")}
              >
                <span className="shrink-0 text-zei-mint">{main.icon}</span>
                <span className="text-xl font-extrabold uppercase tracking-wide">{main.title}</span>
              </button>
              <div className="grid w-full grid-cols-2 gap-4">
                {rest.map((m) => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => pickMode(m.value)}
                    className={btnClass(mode === m.value, "rounded-lg px-4 py-6")}
                  >
                    <span className="shrink-0 text-zei-mint">{m.icon}</span>
                    <span className="text-sm font-bold uppercase">{m.title}</span>
                  </button>
                ))}
              </div>
            </>
          );
        })()}
      </section>

      {mode && (
        <Workspace
          mode={mode}
          report={report}
          turns={turns}
          generating={generate.isPending}
          refining={refine.isPending}
          genError={generate.isError ? generate.error.message : ""}
          workspaceRef={workspaceRef}
          onGenerate={(payload) => generate.mutate(payload)}
          onRefine={(instruction) => {
            setTurns((prev) => [...prev, { role: "user", content: instruction }]);
            refine.mutate({
              mode,
              instruction,
              reportJson: report?.reportJson ?? null,
              css: report?.css ?? null,
            });
          }}
        />
      )}
    </main>
  );
}

function Workspace({
  mode,
  report,
  turns,
  generating,
  refining,
  genError,
  workspaceRef,
  onGenerate,
  onRefine,
}: {
  mode: Mode;
  report: Report | null;
  turns: ChatTurn[];
  generating: boolean;
  refining: boolean;
  genError: string;
  workspaceRef: React.Ref<HTMLElement>;
  onGenerate: (payload: Record<string, unknown>) => void;
  onRefine: (instruction: string) => void;
}) {
  const [clientName, setClientName] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [networkId, setNetworkId] = useState("");
  const [clientUrl, setClientUrl] = useState("");
  const [pastExercices, setPastExercices] = useState("5");
  const [instruction, setInstruction] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    onGenerate({
      mode,
      clientName,
      clientUrl: cssWanted(mode) ? clientUrl : null,
      organizationId: Number(organizationId),
      networkId: Number(networkId),
      pastExercices: Number(pastExercices),
      indicators: jsonWanted(mode) ? DEMO_INDICATORS : [],
    });
  };

  const sendInstruction = (event: FormEvent) => {
    event.preventDefault();
    const text = instruction.trim();
    if (!text || refining) return;
    setInstruction("");
    onRefine(text);
  };

  const modeTitle = MODES.find((m) => m.value === mode)?.title ?? mode;

  return (
    <section ref={workspaceRef} className="zei-chat-bg border-t border-white/15">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
        <h2 className="text-center text-xl font-bold text-white">{modeTitle}</h2>

        <form onSubmit={submit} className="flex flex-col gap-3 rounded-2xl bg-white/10 p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className={labelClass} htmlFor="clientName">Nom du client</label>
              <input id="clientName" className={inputClass} value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Ex. EDF" required />
            </div>
            <div>
              <label className={labelClass} htmlFor="orgId">ID organisation</label>
              <input id="orgId" className={inputClass} type="number" value={organizationId} onChange={(e) => setOrganizationId(e.target.value)} required />
            </div>
            <div>
              <label className={labelClass} htmlFor="netId">ID réseau</label>
              <input id="netId" className={inputClass} type="number" value={networkId} onChange={(e) => setNetworkId(e.target.value)} required />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {cssWanted(mode) && (
              <div>
                <label className={labelClass} htmlFor="clientUrl">URL du client (pour la charte)</label>
                <input id="clientUrl" className={inputClass} type="url" value={clientUrl} onChange={(e) => setClientUrl(e.target.value)} placeholder="https://…" required />
              </div>
            )}
            {jsonWanted(mode) && (
              <div>
                <label className={labelClass} htmlFor="past">Nombre d'exercices passés (charts)</label>
                <input id="past" className={inputClass} type="number" min={1} max={20} value={pastExercices} onChange={(e) => setPastExercices(e.target.value)} required />
              </div>
            )}
          </div>
          {genError && <p className="text-sm font-semibold text-red-300">{genError}</p>}
          <button
            type="submit"
            disabled={generating}
            className="self-start rounded-full bg-zei-mint px-6 py-2.5 text-sm font-bold text-zei-navy transition hover:brightness-110 disabled:opacity-50"
          >
            {generating ? "Génération…" : "Générer"}
          </button>
        </form>

        {report && (
          <>
            <div className="overflow-hidden rounded-2xl border border-white/20 bg-white">
              <iframe
                title="Aperçu du rapport"
                className="h-[480px] w-full"
                srcDoc={buildPreviewSrcDoc(report, mode)}
              />
            </div>

            <div className="flex flex-col gap-3">
              <h3 className="text-sm font-bold uppercase tracking-wide text-white/80">
                Améliorer le rapport en langage naturel
              </h3>
              {turns.map((turn, index) => (
                <div
                  key={index}
                  className={
                    turn.role === "user"
                      ? "self-end rounded-2xl rounded-br-sm bg-white/20 px-4 py-2.5 text-sm text-white"
                      : "self-start rounded-2xl rounded-bl-sm bg-white/10 px-4 py-2.5 text-sm text-white"
                  }
                >
                  <span className="whitespace-pre-wrap">{turn.content}</span>
                </div>
              ))}
              {refining && (
                <div className="self-start rounded-2xl rounded-bl-sm bg-white/10 px-4 py-2.5 text-sm text-white/80">
                  <span className="animate-pulse">zei applique la modification…</span>
                </div>
              )}
              <form onSubmit={sendInstruction} className="flex gap-2">
                <input
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  placeholder="Ex. : rends les titres plus gros, ajoute un chart sur l'eau…"
                  className="flex-1 rounded-full border border-white/25 bg-white/10 px-4 py-2.5 text-sm text-white outline-none placeholder:text-white/50 focus:border-zei-mint focus:ring-2 focus:ring-zei-mint/40"
                />
                <button
                  type="submit"
                  disabled={refining || instruction.trim() === ""}
                  className="rounded-full bg-zei-mint px-5 py-2.5 text-sm font-bold text-zei-navy transition hover:brightness-110 disabled:opacity-50"
                >
                  Envoyer
                </button>
              </form>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

/* ---------- Aperçu du rapport (données fictives) ---------- */

const DEFAULT_CSS = `:root{--primary:#262882;--secondary:#3c3c3b;--tertiary:#58b896;--fourth:rgba(88,184,150,0.18);}
body{font-family:'Poppins',Arial,sans-serif;font-size:14px;color:var(--secondary);padding:24px;}
h1{color:var(--primary);font-size:32px;font-weight:700;} h2{color:var(--primary);font-size:24px;font-weight:600;margin-top:24px;margin-bottom:12px;padding-bottom:6px;border-bottom:3px solid var(--tertiary);} h3{color:var(--secondary);font-size:20px;font-weight:600;margin-top:14px;}
a{color:var(--primary);} table{background-color:var(--fourth);font-size:small;width:100%;table-layout:fixed;} thead{background-color:var(--primary);} thead tr th, thead tr th *{color:#fff;font-weight:600;}`;

function hashOf(text: string): number {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h;
}

const esc = (s: unknown) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));

function fakeValue(id: string): number {
  return 40 + (hashOf(String(id)) % 960);
}

function renderChart(data: any, pastExercices: number, yearN: number): string {
  const indicators: any[] = data?.chart?.indicators ?? [];
  const width = 640;
  const height = 240;
  const pad = 32;
  const years: number[] = [];
  for (let i = pastExercices; i >= 0; i--) years.push(yearN - i);
  const series = indicators.map((ind) => {
    const base = fakeValue(String(ind.indicatorId));
    return years.map((y, i) => ({ x: pad + (i * (width - 2 * pad)) / Math.max(years.length - 1, 1), y: height - pad - ((base + i * 37) % 180), year: y, v: base + i * 13 }));
  });
  const polylines = series
    .map((pts, idx) => {
      const color = ["#262882", "#4347e8", "#58b896"][idx % 3];
      return `<polyline fill="none" stroke="${color}" stroke-width="2.5" points="${pts.map((p) => `${p.x},${p.y}`).join(" ")}" />`;
    })
    .join("");
  const xLabels = years
    .map((y, i) => `<text x="${pad + (i * (width - 2 * pad)) / Math.max(years.length - 1, 1)}" y="${height - 8}" font-size="11" text-anchor="middle" fill="#3c3c3b">${y}</text>`)
    .join("");
  const legend = indicators
    .map((ind, idx) => `<span style="margin-right:12px;color:${["#262882", "#4347e8", "#58b896"][idx % 3]}">● indicateur ${esc(ind.indicatorId)}</span>`)
    .join("");
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;background:rgba(88,184,150,0.08);border-radius:12px">${polylines}${xLabels}<text x="${pad}" y="16" font-size="11" fill="#3c3c3b">${legend}</text></svg>`;
}

function renderTable(data: any, yearN: number): string {
  const columns: any[] = data?.table?.columns ?? [];
  const ids: string[] = data?.table?.indicatorIds ?? [];
  const head = columns.map((c) => `<th>${esc(c.label ?? c.type)}</th>`).join("");
  const rows = ids
    .map((id) => {
      const vN = fakeValue(id);
      const vNm1 = fakeValue(id + ":n1");
      const prog = vNm1 ? (((vN - vNm1) / vNm1) * 100).toFixed(1) + " %" : "—";
      const cells = columns.map((c) => {
        if (c.type === "IndicatorName") return `<td>Indicateur ${esc(id)}</td>`;
        if (c.type === "LastValue") return `<td>${vN.toLocaleString("fr-FR")}</td>`;
        if (c.type === "YearXValue") return `<td>${vNm1.toLocaleString("fr-FR")}</td>`;
        if (c.type === "Progression") return `<td>${prog}</td>`;
        return "<td></td>";
      });
      return `<tr>${cells.join("")}</tr>`;
    })
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>`;
}

function renderBlocks(reportJson: any, pastExercices: number, yearN: number): string {
  const blocks: any[] = Array.isArray(reportJson?.blocks) ? reportJson.blocks : [];
  if (blocks.length === 0) {
    return `<h1>Rapport de durabilité ${yearN}</h1><p>Données de démonstration — structure générée par le reporting builder.</p>`;
  }
  return blocks
    .map((b) => {
      if (b.type === "header") {
        const level = Math.min(Math.max(Number(b.data?.level) || 2, 1), 4);
        return `<h${level}>${esc(b.data?.text)}</h${level}>`;
      }
      if (b.type === "chart") return renderChart(b.data, pastExercices, yearN);
      if (b.type === "table") return renderTable(b.data, yearN);
      if (b.type === "text_indicators")
        return `<p>Donnée narrative de démonstration pour l'indicateur ${esc(b.data?.textIndicators?.indicators?.[0]?.indicatorId ?? "")} — contenu généré à partir de la matrice réseau du client.</p>`;
      return "";
    })
    .join("\n");
}

function buildPreviewSrcDoc(report: Report, mode: Mode): string {
  const css = report.css ?? DEFAULT_CSS;
  const yearN = new Date().getFullYear();
  const pastExercices = 5;
  const body = renderBlocks(report.reportJson, pastExercices, yearN);
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${body}</body></html>`;
}
