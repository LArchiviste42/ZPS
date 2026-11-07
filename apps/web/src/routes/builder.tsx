import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { createFileRoute } from "@tanstack/react-router";

type Mode = "structure_and_design" | "design_only" | "structure_only";

type FieldSpec = { key: string; label: string; type: "text" | "number" | "file" | "choice"; choices?: string[] | null; placeholder?: string | null };

type ChatTurn = { role: "user" | "assistant"; content: string; options?: string[]; fields?: FieldSpec[]; awaitingFile?: boolean };

type ChatResponse = {
  reply: string;
  done: boolean;
  options: string[];
  fields: FieldSpec[];
  awaitingFile: boolean;
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
  structure_and_design: "Bonjour ! On commence par le JSON : quel est le fichier matrice réseau (CSV/XLSX) du client ?",
  structure_only: "Bonjour ! Quel est le fichier matrice réseau (CSV/XLSX) du client ?",
  design_only: "Bonjour ! Je designe le CSS de votre rapport à la charte du client. Quel est le nom du client, et quelle est l'URL de son site web ?",
};

export const Route = createFileRoute("/builder")({
  staticData: { landing: true },
  component: BuilderPage,
});

// The gateway can answer a 5xx with an HTML error page: never call res.json() blindly.
async function fetchJson(
  url: string,
  payload?: Record<string, unknown>,
): Promise<{ ok: boolean; status: number; data: any }> {
  const res = await fetch(
    url,
    payload
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }
      : undefined,
  );
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  return { ok: res.ok, status: res.status, data };
}

async function postChat(payload: Record<string, unknown>): Promise<ChatResponse> {
  let result = await fetchJson("/api/report/chat", payload);
  // One automatic retry on a transient gateway 5xx (e.g. 504 timeout).
  if (!result.ok && result.status >= 500) {
    await new Promise((r) => setTimeout(r, 2000));
    result = await fetchJson("/api/report/chat", payload);
  }
  if (!result.ok || result.data == null) {
    const detail = result.data?.detail;
    throw new Error(typeof detail === "string" ? detail : `Zai (Le Chonk) n'a pas pu répondre (erreur ${result.status}). Réessaie.`);
  }
  return result.data as ChatResponse;
}

