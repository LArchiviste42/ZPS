import { useRef, useState } from "react";
import type { FormEvent, ReactNode, Ref } from "react";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

type Mode = "structure_and_design" | "design_only" | "structure_only";

type ReportResponse = {
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

const inputClass =
  "w-full rounded-xl border border-white/25 bg-white/10 px-3 py-2 text-sm text-white outline-none placeholder:text-white/50 focus:border-zei-mint focus:ring-2 focus:ring-zei-mint/40";
const labelClass = "mb-1 block text-xs font-semibold uppercase tracking-wide text-white/70";

function BuilderPage() {
  const [mode, setMode] = useState<Mode | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const chatRef = useRef<HTMLElement>(null);

  const pickMode = (value: Mode) => {
    setMode(value);
    setTurns([]);
    setTimeout(() => chatRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  const generate = useMutation({
    mutationFn: (payload: Record<string, unknown>) => postReport(payload),
    onSuccess: (data, payload) => {
      const label = MODES.find((m) => m.value === payload.mode)?.title ?? "Rapport";
      const parts: string[] = [];
      if (data.reportJson != null) parts.push("```json\n" + JSON.stringify(data.reportJson, null, 2) + "\n```");
      if (data.css != null) parts.push("```css\n" + data.css + "\n```");
      if (data.excluded.length > 0) parts.push(`Indicateurs NA/NM exclus : ${data.excluded.join(", ")}`);
      if (data.notes) parts.push(data.notes);
      setTurns((prev) => [
        ...prev,
        { role: "assistant", content: `**${label}** — livrable généré :\n\n${parts.join("\n\n")}` },
      ]);
    },
    onError: (error) => {
      setTurns((prev) => [...prev, { role: "assistant", content: `Erreur : ${error.message}` }]);
    },
  });

  return (
    <main className="zei-animated-bg flex min-h-full flex-col">
      <section className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-8 px-6 py-16 text-center">
        <img src="/logo-zei-white.svg" alt="Zei" className="h-14 w-auto" />
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight text-white sm:text-5xl">
            Reporting Builder by Zei
          </h1>
          <p className="mt-2 text-sm font-semibold text-zei-mint">by Zei Professionnal Services</p>
        </div>

        <div className="flex w-full flex-col gap-4">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => pickMode(m.value)}
              className={`flex w-full items-center gap-4 rounded-2xl border px-6 py-5 text-left transition hover:scale-[1.01] ${
                mode === m.value
                  ? "border-zei-mint bg-white/20 ring-2 ring-zei-mint"
                  : "border-white/25 bg-white/10 hover:bg-white/20"
              }`}
            >
              <span className="text-zei-mint">{m.icon}</span>
              <span className="text-lg font-bold text-white">{m.title}</span>
            </button>
          ))}
        </div>
      </section>

      {mode && (
        <ChatSection
          ref={chatRef}
          mode={mode}
          turns={turns}
          pending={generate.isPending}
          onSubmit={(payload, summary) => {
            setTurns((prev) => [...prev, { role: "user", content: summary }]);
            generate.mutate(payload);
          }}
        />
      )}
    </main>
  );
}

const ChatSection = ({
  mode,
  turns,
  pending,
  onSubmit,
  chatRef,
}: {
  mode: Mode;
  turns: ChatTurn[];
  pending: boolean;
  onSubmit: (payload: Record<string, unknown>, summary: string) => void;
  chatRef: Ref<HTMLElement>;
}) => {
  const [clientName, setClientName] = useState("");
  const [clientUrl, setClientUrl] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [networkId, setNetworkId] = useState("");
  const [exerciceId, setExerciceId] = useState("");
  const [yearN, setYearN] = useState("2026");
  const [yearNMinus1, setYearNMinus1] = useState("2025");
  const [pastExercices, setPastExercices] = useState("5");
  const [indicatorsText, setIndicatorsText] = useState("");
  const [formError, setFormError] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFormError("");

    let indicators: unknown[] = [];
    if (mode !== "design_only") {
      try {
        const parsed = JSON.parse(indicatorsText || "[]");
        if (!Array.isArray(parsed)) throw new Error("Le JSON doit être un tableau.");
        if (parsed.length === 0) throw new Error("Ajoutez au moins un indicateur.");
        indicators = parsed;
      } catch (error) {
        setFormError(`Indicateurs invalides : ${error instanceof Error ? error.message : String(error)}`);
        return;
      }
    }

    const payload = {
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
    };
    const summary = `Client **${clientName}** (${clientUrl}) — org ${organizationId}, network ${networkId}, exercice N-1 ${exerciceId}, ${yearN}/${yearNMinus1}, ${pastExercices} exercices passés, ${indicators.length} indicateur(s). Mode : ${mode}.`;
    onSubmit(payload, summary);
  };

  const modeTitle = MODES.find((m) => m.value === mode)?.title ?? mode;

  return (
    <section ref={chatRef} className="zei-chat-bg border-t border-white/15">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-6 py-8">
        <h2 className="text-center text-xl font-bold text-white">{modeTitle}</h2>

        <div className="flex flex-col gap-3">
          {turns.length === 0 && (
            <p className="text-center text-sm text-white/70">
              Renseignez le contexte ci-dessous, le chat générera le livrable avec la logique du skill zei-rapport-json.
            </p>
          )}
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
          {pending && (
            <div className="self-start rounded-2xl rounded-bl-sm bg-white/10 px-4 py-2.5 text-sm text-white/80">
              <span className="animate-pulse">zei génère le livrable…</span>
            </div>
          )}
        </div>

        <form onSubmit={submit} className="flex flex-col gap-3 rounded-2xl bg-white/10 p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={labelClass} htmlFor="clientName">Nom du client</label>
              <input id="clientName" className={inputClass} value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Ex. EDF" required />
            </div>
            <div>
              <label className={labelClass} htmlFor="clientUrl">Site web du client</label>
              <input id="clientUrl" className={inputClass} type="url" value={clientUrl} onChange={(e) => setClientUrl(e.target.value)} placeholder="https://…" required />
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
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
                rows={5}
                className={`${inputClass} font-mono`}
                value={indicatorsText}
                onChange={(e) => setIndicatorsText(e.target.value)}
                placeholder='[{"theme":"Environnement","subTheme":"GES","category":"Scope 1","name":"Émissions GES","type":"Nombre","parentId":412225}]'
                required
              />
            </div>
          )}
          {formError && <p className="text-sm font-semibold text-red-300">{formError}</p>}
          <button
            type="submit"
            disabled={pending}
            className="self-start rounded-full bg-zei-mint px-6 py-2.5 text-sm font-bold text-zei-navy transition hover:brightness-110 disabled:opacity-50"
          >
            {pending ? "Génération…" : "Envoyer au chat"}
          </button>
        </form>
      </div>
    </section>
  );
};
