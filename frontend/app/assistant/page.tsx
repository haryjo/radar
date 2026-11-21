"use client";

import clsx from "clsx";
import { ArrowUp, ArrowUpRight, Bookmark, BookmarkCheck, Radar, Sparkles, Target, Wrench, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ChatIllustration } from "@/components/illustrations";
import { Markdown } from "@/components/markdown";
import { PageHeader } from "@/components/ui";
import { api, streamSSE, type ExpressOffer, type SearchLogEntry } from "@/lib/api";
import { useToast } from "@/components/toast";

interface Message {
  role: "user" | "assistant";
  content: string;
  tools: { name: string; detail: string }[];
  error?: string;
  express?: { offers: ExpressOffer[]; sources: SearchLogEntry[]; total: number; duration: number };
}

type ChatEvent =
  | { type: "token"; content: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string; preview: string }
  | { type: "error"; message: string }
  | { type: "offers"; offers: ExpressOffer[]; sources: SearchLogEntry[]; total_found: number; duration_s: number }
  | { type: "done" };

const SUGGESTIONS = [
  { icon: Zap, text: "Cherche maintenant des offres de développeur Python à Antananarivo ou en télétravail" },
  { icon: Sparkles, text: "Quelles sont mes meilleures nouvelles offres ?" },
  { icon: Target, text: "Quelles compétences reviennent le plus dans les offres retenues ?" },
];