function BuilderPage() {
  const [mode, setMode] = useState<Mode>("structure_and_design");
  const [view, setView] = useState<"home" | "chat">("home");
  const [turns, setTurns] = useState<ChatTurn[]>([{ role: "assistant", content: GREETINGS.structure_and_design }]);
  const [report, setReport] = useState<Report | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [previewFull, setPreviewFull] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyQuery, setHistoryQuery] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [input, setInput] = useState("");
  const [csvText, setCsvText] = useState("");
  const [csvName, setCsvName] = useState("");
  const [csvB64, setCsvB64] = useState("");
  const [imgB64, setImgB64] = useState("");
  const [imgName, setImgName] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  const readUpload = (file: File) => {
    setCsvName(file.name);
    if (file.type.startsWith("image/")) {
      setCsvText("");
      setCsvB64("");
      setImgName(file.name);
      void file.arrayBuffer().then((buf) => {
        let bin = "";
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i] ?? 0);
        setImgB64(btoa(bin));
      });
      return;
    }
    setImgB64("");
    setImgName("");
    if (file.name.toLowerCase().endsWith(".xlsx")) {
      setCsvText("");
      void file.arrayBuffer().then((buf) => {
        let bin = "";
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i] ?? 0);
        setCsvB64(btoa(bin));
      });
    } else {
      setCsvB64("");
      void file.text().then(setCsvText);
    }
  };
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
    const { ok, data } = await fetchJson("/api/report/history");
    if (ok && data) setHistory(data.entries);
  };

  const toggleHistory = () => {
    const next = !historyOpen;
    setHistoryOpen(next);
    if (next) {
      setHistoryQuery("");
      void refreshHistory();
    }
  };

  const filteredHistory = history.filter((h) =>
    (h.client_name || "").toLowerCase().includes(historyQuery.trim().toLowerCase()),
  );

  const modeTags = (mode: string): string[] =>
    mode === "structure_only" ? ["JSON"] : mode === "design_only" ? ["CSS"] : ["JSON", "CSS"];

  // Group by client, newest client first; within a client, entries are versions (newest first).
  const groupedHistory = Object.entries(
    filteredHistory.reduce((acc, h) => {
      const key = h.client_name || "Sans nom";
      (acc[key] ??= []).push(h);
      return acc;
    }, {} as Record<string, HistoryEntry[]>),
  ).sort((a, b) => (b[1][0]?.created_at ?? "").localeCompare(a[1][0]?.created_at ?? ""));

  const loadHistoryEntry = async (id: string) => {
    const { ok, data } = await fetchJson(`/api/report/history/${id}`);
    if (!ok || !data) return;
    setReport({ reportJson: data.reportJson, css: data.css });
    setTurns((prev) => [...prev, { role: "assistant", content: `Livrable rechargé depuis l'historique : ${data.summary}` }]);
    setHistoryOpen(false);
  };

  const sendText = async (raw: string, uploadOverride?: { text: string | null; b64: string | null; imgB64?: string | null }) => {
    const text = raw.trim();
    if (!text || pending) return;
    const userTurn: ChatTurn = { role: "user", content: csvName ? `${text} 📎 ${csvName}` : text };
    const historyForApi = [...turns, userTurn].map((t) => ({ role: t.role, content: t.content }));
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    setPending(true);
    setError("");
    try {
      const data = await postChat({
        mode,
        messages: historyForApi,
        csv: uploadOverride?.text ?? (csvText || null),
        fileB64: uploadOverride?.b64 ?? (csvB64 || null),
        imageB64: uploadOverride?.imgB64 ?? (imgB64 || null),
        reportJson: report?.reportJson ?? null,
        css: report?.css ?? null,
      });
      setTurns((prev) => [...prev, { role: "assistant", content: data.reply, options: data.options, fields: data.fields, awaitingFile: data.awaitingFile }]);
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
      setCsvB64("");
      setImgB64("");
      setImgName("");
    }
  };

  const status = (() => {
    const lastUser = [...turns].reverse().find((t) => t.role === "user")?.content ?? "";
    if (imgB64) return "analyse de la capture d'écran du site (couleurs, polices, style)…";
    if (csvName || /📎/.test(lastUser))
      return "récupération du fichier et analyse de la matrice réseau pour construire le JSON et l'aperçu…";
    if (/https?:\/\//.test(lastUser)) return "lecture du site du client pour extraire la charte graphique (couleurs, polices)…";
    if (lastUser.trim()) return `enregistrement de la demande « ${lastUser.slice(0, 40)} » — ouverture de la session et stockage dans l'historique…`;
    if (report?.css || report?.reportJson) return "mise à jour du livrable selon ta demande…";
    if (mode === "design_only") return "préparation du CSS à la charte du client…";
    return "rédaction du JSON et de l'aperçu…";
  })();

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleAwaitedFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    readUpload(file);
    const upload = file.type.startsWith("image/")
      ? { text: null, b64: null, imgB64: imgB64 }
      : file.name.toLowerCase().endsWith(".xlsx")
        ? { text: null, b64: csvB64, imgB64: null }
        : { text: csvText, b64: null, imgB64: null };
    // readUpload is async (arrayBuffer/text); read again synchronously is not possible, so re-read:
    void (file.type.startsWith("image/") || file.name.toLowerCase().endsWith(".xlsx")
      ? file.arrayBuffer()
      : file.text()
    ).then((content) => {
      let up = upload;
      if (file.type.startsWith("image/")) {
        let bin = "";
        const bytes = new Uint8Array(content as ArrayBuffer);
        for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i] ?? 0);
        up = { text: null, b64: null, imgB64: btoa(bin) };
      } else if (file.name.toLowerCase().endsWith(".xlsx")) {
        let bin = "";
        const bytes = new Uint8Array(content as ArrayBuffer);
        for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i] ?? 0);
        up = { text: null, b64: btoa(bin), imgB64: null };
      } else {
        up = { text: content as string, b64: null, imgB64: null };
      }
      void sendText(`📎 ${file.name}`, up);
    });
  };

  const handleFiles = (files: FileList | File[]) => {
    const f = files[0];
    if (f) readUpload(f);
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const item = [...e.clipboardData.items].find((i) => i.type.startsWith("image/"));
    if (!item) return;
    const file = item.getAsFile();
    if (file) {
      e.preventDefault();
      readUpload(file);
    }
  };

  const send = (event: FormEvent) => {
    event.preventDefault();
    void sendText(input);
  };

  const onFile = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) readUpload(file);
  };

  return (
    <main className="zei-animated-bg flex min-h-full flex-col">
      <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-white/10 bg-transparent px-4 py-3">
        <button type="button" onClick={() => setView("home")} className="flex items-center gap-3" title="Accueil">
          <img src="/logo-zei-white.svg" alt="Zei" className="h-7 w-auto" />
          <h1 className="text-lg font-extrabold uppercase tracking-wide text-white">Reporting Builder</h1>
          <span className="flex items-center gap-1 text-[10px] font-semibold normal-case text-white/60">
            powered by Mistral
            <img src="/drapeau-eu.png" alt="Union européenne" className="h-4 w-auto rounded-[2px]" />
          </span>
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
            const [first, ...rest] = MODES;
            if (!first) return null;
            const main = first;
            const btnClass = "flex flex-col items-center justify-center gap-3 border text-center text-white transition hover:scale-[1.01] border-white/25 bg-white/10 hover:bg-white/20";
            return (
              <>
                <button
                  key={main.value}
                  type="button"
                  onClick={() => pickMode(main.value)}
                  className={`${btnClass} w-full rounded-2xl px-6 py-12`}
                >
                  <span className="text-zei-mint [&>svg]:h-12 [&>svg]:w-12">{main.icon}</span>
                  <span className="text-xl font-extrabold uppercase tracking-wide">{main.longTitle}</span>
                </button>
                <div className="grid w-full grid-cols-2 gap-4">
                  {rest.map((m) => (
                    <button
                      key={m.value}
                      type="button"
                      onClick={() => pickMode(m.value)}
                      className={`${btnClass} rounded-lg px-4 py-10`}
                    >
                      <span className="text-zei-mint [&>svg]:h-10 [&>svg]:w-10">{m.icon}</span>
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
      <div
        className={`mx-auto flex w-full ${report ? "max-w-none px-2" : "max-w-3xl px-6"} flex-1 flex-col gap-4 py-6 rounded-2xl transition ${isDragging ? "ring-2 ring-zei-mint bg-white/5" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        onPaste={handlePaste}
      >
        {historyOpen && (
          <aside className="fixed inset-y-0 right-0 z-20 flex w-80 max-w-full flex-col gap-3 border-l border-white/15 bg-zei-navy/95 p-4 shadow-2xl backdrop-blur">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold uppercase text-white">Historique des demandes</h2>
              <button
                type="button"
                onClick={() => setHistoryOpen(false)}
                className="rounded-full border border-white/25 px-2.5 py-1 text-xs font-bold text-white/80 hover:bg-white/20"
              >
                ✕
              </button>
            </div>
            <input
              value={historyQuery}
              onChange={(e) => setHistoryQuery(e.target.value)}
              placeholder="Rechercher une entreprise…"
              className="w-full rounded-xl border border-white/25 bg-white/10 px-3 py-2 text-sm text-white outline-none placeholder:text-white/50 focus:border-zei-mint focus:ring-2 focus:ring-zei-mint/40"
            />
            {filteredHistory.length === 0 && (
              <p className="text-sm text-white/60">
                {history.length === 0 ? "Aucune demande pour l'instant." : "Aucun résultat pour cette recherche."}
              </p>
            )}
            <ul className="flex flex-1 flex-col gap-3 overflow-y-auto">
              {groupedHistory.map(([client, entries]) => (
                <li key={client}>
                  <p className="mb-1 flex items-center justify-between px-1 text-xs font-extrabold uppercase tracking-wide text-zei-mint">
                    <span>{client}</span>
                    <span className="text-white/50">
                      {entries.length} version{entries.length > 1 ? "s" : ""}
                    </span>
                  </p>
                  <ul className="flex flex-col gap-1.5">
                    {entries.map((h, i) => (
                      <li key={h.id}>
                        <button
                          type="button"
                          onClick={() => void loadHistoryEntry(h.id)}
                          className="w-full rounded-xl border border-white/15 bg-white/10 px-3 py-2 text-left text-sm text-white hover:bg-white/20"
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="text-xs font-bold text-white/90">v{entries.length - i}</span>
                            <span className="flex gap-1">
                              {modeTags(h.mode).map((tag) => (
                                <span
                                  key={tag}
                                  className={`rounded-full px-2 py-0.5 text-[10px] font-extrabold uppercase ${
                                    tag === "JSON" ? "bg-zei-indigo text-white" : "bg-zei-mint text-zei-navy"
                                  }`}
                                >
                                  {tag}
                                </span>
                              ))}
                            </span>
                          </span>
                          <span className="mt-1 block text-xs text-white/60">
                            {new Date(h.created_at).toLocaleString("fr-FR")}
                          </span>
                          <span className="block text-xs text-white/60">{h.summary}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </aside>
        )}

        {report && (
          <div className="grid flex-1 gap-4 lg:h-[calc(100vh-7rem)] lg:grid-cols-[3fr_2fr]">
            <div className="flex flex-col gap-3">
              <div className="relative overflow-hidden rounded-2xl border border-white/20 bg-white">
                <iframe title="Aperçu du rapport" className="h-[560px] w-full" srcDoc={buildPreviewSrcDoc(report, 0.5)} />
                <button
                  type="button"
                  onClick={() => setPreviewFull(true)}
                  title="Agrandir l'aperçu"
                  className="absolute right-2 top-2 rounded-full bg-zei-navy/80 px-2.5 py-1.5 text-sm text-white transition hover:bg-zei-navy"
                >
                  ⤢ Agrandir
                </button>
              </div>
              {report.css && <DownloadCssButton css={report.css} />}
              {report.reportJson != null && <DownloadJsonButton reportJson={report.reportJson} />}
              {(report.css || report.reportJson != null) && (
                <p className="text-center text-xs text-white/50">à copier-coller dans Zei</p>
              )}
            </div>
            <ChatColumn
              turns={turns}
              pending={pending}
              error={error}
              input={input}
              setInput={setInput}
              csvName={csvName}
              imgName={imgName}
          onPickFile={() => fileInputRef.current?.click()}
              onFile={onFile}
              onSend={send}
              onSendText={(t, u) => void sendText(t, u)}
              status={status}
              bottomRef={bottomRef}
            />
          </div>
        )}

        {previewFull && report && (
          <div
            className="fixed inset-0 z-30 flex items-center justify-center bg-zei-navy/80 p-4 backdrop-blur-sm"
            onClick={() => setPreviewFull(false)}
          >
            <div
              className="flex h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-white/20 bg-white"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between bg-zei-navy px-4 py-2">
                <span className="text-sm font-bold text-white">Aperçu du rapport — taille réelle</span>
                <button
                  type="button"
                  onClick={() => setPreviewFull(false)}
                  className="rounded-full border border-white/25 px-2.5 py-1 text-xs font-bold text-white/80 hover:bg-white/20"
                >
                  ✕ Fermer
                </button>
              </div>
              <iframe title="Aperçu du rapport en taille réelle" className="w-full flex-1" srcDoc={buildPreviewSrcDoc(report, 1)} />
            </div>
          </div>
        )}

        {!report && (
        <ChatColumn
          turns={turns}
          pending={pending}
          error={error}
          input={input}
          setInput={setInput}
          csvName={csvName}
          imgName={imgName}
          onPickFile={() => fileInputRef.current?.click()}
          onFile={onFile}
          onSend={send}
          onSendText={(t, u) => void sendText(t, u)}
          status={status}
          bottomRef={bottomRef}
        />
        )}
      </div>
      )}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,.csv,.xlsx,text/csv"
        className="hidden"
        onChange={handleAwaitedFile}
      />
    </main>
  );
}

function ChatColumn({
  turns,
  pending,
  error,
  input,
  setInput,
  csvName,
  imgName,
  onFile,
  onPickFile,
  onSend,
  onSendText,
  status,
  bottomRef,
}: {
  turns: ChatTurn[];
  pending: boolean;
  error: string;
  input: string;
  setInput: (v: string) => void;
  csvName: string;
  imgName: string;
  onFile: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onPickFile: () => void;
  onSend: (e: FormEvent) => void;
  onSendText: (text: string, upload?: { text: string | null; b64: string | null; imgB64?: string | null }) => void;
  status: string;
  bottomRef: React.Ref<HTMLDivElement>;
}) {
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-3">
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
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
              {turn.role === "assistant" && turn.awaitingFile && !turn.fields?.some((f) => f.type === "file") && (
                <div className="mt-2">
                  <button
                    type="button"
                    disabled={pending}
                    onClick={() => onPickFile()}
                    className="rounded-full border border-zei-mint bg-zei-mint/20 px-4 py-1.5 text-xs font-bold text-white transition hover:bg-zei-mint hover:text-zei-navy disabled:opacity-50"
                  >
                    📎 Ajouter un fichier
                  </button>
                </div>
              )}
              {turn.role === "assistant" && turn.fields && turn.fields.length > 0 && (
                <Questionnaire fields={turn.fields} disabled={pending} onSubmit={onSendText} />
              )}
              {turn.role === "assistant" && turn.options && turn.options.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {turn.options.map((opt) => (
                    <button
                      key={opt}
                      type="button"
                      disabled={pending}
                      onClick={() => onSendText(opt)}
                      className="rounded-full border border-zei-mint bg-zei-mint/20 px-4 py-1.5 text-xs font-bold text-white transition hover:bg-zei-mint hover:text-zei-navy disabled:opacity-50"
                    >
                      {opt}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
          {pending && (
            <div className="self-start rounded-2xl rounded-bl-sm bg-white/10 px-6 py-5">
              <span className="mb-1 block text-[10px] font-bold uppercase tracking-wide text-zei-mint">
                Zai (Le Chonk) réfléchit…
              </span>
              <div className="h-48 w-64">
                <ChonkThinking />
              </div>
              <div className="zei-progress-bar mt-3 w-96 max-w-full">
                <span />
              </div>
              <p className="mt-2 text-xs text-white/70">{status}</p>
            </div>
          )}
          <div ref={bottomRef} />
      </div>

        {error && <p className="shrink-0 text-sm font-semibold text-red-300">{error}</p>}

        <form onSubmit={onSend} className="flex shrink-0 items-center gap-2 rounded-2xl bg-white/10 p-3">
          <label className="cursor-pointer rounded-full border border-white/25 px-3 py-2 text-xs font-bold text-white/80 hover:bg-white/20" title="Joindre un fichier (CSV/XLSX matrice réseau, ou capture d'écran du site)">
            📎 Fichier
            <input type="file" accept="image/*,.csv,.xlsx,text/csv" onChange={onFile} className="hidden" />
          </label>
          {csvName && <span className="max-w-40 truncate text-xs text-zei-mint">📎 {csvName}</span>}
          {imgName && <span className="max-w-40 truncate text-xs text-zei-mint">🖼 {imgName}</span>}
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Répondez au chat… (glissez-déposez ou collez une image ici)"
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
  );
}

function DownloadCssButton({ css }: { css: string }) {
  const [done, setDone] = useState(false);
  const action = async () => {
    try {
      await navigator.clipboard.writeText(css);
    } catch {
      /* presse-papiers indisponible : le téléchargement suffit */
    }
    const url = URL.createObjectURL(new Blob([css], { type: "text/css" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "rapport-zei.css";
    a.click();
    URL.revokeObjectURL(url);
    setDone(true);
    setTimeout(() => setDone(false), 2500);
  };
  return (
    <button
      type="button"
      onClick={() => void action()}
      className="w-full rounded-2xl bg-zei-mint px-6 py-4 text-base font-extrabold uppercase tracking-wide text-zei-navy transition hover:brightness-110"
    >
      {done ? "✓ CSS copié et téléchargé" : "⬇ Télécharger le CSS"}
    </button>
  );
}

function DownloadJsonButton({ reportJson }: { reportJson: unknown }) {
  const action = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(reportJson, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "rapport-zei.json";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <button
      type="button"
      onClick={action}
      className="w-full rounded-2xl border border-zei-mint bg-white/10 px-6 py-3 text-sm font-bold uppercase tracking-wide text-zei-mint transition hover:bg-white/20"
    >
      ⬇ Télécharger le JSON
    </button>
  );
}

/* ---------- Zai (Le Chonk), gros chaton animé ---------- */

function Questionnaire({
  fields,
  disabled,
  onSubmit,
}: {
  fields: FieldSpec[];
  disabled: boolean;
  onSubmit: (text: string, upload?: { text: string | null; b64: string | null; imgB64?: string | null }) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [csv, setCsv] = useState<{ name: string; text: string | null; b64: string | null; imgB64?: string | null } | null>(null);
  const set = (key: string, v: string) => setValues((prev) => ({ ...prev, [key]: v }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const lines = fields
      .filter((f) => f.type !== "file")
      .map((f) => `${f.key}: ${values[f.key] ?? ""}`)
      .filter((l) => !l.endsWith(": "));
    const text = lines.join("\n") || "Réponses envoyées.";
    onSubmit(csv ? `${text}\n📎 ${csv.name}` : text, csv ? { text: csv.text, b64: csv.b64, imgB64: csv.imgB64 ?? null } : undefined);
  };

  return (
    <form onSubmit={submit} className="mt-2 flex flex-col gap-2 rounded-xl bg-white/10 p-3">
      {fields.map((f) => (
        <div key={f.key}>
          <label className="mb-1 block text-[10px] font-bold uppercase tracking-wide text-white/70">{f.label}</label>
          {f.type === "choice" && f.choices ? (
            <div className="flex flex-wrap gap-1.5">
              {f.choices.map((c) => (
                <button
                  key={c}
                  type="button"
                  disabled={disabled}
                  onClick={() => set(f.key, c)}
                  className={`rounded-full border px-3 py-1 text-xs font-bold ${
                    values[f.key] === c
                      ? "border-zei-mint bg-zei-mint text-zei-navy"
                      : "border-white/25 bg-white/10 text-white hover:bg-white/20"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          ) : f.type === "file" ? (
            <label className="inline-block cursor-pointer rounded-full border border-white/25 bg-white/10 px-3 py-1.5 text-xs font-bold text-white/80 hover:bg-white/20">
              📎 Choisir un fichier (CSV/XLSX ou capture d'écran)
              <input
                type="file"
                accept="image/*,.csv,.xlsx,text/csv"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  if (file.type.startsWith("image/")) {
                    void file.arrayBuffer().then((buf) => {
                      let bin = "";
                      const bytes = new Uint8Array(buf);
                      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i] ?? 0);
                      setCsv({ name: file.name, text: null, b64: null, imgB64: btoa(bin) });
                    });
                    return;
                  }
                  if (file.name.toLowerCase().endsWith(".xlsx")) {
                    void file.arrayBuffer().then((buf) => {
                      let bin = "";
                      const bytes = new Uint8Array(buf);
                      for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i] ?? 0);
                      setCsv({ name: file.name, text: null, b64: btoa(bin) });
                    });
                  } else {
                    void file.text().then((t) => setCsv({ name: file.name, text: t, b64: null }));
                  }
                }}
              />
            </label>
          ) : (
            <input
              type={f.type === "number" ? "number" : "text"}
              value={values[f.key] ?? ""}
              placeholder={f.placeholder ?? ""}
              onChange={(e) => set(f.key, e.target.value)}
              className="w-full rounded-lg border border-white/25 bg-white/10 px-3 py-1.5 text-xs text-white outline-none placeholder:text-white/40 focus:border-zei-mint"
            />
          )}
          {f.type === "file" && csv && <span className="ml-2 text-xs text-zei-mint">{csv.name}</span>}
        </div>
      ))}
      <button
        type="submit"
        disabled={disabled}
        className="self-start rounded-full bg-zei-mint px-4 py-1.5 text-xs font-bold text-zei-navy disabled:opacity-50"
      >
        Envoyer les réponses
      </button>
    </form>
  );
}

