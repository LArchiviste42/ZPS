import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

type ChatMessage = { role: "user" | "assistant"; content: string };

export const Route = createFileRoute("/chat")({
  staticData: { landing: true },
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
    <main className="mx-auto flex min-h-full w-full max-w-2xl flex-col gap-4 p-8">
      <h1 className="text-3xl font-semibold">Mistral Chat</h1>
      <p className="text-sm opacity-70">mistral-small-latest, via the app's own /api/chat endpoint</p>

      <div className="flex flex-1 flex-col gap-2 overflow-y-auto rounded-lg border border-black/10 p-4 dark:border-white/10">
        {messages.length === 0 && (
          <p className="text-sm opacity-60">Type a message below to start the conversation.</p>
        )}
        {messages.map((message, index) => (
          <div
            key={index}
            className={
              message.role === "user"
                ? "self-end rounded-lg bg-orange-200 px-3 py-2 dark:bg-orange-900"
                : "self-start rounded-lg bg-black/5 px-3 py-2 dark:bg-white/10"
            }
          >
            <span className="whitespace-pre-wrap text-sm">{message.content}</span>
          </div>
        ))}
      </div>

      {send.isError && (
        <p className="text-sm text-red-600 dark:text-red-400">{send.error.message}</p>
      )}

      <form onSubmit={submit} className="flex gap-2">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Type a message..."
          className="flex-1 rounded-lg border border-black/20 px-3 py-2 text-sm dark:border-white/20"
        />
        <button
          type="submit"
          disabled={send.isPending || input.trim() === ""}
          className="rounded-lg bg-orange-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {send.isPending ? "Sending..." : "Send"}
        </button>
      </form>
    </main>
  );
}