export default function AssistantPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [threadId] = useState(() => `web-${Math.random().toString(36).slice(2, 10)}`);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function patchLast(update: (m: Message) => Message) {
    setMessages((prev) => [...prev.slice(0, -1), update(prev[prev.length - 1])]);
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "user", content: text, tools: [] }, { role: "assistant", content: "", tools: [] }]);
    try {
      await streamSSE<ChatEvent>("/api/chat", (event) => {
        if (event.type === "token") patchLast((m) => ({ ...m, content: (m.content + event.content).replace(/^\s+/, "") }));
        if (event.type === "tool_call") patchLast((m) => ({ ...m, tools: [...m.tools, { name: event.name, detail: Object.values(event.args ?? {}).join(", ") }] }));
        if (event.type === "error") patchLast((m) => ({ ...m, error: event.message }));
        if (event.type === "offers") {
          patchLast((m) => ({ ...m, express: { offers: event.offers, sources: event.sources, total: event.total_found, duration: event.duration_s } }));
        }
      }, { method: "POST", body: JSON.stringify({ message: text, thread_id: threadId }) });
    } catch (e) {
      patchLast((m) => ({ ...m, error: (e as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-8rem)] max-w-3xl flex-col md:h-[calc(100dvh-5rem)]">
      <PageHeader eyebrow="Agent" title="Assistant" description="L'agent choisit lui-même ses outils : recherche web, lecture de page, profil et serveur MCP." />

      <div className="scroll-thin -mx-2 flex-1 space-y-6 overflow-y-auto px-2 pb-6">
        {messages.length === 0 && (
          <div className="flex flex-col items-center pt-6 text-center">
            <ChatIllustration className="w-36" />
            <p className="mt-4 font-medium">Que veux-tu savoir sur tes offres ?</p>
            <div className="mt-6 grid w-full gap-2 sm:grid-cols-3">
              {SUGGESTIONS.map(({ icon: Icon, text }) => (
                <button
                  key={text}
                  onClick={() => send(text)}
                  className="group rounded-2xl border border-line bg-surface p-4 text-left text-[13px] text-muted shadow-card transition-all hover:-translate-y-0.5 hover:border-ink/15 hover:text-ink"
                >
                  <Icon className="mb-2 size-4 text-accent" />
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={clsx("animate-fade-in flex gap-3", m.role === "user" && "justify-end")}>
            {m.role === "assistant" && (
              <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-ink text-canvas"><Radar className="size-3.5" /></span>
            )}
            {m.role === "user" ? (
              <p className="max-w-[80%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm text-canvas">{m.content}</p>
            ) : (
              <div className="min-w-0 max-w-[90%] space-y-2 pt-0.5">
                {m.tools.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.tools.map((t, j) => (
                      <span key={j} className="inline-flex max-w-full items-center gap-1.5 truncate rounded-full border border-line bg-surface px-2.5 py-1 font-mono text-[11px] text-muted">
                        <Wrench className="size-3 shrink-0 text-accent" />{t.name}{t.detail && <span className="truncate opacity-70">· {t.detail.slice(0, 48)}</span>}
                      </span>
                    ))}
                  </div>
                )}
                {m.express && <ExpressResults {...m.express} />}
                {m.content ? (
                  <Markdown>{m.content}</Markdown>
                ) : (
                  busy && i === messages.length - 1 && !m.error && (
                    <div className="flex gap-1 py-2">
                      {[0, 1, 2].map((d) => <span key={d} className="size-1.5 animate-bounce rounded-full bg-muted" style={{ animationDelay: `${d * 0.15}s` }} />)}
                    </div>
                  )
                )}
                {m.error && <p className="rounded-lg bg-danger/8 px-3 py-2 text-sm text-danger">{m.error}</p>}
              </div>
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="relative">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
          rows={1}
          placeholder="Pose une question sur tes offres…"
          className="block w-full resize-none rounded-2xl border border-line bg-surface py-3.5 pl-4 pr-14 text-sm shadow-card outline-none transition-colors focus:border-accent"
        />
        <button type="submit" disabled={busy || !input.trim()} className="absolute bottom-2.5 right-2.5 grid size-8 place-items-center rounded-xl bg-ink text-canvas transition-opacity disabled:opacity-25">
          <ArrowUp className="size-4" />
        </button>
      </form>
    </div>
  );
}


const SOURCE_LABEL: Record<string, string> = {
  web: "Web", jsonld: "Web", jobicy: "Jobicy", arbeitnow: "Arbeitnow", remoteok: "Remote OK", himalayas: "Himalayas",
};

/** Résultats de la recherche express : cartes notées, sources consultées, sauvegarde en un clic. */
function ExpressResults({ offers, sources, total, duration }: { offers: ExpressOffer[]; sources: SearchLogEntry[]; total: number; duration: number }) {
  const toast = useToast();
  const [saved, setSaved] = useState<Record<string, boolean>>({});

  async function save(offer: ExpressOffer) {
    try {
      await api("/api/offers", {
        method: "POST",
        body: JSON.stringify({ ...offer, reasons: offer.reason ? [offer.reason] : [], source: offer.source, query: "recherche express" }),
      });
      setSaved((s) => ({ ...s, [offer.url]: true }));
      toast("Offre ajoutée à tes offres (veille « assistant »).");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-[12px] text-muted">
        {total} résultats en {duration} s · sources :{" "}
        {sources.map((src, i) => (
          <span key={src.source} className={src.error ? "text-danger" : undefined} title={src.error ?? undefined}>
            {i > 0 && ", "}{src.label} ({src.error ? "échec" : src.count})
          </span>
        ))}
      </p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {offers.slice(0, 8).map((o) => (
          <li key={o.url} className="flex flex-col rounded-xl border border-line bg-surface p-3">
            <div className="flex items-start gap-2.5">
              <span className={`grid size-8 shrink-0 place-items-center rounded-lg text-[12px] font-semibold tabular-nums ${o.score >= 70 ? "bg-success/12 text-success" : o.score >= 50 ? "bg-accent-soft text-accent" : "bg-ink/[0.06] text-muted"}`}>
                {o.score}
              </span>
              <div className="min-w-0 flex-1">
                <p className="line-clamp-2 text-[13px] font-medium leading-snug">{o.title}</p>
                <p className="truncate text-[11px] text-muted">{[o.company, o.location, SOURCE_LABEL[o.source] ?? o.source].filter(Boolean).join(" · ")}</p>
              </div>
            </div>
            {o.reason && <p className="mt-2 line-clamp-2 text-[12px] text-ink/75">{o.reason}</p>}
            <div className="mt-auto flex gap-1.5 pt-2.5">
              <a href={o.url} target="_blank" rel="noreferrer" className="inline-flex h-7 items-center gap-1 rounded-md bg-accent-soft px-2 text-[12px] font-medium text-accent">
                <ArrowUpRight className="size-3.5" />Ouvrir
              </a>
              <button onClick={() => save(o)} disabled={saved[o.url]} className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] text-muted hover:bg-ink/5 hover:text-ink disabled:text-success">
                {saved[o.url] ? <BookmarkCheck className="size-3.5" /> : <Bookmark className="size-3.5" />}
                {saved[o.url] ? "Gardée" : "Garder"}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