function ChonkThinking() {
  // Gros chat orange (style Mistral) SUR LE DOS, pattes en l'air qui jouent avec la pelote de laine verte Zei.
  return (
    <svg
      viewBox="0 0 140 96"
      className="chonk-bob h-full w-auto"
      role="img"
      aria-label="Zai (Le Chonk), chat orange sur le dos qui joue avec une pelote de laine verte Zei"
    >
      {/* fil de laine */}
      <path
        className="chonk-thread"
        d="M118 34 C 130 40, 136 28, 126 24 C 116 20, 108 30, 96 26"
        stroke="#58B896"
        strokeWidth="2.5"
        fill="none"
        strokeLinecap="round"
      />
      {/* pelote verte Zei qui rebondit au-dessus des pattes */}
      <g className="chonk-ball">
        <circle cx="104" cy="24" r="14" fill="#58B896" />
        <path d="M92 20 Q104 14 116 20 M91 26 Q104 20 117 26 M94 32 Q104 26 114 32" stroke="#3E8E6E" strokeWidth="1.6" fill="none" />
        <circle cx="104" cy="24" r="14" fill="none" stroke="#4AA886" strokeWidth="1.5" />
      </g>
      {/* queue */}
      <g className="chonk-tail">
        <path d="M100 84 Q114 88 116 78" stroke="#FF8205" strokeWidth="7" fill="none" strokeLinecap="round" />
      </g>
      {/* corps sur le dos */}
      <ellipse cx="62" cy="80" rx="34" ry="15" fill="#FF8205" />
      <ellipse cx="62" cy="76" rx="26" ry="10" fill="#FFD8A8" />
      {/* tête couchée sur le côté */}
      <g className="chonk-head">
        <circle cx="28" cy="70" r="17" fill="#FF8205" />
        <path d="M16 60 L10 46 L24 54 Z" fill="#FF8205" />
        <path d="M38 56 L44 44 L46 58 Z" fill="#FF8205" />
        <path d="M18 58 L14 49 L23 54 Z" fill="#E10500" />
        <g className="chonk-eyes">
          <circle cx="22" cy="68" r="2.8" fill="#262882" />
          <circle cx="34" cy="66" r="2.8" fill="#262882" />
        </g>
        <path d="M25 75 Q28 78 31 75" stroke="#262882" strokeWidth="1.8" fill="none" strokeLinecap="round" />
        <path d="M12 72 L4 70 M13 76 L5 78 M42 70 L50 68" stroke="#FFD8B0" strokeWidth="1.4" strokeLinecap="round" />
      </g>
      {/* pattes en l'air qui battent la pelote (alternées) */}
      <g className="chonk-paws">
        <rect x="52" y="52" width="9" height="20" rx="4.5" fill="#FFAF00" />
        <rect x="64" y="50" width="9" height="22" rx="4.5" fill="#FF8205" />
      </g>
      <g className="chonk-paws-alt">
        <rect x="76" y="50" width="9" height="22" rx="4.5" fill="#FFAF00" />
        <rect x="88" y="52" width="9" height="20" rx="4.5" fill="#FF8205" />
      </g>
      {/* pattes arrière */}
      <ellipse cx="46" cy="92" rx="8" ry="4" fill="#E8730A" />
      <ellipse cx="80" cy="92" rx="8" ry="4" fill="#E8730A" />
    </svg>
  );
}

