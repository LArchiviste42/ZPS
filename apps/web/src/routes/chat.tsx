import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

type ChatMessage = { role: "user" | "assistant"; content: string };

export const Route = createFileRoute("/chat")({
  staticData: { landing: false },
  component: ChatPage,
});

async function postChat(history: ChatMessage[]): Promise<string> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: history }),
  });
  const data = (await res.json()) as { reply?: string; detail?: unknown };
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "The request failed.");
  }
  return data.reply ?? "";
}

/** The Zei emblem: mint circle with the white leaf mark, as in the 2022 charte. */
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

function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");

  const send = useMutation({
    mutationFn: (history: ChatMessage[]) => postChat(history),
    onSuccess: (reply) => {
      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || send.isPending) return;
    const history = [...messages, { role: "user" as const, content: text }];
    setMessages(history);
    setInput("");
    send.mutate(history);
  };

  return (
    <main className="flex min-h-full flex-col bg-white">
      <header className="flex items-center gap-3 bg-zei-navy px-6 py-4">
        <ZeiMark className="h-8 w-8" />
        <div className="leading-tight">
          <p className="text-lg font-extrabold lowercase tracking-tight text-white">zei · chat</p>
          <p className="text-xs text-white/70">mistral-large-4, via /api/chat</p>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-3 px-6 py-6">
        <div className="flex flex-1 flex-col gap-3">
          {messages.length === 0 && (
            <p className="mt-8 text-center text-sm text-zei-ink/60">
              Tapez un message ci-dessous pour démarrer la conversation.
            </p>
          )}
          {messages.map((message, index) => (
            <div
              key={index}
              className={
                message.role === "user"
                  ? "self-end rounded-2xl rounded-br-sm bg-zei-indigo px-4 py-2.5 text-sm text-white"
                  : "self-start rounded-2xl rounded-bl-sm bg-zei-mint/15 px-4 py-2.5 text-sm text-zei-ink"
              }
            >
              <span className="whitespace-pre-wrap">{message.content}</span>
            </div>
          ))}
          {send.isPending && (
            <div className="self-start rounded-2xl rounded-bl-sm bg-zei-mint/15 px-4 py-2.5 text-sm text-zei-ink/60">
              <span className="animate-pulse">zei réfléchit…</span>
            </div>
          )}
        </div>

        {send.isError && (
          <p className="text-sm font-semibold text-red-600">{send.error.message}</p>
        )}

        <form onSubmit={submit} className="flex gap-2 pb-2">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Tapez un message…"
            className="flex-1 rounded-full border border-zei-ink/15 bg-white px-4 py-2.5 text-sm text-zei-ink outline-none placeholder:text-zei-ink/40 focus:border-zei-mint focus:ring-2 focus:ring-zei-mint/30"
          />
          <button
            type="submit"
            disabled={send.isPending || input.trim() === ""}
            className="rounded-full bg-zei-indigo px-5 py-2.5 text-sm font-bold text-white transition hover:bg-zei-navy disabled:opacity-50"
          >
            {send.isPending ? "Envoi…" : "Envoyer"}
          </button>
        </form>
      </div>
    </main>
  );
}
