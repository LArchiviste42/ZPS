import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { createFileRoute } from "@tanstack/react-router";

type Mode = "structure_and_design" | "design_only" | "structure_only";

type ChatTurn = { role: "user" | "assistant"; content: string };

type ChatResponse = {
  reply: string;
  done: boolean;
  reportJson: unknown | null;
  css: string | null;
  excluded: string[];
  notes: string;
  historyId: string | null;
};

type Report = { reportJson: unknown | null; css: string | null };

type HistoryEntry = { id: string; created_at: string; mode: string; client_name: string; summary: string };

const MODES: { value: Mode; title: string; longTitle: string; icon: ReactNode }[] = [
  {
    value: "structure_and_design",
    title: "JSON & CSS",
    longTitle: "Construire et designer le rapport (JSON & CSS)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
        <rect x="3" y="3" width="8" height="8" rx="2" />
        <rect x="13" y="3" width="8" height="5" rx="2" />
        <rect x="13" y="10" width="8" height="11" rx="2" />
        <path d="M3 15h8M3 19h5" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    value: "structure_only",
    title: "JSON",
    longTitle: "Construire le rapport (JSON)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
        <path d="M8 4c-2 0-3 1-3 3v2c0 1-1 2-2 2 1 0 2 1 2 2v2c0 2 1 3 3 3" strokeLinecap="round" />
        <path d="M16 4c2 0 3 1 3 3v2c0 1 1 2 2 2-1 0-2 1-2 2v2c0 2-1 3-3 3" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    value: "design_only",
    title: "CSS",
    longTitle: "Designer le rapport (CSS)",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
        <path d="M12 3a9 9 0 1 0 0 18c1.5 0 2-.8 2-2 0-1.5 1-2 2.5-2H19a2 2 0 0 0 2-2c0-5-4.5-12-9-12z" strokeLinejoin="round" />
        <circle cx="7.5" cy="11.5" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="10.5" cy="7.5" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="15" cy="7.5" r="1.2" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
];

const GREETINGS: Record<Mode, string> = {
  structure_and_design: "Bonjour ! Je construis et designe votre rapport (JSON & CSS). Quel est le nom du client ?",
  structure_only: "Bonjour ! Je construis la structure JSON de votre rapport. Quel est le nom du client ?",
  design_only: "Bonjour ! Je designe le CSS de votre rapport à la charte du client. Quel est le nom du client, et quelle est l'URL de son site web ?",
};

export const Route = createFileRoute("/builder")({
  staticData: { landing: true },
  component: BuilderPage,
});

async function postChat(payload: Record<string, unknown>): Promise<ChatResponse> {
  const res = await fetch("/api/report/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = (await res.json()) as ChatResponse & { detail?: unknown };
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "Le chat a échoué.");
  }
  return data;
}