/* ---------- Aperçu du rapport (données fictives) ---------- */

// Rapport de démonstration inspiré du module Zei « Énergie » (ESRS E1) : sert d'aperçu riche
// quand aucun JSON n'a encore été généré (mode CSS seul ou phase 1 du mode combiné).
const DEMO_REPORT = {
  time: 1762500000000,
  version: "2.30.5",
  blocks: [
    { type: "header", data: { text: "Rapport de durabilité 2026 — Module Énergie (démonstration)", level: 1 } },
    { id: "demoToc", type: "table_of_content", data: { tableOfContent: { title: "Sommaire", level: 4 } } },
    { type: "pageBreak", data: {} },
    { type: "pageBreak", data: {} },
    { type: "header", data: { text: "ESRS E1 — Changement climatique", level: 2 } },
    { type: "text_indicators", data: { organizationId: 49, networkId: 727, locale: "fr", textIndicators: { indicators: [{ type: "LastValue", indicatorId: 48261 }] } } },
    { type: "pageBreak", data: {} },
    { type: "header", data: { text: "Non renouvelable", level: 2 } },
    { type: "header", data: { text: "Électricité", level: 3 } },
    { type: "chart", data: { organizationId: 49, networkId: 727, locale: "fr", chart: { chartType: "line", xAxis: { label: "date", type: "Exercice", relativeStart: { minusX: 6 }, relativeEnd: { minusX: 1 } }, indicators: [{ type: "IndicatorValue", indicatorId: 48228 }, { type: "IndicatorValue", indicatorId: 48229 }] } } },
    { type: "table", id: "demoT1", data: { organizationId: 49, locale: "fr", networkId: 727, table: { columns: [ { type: "IndicatorName", label: "Indicator" }, { type: "LastValue", label: "2026" }, { type: "YearXValue", label: "2025", year: 2025 }, { type: "Progression", progression: { type: "percent", column1: { type: "ExerciceXValue", exerciceId: 2854 }, column2: { type: "LastValue" } } } ], indicatorIds: ["48228", "48229", "48236", "48264"] } } },
    { type: "header", data: { text: "Pétroles et dérivés énergétiques du pétrole", level: 3 } },
    { type: "table", id: "demoT2", data: { organizationId: 49, locale: "fr", networkId: 727, table: { columns: [ { type: "IndicatorName", label: "Indicator" }, { type: "LastValue", label: "2026" }, { type: "YearXValue", label: "2025", year: 2025 }, { type: "Progression", progression: { type: "percent", column1: { type: "ExerciceXValue", exerciceId: 2854 }, column2: { type: "LastValue" } } } ], indicatorIds: ["48265", "48266", "48268", "48270", "48269", "48267"] } } },
    { type: "header", data: { text: "Charbon", level: 3 } },
    { type: "table", id: "demoT3", data: { organizationId: 49, locale: "fr", networkId: 727, table: { columns: [ { type: "IndicatorName", label: "Indicator" }, { type: "LastValue", label: "2026" }, { type: "YearXValue", label: "2025", year: 2025 }, { type: "Progression", progression: { type: "percent", column1: { type: "ExerciceXValue", exerciceId: 2854 }, column2: { type: "LastValue" } } } ], indicatorIds: ["48231"] } } },
    { type: "header", data: { text: "Gaz fossile & Biogaz", level: 3 } },
    { type: "chart", data: { organizationId: 49, networkId: 727, locale: "fr", chart: { chartType: "line", xAxis: { label: "date", type: "Exercice", relativeStart: { minusX: 6 }, relativeEnd: { minusX: 1 } }, indicators: [{ type: "IndicatorValue", indicatorId: 48250 }] } } },
    { type: "header", data: { text: "Nucléaire", level: 3 } },
    { type: "table", id: "demoT4", data: { organizationId: 49, locale: "fr", networkId: 727, table: { columns: [ { type: "IndicatorName", label: "Indicator" }, { type: "LastValue", label: "2026" }, { type: "YearXValue", label: "2025", year: 2025 }, { type: "Progression", progression: { type: "percent", column1: { type: "ExerciceXValue", exerciceId: 2854 }, column2: { type: "LastValue" } } } ], indicatorIds: ["48253", "48237"] } } },
    { type: "header", data: { text: "Sous-total non renouvelable", level: 3 } },
    { type: "chart", data: { organizationId: 49, networkId: 727, locale: "fr", chart: { chartType: "line", xAxis: { label: "date", type: "Exercice", relativeStart: { minusX: 6 }, relativeEnd: { minusX: 1 } }, indicators: [{ type: "IndicatorValue", indicatorId: 48242 }, { type: "IndicatorValue", indicatorId: 48241 }] } } },
    { type: "pageBreak", data: {} },
    { type: "header", data: { text: "Renouvelable", level: 2 } },
    { type: "header", data: { text: "Énergie renouvelable autoproduite", level: 3 } },
    { type: "chart", data: { organizationId: 49, networkId: 727, locale: "fr", chart: { chartType: "line", xAxis: { label: "date", type: "Exercice", relativeStart: { minusX: 6 }, relativeEnd: { minusX: 1 } }, indicators: [{ type: "IndicatorValue", indicatorId: 48249 }] } } },
    { type: "header", data: { text: "Réseaux de chaleur et de froid / Vapeur", level: 3 } },
    { type: "table", id: "demoT5", data: { organizationId: 49, locale: "fr", networkId: 727, table: { columns: [ { type: "IndicatorName", label: "Indicator" }, { type: "LastValue", label: "2026" }, { type: "YearXValue", label: "2025", year: 2025 }, { type: "Progression", progression: { type: "percent", column1: { type: "ExerciceXValue", exerciceId: 2854 }, column2: { type: "LastValue" } } } ], indicatorIds: ["48244", "48245", "48246", "48243"] } } },
    { type: "pageBreak", data: {} },
    { type: "header", data: { text: "Total", level: 2 } },
    { type: "header", data: { text: "Consommation totale d'énergie", level: 3 } },
    { type: "chart", data: { organizationId: 49, networkId: 727, locale: "fr", chart: { chartType: "line", xAxis: { label: "date", type: "Exercice", relativeStart: { minusX: 6 }, relativeEnd: { minusX: 1 } }, indicators: [{ type: "IndicatorValue", indicatorId: 48230 }, { type: "IndicatorValue", indicatorId: 48250 }, { type: "IndicatorValue", indicatorId: 48253 }] } } },
    { type: "table", id: "demoT6", data: { organizationId: 49, locale: "fr", networkId: 727, table: { columns: [ { type: "IndicatorName", label: "Indicator" }, { type: "LastValue", label: "2026" }, { type: "YearXValue", label: "2025", year: 2025 }, { type: "Progression", progression: { type: "percent", column1: { type: "ExerciceXValue", exerciceId: 2854 }, column2: { type: "LastValue" } } } ], indicatorIds: ["48230", "48250", "48253", "48255", "48256"] } } },
  ],
};


const DEFAULT_CSS = `:root{--primary:#262882;--secondary:#3c3c3b;--tertiary:#58b896;--fourth:rgba(88,184,150,0.18);}
body{font-family:'Poppins',Arial,sans-serif;font-size:14px;color:var(--secondary);padding:24px;}
h1{color:var(--primary);font-size:32px;font-weight:700;margin-bottom:16px;}
h2{color:var(--primary);font-size:24px;font-weight:600;margin-top:24px;margin-bottom:12px;padding-bottom:6px;border-bottom:3px solid var(--tertiary);}
h3{color:var(--secondary);font-size:20px;font-weight:600;margin-top:14px;margin-bottom:10px;}
h4{color:var(--secondary);font-size:14px;font-weight:500;margin-top:10px;}
a{color:var(--primary);text-decoration:none;} a:hover{text-decoration:underline;}
table{background-color:var(--fourth);font-size:small;width:100%;table-layout:fixed;border-collapse:collapse;}
thead{background-color:var(--primary);} thead tr th, thead tr th *{color:#fff;font-weight:600;}
tbody tr td{padding:6px 8px;border-bottom:1px solid rgba(60,60,59,0.15);} tbody tr:nth-child(even){background-color:rgba(255,255,255,0.35);}
.editor-kpi div div{border-radius:12px;padding:10px;background-color:var(--fourth);}`;

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
  const chart = data?.chart ?? {};
  const indicators: any[] = chart.indicators ?? [];
  const isBar = chart.chartType === "bar";
  const width = 640;
  const height = 240;
  const pad = 32;
  const yearN = new Date().getFullYear();
  const years: number[] = [];
  for (let i = 5; i >= 0; i--) years.push(yearN - i);
  const colors = ["#262882", "#4347e8", "#58b896"];
  const xFor = (i: number) => pad + (i * (width - 2 * pad)) / Math.max(years.length - 1, 1);
  let marks = "";
  if (isBar) {
    const groupW = (width - 2 * pad) / years.length;
    const barW = Math.max(groupW / (indicators.length + 1), 4);
    indicators.forEach((ind, idx) => {
      const base = fakeValue(String(ind.indicatorId));
      years.forEach((_y, i) => {
        const v = (base + i * 37) % 180;
        marks += `<rect x="${xFor(i) + idx * barW}" y="${height - pad - v}" width="${barW - 1}" height="${v}" fill="${colors[idx % 3]}" />`;
      });
    });
  } else {
    indicators.forEach((ind, idx) => {
      const base = fakeValue(String(ind.indicatorId));
      const pts = years.map((_y, i) => ({ x: xFor(i), y: height - pad - ((base + i * 37) % 180) }));
      marks += `<polyline fill="none" stroke="${colors[idx % 3]}" stroke-width="2.5" points="${pts.map((p) => `${p.x},${p.y}`).join(" ")}" />`;
    });
  }
  const xLabels = years
    .map((y, i) => `<text x="${xFor(i)}" y="${height - 8}" font-size="11" text-anchor="middle" fill="#3c3c3b">${y}</text>`)
    .join("");
  const legend = indicators.map((ind, idx) => `<span style="margin-right:12px;color:${colors[idx % 3]}">● indicateur ${esc(ind.indicatorId)}</span>`).join("");
  return `<svg viewBox="0 0 ${width} ${height}" style="width:100%;background:rgba(88,184,150,0.08);border-radius:12px">${marks}${xLabels}<text x="${pad}" y="16" font-size="11" fill="#3c3c3b">${legend}</text></svg>`;
}