function BuilderPage() {
  const [mode, setMode] = useState<Mode>("structure_and_design");
  const [view, setView] = useState<"home" | "chat">("home");
  const [turns, setTurns] = useState<ChatTurn[]>([{ role: "assistant", content: GREETINGS.structure_and_design }]);
  const [report, setReport] = useState<Report | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [input, setInput] = useState("");
  const [csvText, setCsvText] = useState("");
  const [csvName, setCsvName] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, pending]);

  const pickMode = (value: Mode) => {
    setMode(value);
    setTurns([{ role: "assistant", content: GREETINGS[value] }]);
    setReport(null);
    setError("");
    setView("chat");
  };

  const refreshHistory = async () => {
    const res = await fetch("/api/report/history");
    if (res.ok) setHistory((await res.json()).entries);
  };

  const toggleHistory = () => {
    const next = !historyOpen;
    setHistoryOpen(next);
    if (next) void refreshHistory();
  };

  const loadHistoryEntry = async (id: string) => {
    const res = await fetch(`/api/report/history/${id}`);
    if (!res.ok) return;
    const data = (await res.json()) as { reportJson: unknown | null; css: string | null; summary: string };
    setReport({ reportJson: data.reportJson, css: data.css });
    setTurns((prev) => [...prev, { role: "assistant", content: `Livrable rechargé depuis l'historique : ${data.summary}` }]);
    setHistoryOpen(false);
  };

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || pending) return;
    const userTurn: ChatTurn = { role: "user", content: csvName ? `${text} 📎 ${csvName}` : text };
    const historyForApi = [...turns, userTurn].map((t) => ({ role: t.role, content: t.content }));
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    setPending(true);
    setError("");
    try {
      const data = await postChat({ mode, messages: historyForApi, csv: csvText || null });
      setTurns((prev) => [...prev, { role: "assistant", content: data.reply }]);
      if (data.done && (data.reportJson != null || data.css != null)) {
        setReport({ reportJson: data.reportJson, css: data.css });
        await refreshHistory();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setPending(false);
      setCsvText("");
      setCsvName("");
    }
  };

  const onFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setCsvName(file.name);
    void file.text().then(setCsvText);
  };

  return (
    <main className="zei-animated-bg flex min-h-full flex-col">
      <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-white/15 bg-zei-navy/95 px-4 py-3 backdrop-blur">
        <button type="button" onClick={() => setView("home")} className="flex items-center gap-3" title="Accueil">
          <img src="/logo-zei-white.svg" alt="Zei" className="h-7 w-auto" />
          <h1 className="text-lg font-extrabold uppercase tracking-wide text-white">Reporting Builder</h1>
        </button>
        <nav className="ml-auto flex items-center gap-2">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => pickMode(m.value)}
              className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold uppercase ${
                mode === m.value
                  ? "border-zei-mint bg-white/20 text-white ring-1 ring-zei-mint"
                  : "border-white/25 bg-white/10 text-white/80 hover:bg-white/20"
              }`}
            >
              <span className="text-zei-mint">{m.icon}</span>
              {m.title}
            </button>
          ))}
          <button
            type="button"
            onClick={toggleHistory}
            className="rounded-lg border border-white/25 bg-white/10 px-3 py-1.5 text-xs font-bold uppercase text-white/80 hover:bg-white/20"
          >
            Historique
          </button>
        </nav>
      </header>

      {view === "home" && (
        <section className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-4 px-6 py-16">
          {(() => {
            const [main, ...rest] = MODES;
            const btnClass = "flex items-center justify-center gap-4 border text-center text-white transition hover:scale-[1.01] border-white/25 bg-white/10 hover:bg-white/20";
            return (
              <>
                <button
                  key={main.value}
                  type="button"
                  onClick={() => pickMode(main.value)}
                  className={`${btnClass} w-full rounded-2xl px-6 py-8`}
                >
                  <span className="shrink-0 text-zei-mint">{main.icon}</span>
                  <span className="text-xl font-extrabold uppercase tracking-wide">{main.longTitle}</span>
                </button>
                <div className="grid w-full grid-cols-2 gap-4">
                  {rest.map((m) => (
                    <button
                      key={m.value}
                      type="button"
                      onClick={() => pickMode(m.value)}
                      className={`${btnClass} rounded-lg px-4 py-6`}
                    >
                      <span className="shrink-0 text-zei-mint">{m.icon}</span>
                      <span className="text-sm font-bold uppercase">{m.longTitle}</span>
                    </button>
                  ))}
                </div>
              </>
            );
          })()}
        </section>
      )}

      {view === "chat" && (
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 px-6 py-6">
        {historyOpen && (
          <aside className="rounded-2xl border border-white/20 bg-zei-navy/80 p-4">
            <h2 className="mb-2 text-sm font-bold uppercase text-white">Historique des demandes</h2>
            {history.length === 0 && <p className="text-sm text-white/60">Aucune demande pour l'instant.</p>}
            <ul className="flex flex-col gap-2">
              {history.map((h) => (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => void loadHistoryEntry(h.id)}
                    className="w-full rounded-xl border border-white/15 bg-white/10 px-3 py-2 text-left text-sm text-white hover:bg-white/20"
                  >
                    <span className="font-bold">{h.client_name || "Sans nom"}</span> · {h.mode} ·{" "}
                    <span className="text-white/60">{new Date(h.created_at).toLocaleString("fr-FR")}</span>
                    <span className="block text-xs text-white/60">{h.summary}</span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        )}

        <div className="flex flex-1 flex-col gap-3">
          {turns.map((turn, index) => (
            <div
              key={index}
              className={
                turn.role === "user"
                  ? "self-end rounded-2xl rounded-br-sm bg-white/20 px-4 py-2.5 text-sm text-white"
                  : "self-start rounded-2xl rounded-bl-sm bg-white/10 px-4 py-2.5 text-sm text-white"
              }
            >
              {turn.role === "assistant" && (
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wide text-zei-mint">
                  Zai (Le Chonk)
                </span>
              )}
              <span className="whitespace-pre-wrap">{turn.content}</span>
            </div>
          ))}
          {pending && (
            <div className="self-start rounded-2xl rounded-bl-sm bg-white/10 px-4 py-2.5 text-sm text-white/80">
              <span className="animate-pulse">Zai (Le Chonk) réfléchit…</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {report && (
          <div className="overflow-hidden rounded-2xl border border-white/20 bg-white">
            <iframe title="Aperçu du rapport" className="h-[420px] w-full" srcDoc={buildPreviewSrcDoc(report)} />
          </div>
        )}

        {error && <p className="text-sm font-semibold text-red-300">{error}</p>}

        <form onSubmit={send} className="flex items-center gap-2 rounded-2xl bg-white/10 p-3">
          <label className="cursor-pointer rounded-full border border-white/25 px-3 py-2 text-xs font-bold text-white/80 hover:bg-white/20" title="Joindre le CSV de la matrice réseau">
            📎 CSV
            <input type="file" accept=".csv,text/csv" onChange={onFile} className="hidden" />
          </label>
          {csvName && <span className="max-w-40 truncate text-xs text-zei-mint">{csvName}</span>}
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Répondez au chat…"
            className="flex-1 rounded-full border border-white/25 bg-white/10 px-4 py-2.5 text-sm text-white outline-none placeholder:text-white/50 focus:border-zei-mint focus:ring-2 focus:ring-zei-mint/40"
          />
          <button
            type="submit"
            disabled={pending || input.trim() === ""}
            className="rounded-full bg-zei-mint px-5 py-2.5 text-sm font-bold text-zei-navy transition hover:brightness-110 disabled:opacity-50"
          >
            Envoyer
          </button>
        </form>
      </div>
      )}
    </main>
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

function renderChart(data: any): string {
  const indicators: any[] = data?.chart?.indicators ?? [];
  const width = 640;
  const height = 240;
  const pad = 32;
  const yearN = new Date().getFullYear();
  const years: number[] = [];
  for (let i = 5; i >= 0; i--) years.push(yearN - i);
  const series = indicators.map((ind) => {
    const base = fakeValue(String(ind.indicatorId));
    return years.map((y, i) => ({ x: pad + (i * (width - 2 * pad)) / Math.max(years.length - 1, 1), y: height - pad - ((base + i * 37) % 180), year: y }));
  });
  const colors = ["#262882", "#4347e8", "#58b896"];
  const polylines = series
    .map((pts, idx) => `<polyline fill="none" stroke="${colors[idx % 3]}" stroke-width="2.5" points="${pts.map((p) => `${p.x},${p.y}`).join(" ")}" />`)
    .join("");
  const xLabels = years
    .map((y, i) => `<text x="${pad + (i * (width - 2 * pad)) / Math.max(years.length - 1, 1)}" y="${height - 8}" font-size="11" text-anchor="middle" fill="#3c3c3b">${y}</text>`)
    .join("");
  const legend = indicators.map((ind, idx) => `<span style="margin-right:12px;color:${colors[idx % 3]}">● indicateur ${esc(ind.indicatorId)}</span>`).join("");
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;background:rgba(88,184,150,0.08);border-radius:12px">${polylines}${xLabels}<text x="${pad}" y="16" font-size="11" fill="#3c3c3b">${legend}</text></svg>`;
}

function renderTable(data: any): string {
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

function renderBlocks(reportJson: any): string {
  const blocks: any[] = Array.isArray(reportJson?.blocks) ? reportJson.blocks : [];
  if (blocks.length === 0) {
    return `<h1>Rapport de durabilité ${new Date().getFullYear()}</h1><p>Données de démonstration — structure générée par le reporting builder.</p>`;
  }
  return blocks
    .map((b) => {
      if (b.type === "header") {
        const level = Math.min(Math.max(Number(b.data?.level) || 2, 1), 4);
        return `<h${level}>${esc(b.data?.text)}</h${level}>`;
      }
      if (b.type === "chart") return renderChart(b.data);
      if (b.type === "table") return renderTable(b.data);
      if (b.type === "text_indicators")
        return `<p>Donnée narrative de démonstration pour l'indicateur ${esc(b.data?.textIndicators?.indicators?.[0]?.indicatorId ?? "")} — contenu généré à partir de la matrice réseau du client.</p>`;
      return "";
    })
    .join("\n");
}

function buildPreviewSrcDoc(report: Report): string {
  const css = report.css ?? DEFAULT_CSS;
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${renderBlocks(report.reportJson)}</body></html>`;
}