function renderTableOfContent(blocks: any[]): string {
  const titles = blocks
    .filter((b) => b.type === "header" && Number(b.data?.level) <= 2)
    .map((b) => `<li style="margin:2px 0">${esc(b.data?.text)}</li>`)
    .join("");
  return `<div style="border:1px solid rgba(60,60,59,0.2);border-radius:12px;padding:12px 16px;background:rgba(88,184,150,0.08)"><h4 style="margin:0 0 8px;font-size:16px">Sommaire</h4><ul style="margin:0;padding-left:18px;font-size:13px">${titles}</ul></div>`;
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
  const blocks: any[] = Array.isArray(reportJson?.blocks) && reportJson.blocks.length > 0 ? reportJson.blocks : DEMO_REPORT.blocks;
  // Chaque pageBreak ouvre une nouvelle "page A4" (le rapport se téléchargerait en PDF depuis Zei).
  const pages: string[] = [""];
  for (const b of blocks) {
    if (b.type === "pageBreak") {
      pages.push("");
      continue;
    }
    let html = "";
    if (b.type === "header") {
      const level = Math.min(Math.max(Number(b.data?.level) || 2, 1), 4);
      html = `<h${level}>${esc(b.data?.text)}</h${level}>`;
    } else if (b.type === "table_of_content") {
      html = renderTableOfContent(blocks);
    } else if (b.type === "chart") {
      html = renderChart(b.data);
    } else if (b.type === "table") {
      html = renderTable(b.data);
    } else if (b.type === "text_indicators") {
      html = `<p>Donnée narrative de démonstration pour l'indicateur ${esc(b.data?.textIndicators?.indicators?.[0]?.indicatorId ?? "")} — contenu généré à partir de la matrice réseau du client.</p>`;
    }
    pages[pages.length - 1] += "\n" + html;
  }
  return pages.map((html) => `<div class="page">${html}</div>`).join("");
}

function buildPreviewSrcDoc(report: Report, zoom = 1): string {
  const css = report.css ?? DEFAULT_CSS;
  // Habillage "page A4" de l'aperçu : marges latérales dans la page, feuilles séparées au scroll.
  const pageChrome = `body{background:#d7dae6;padding:24px 0;}
.page{background:#fff;width:794px;min-height:1123px;margin:0 auto 28px;padding:64px 56px;box-shadow:0 6px 18px rgba(11,13,46,.35);box-sizing:border-box;}`;
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style><style>${pageChrome}</style><style>body{zoom:${zoom}}</style></head><body>${renderBlocks(report.reportJson)}</body></html>`;
}


