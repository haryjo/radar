"use client";

import clsx from "clsx";
import { AlertTriangle, Check, Cpu, Database, Flag, Search, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { streamSSE, type RunEvent, type RunStats } from "@/lib/api";
import { compact } from "@/lib/format";
import { CompareBar, Donut, Funnel } from "./charts";
import { RadarIllustration } from "./illustrations";

const KINDS: Record<string, { icon: typeof Check; ring: string }> = {
  start: { icon: Flag, ring: "bg-accent-soft text-accent" },
  step: { icon: Check, ring: "bg-success/12 text-success" },
  cache: { icon: Database, ring: "bg-chart-2/15 text-chart-2" },
  guardrail: { icon: ShieldCheck, ring: "bg-accent-soft text-accent" },
  warning: { icon: AlertTriangle, ring: "bg-warning/15 text-warning" },
  llm: { icon: Cpu, ring: "bg-chart-3/20 text-warning" },
  search: { icon: Search, ring: "bg-accent-soft text-accent" },
  error: { icon: X, ring: "bg-danger/12 text-danger" },
};

export interface LiveOffer {
  kept: boolean;
  offer: { title: string; company: string; location: string; score: number; url: string; source?: string; reasons?: string[] };
}

export interface ProgressState {
  stage: string;
  done: number;
  total: number;
  label: string;
}

/** Flux d'une exécution : historique, progression de l'étape en cours, offres notées en direct. */
export function useRunStream(runId: number, onEnd?: (status: string, stats?: RunStats) => void) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [offers, setOffers] = useState<LiveOffer[]>([]);
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setEvents([]);
    setOffers([]);
    setProgress(null);
    setDone(false);
    type AnyEvent = RunEvent & { type: string } & Partial<LiveOffer> & Partial<ProgressState>;
    streamSSE<AnyEvent>(
      `/api/runs/${runId}/stream`,
      (event) => {
        if (event.type === "end") {
          setDone(true);
          setProgress(null);
          onEnd?.(event.status ?? "", event.stats);
        } else if (event.type === "progress") {
          setProgress({ stage: event.stage ?? "", done: event.done ?? 0, total: event.total ?? 0, label: event.label ?? "" });
        } else if (event.type === "offer" && event.offer) {
          setOffers((prev) => [...prev, { kept: Boolean(event.kept), offer: event.offer! }]);
        } else {
          setEvents((prev) => [...prev, event]);
        }
      },
      { signal: controller.signal },
    ).catch(() => setDone(true));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  return { events, offers, progress, done };
}

export const STAGES = [
  { id: "plan", label: "Préparation" },
  { id: "search", label: "Recherche" },
  { id: "triage", label: "Tri" },
  { id: "read", label: "Lecture" },
  { id: "extract", label: "Extraction" },
  { id: "score", label: "Notation" },
  { id: "save", label: "Enregistrement" },
];

/** Frise des étapes + barre de l'étape en cours : on voit toujours ce que fait l'agent. */
export function StageStepper({ progress, done }: { progress: ProgressState | null; done: boolean }) {
  const current = progress ? STAGES.findIndex((s) => s.id === progress.stage) : done ? STAGES.length : 0;
  const ratio = progress && progress.total ? progress.done / progress.total : 0;
  return (
    <div>
      <ol className="flex items-center gap-1.5">
        {STAGES.map((stage, i) => {
          const state = done || i < current ? "done" : i === current ? "active" : "todo";
          return (
            <li key={stage.id} className="flex min-w-0 flex-1 flex-col gap-1.5">
              <div className="h-1.5 overflow-hidden rounded-full bg-ink/[0.07]">
                <div
                  className={clsx("h-full rounded-full transition-all duration-500", state === "done" ? "bg-success" : "bg-accent")}
                  style={{ width: state === "done" ? "100%" : state === "active" ? `${Math.max(ratio * 100, 8)}%` : "0%" }}
                />
              </div>
              <span className={clsx("truncate text-[11px]", state === "active" ? "font-medium text-ink" : "text-muted")}>
                {stage.label}
              </span>
            </li>
          );
        })}
      </ol>
      {progress && (
        <p className="mt-3 flex items-center gap-2 text-sm">
          <span className="relative flex size-2">
            <span className="absolute inset-0 animate-ping rounded-full bg-accent opacity-60" />
            <span className="relative size-2 rounded-full bg-accent" />
          </span>
          <span className="font-medium">{STAGES.find((s) => s.id === progress.stage)?.label}</span>
          {progress.total > 1 && <span className="tabular-nums text-muted">{progress.done}/{progress.total}</span>}
          <span className="truncate text-muted">{progress.label}</span>
        </p>
      )}
    </div>
  );
}

/** Offres notées pendant l'exécution, affichées dès qu'elles arrivent. */
export function LiveOffers({ offers }: { offers: LiveOffer[] }) {
  if (offers.length === 0) return null;
  const sorted = [...offers].sort((a, b) => Number(b.kept) - Number(a.kept) || b.offer.score - a.offer.score);
  return (
    <ul className="space-y-2">
      {sorted.map(({ offer, kept }) => (
        <li key={offer.url} className={clsx("animate-fade-in flex items-center gap-3 rounded-xl border border-line bg-surface p-3", !kept && "opacity-55")}>
          <span
            className={clsx(
              "grid size-9 shrink-0 place-items-center rounded-lg text-[13px] font-semibold tabular-nums",
              kept ? "bg-success/12 text-success" : "bg-ink/[0.06] text-muted",
            )}
          >
            {offer.score}
          </span>
          <div className="min-w-0 flex-1">
            <a href={offer.url} target="_blank" rel="noreferrer" className="block truncate text-sm font-medium hover:text-accent">{offer.title}</a>
            <p className="truncate text-[12px] text-muted">{[offer.company, offer.location].filter(Boolean).join(" · ")}</p>
          </div>
          {offer.source && offer.source !== "web" && <span className="shrink-0 rounded-md bg-raised px-1.5 py-0.5 text-[10px] text-muted">{offer.source}</span>}
        </li>
      ))}
    </ul>
  );
}

/** Journal des étapes. */
export function Timeline({ events, running }: { events: RunEvent[]; running: boolean }) {
  return (
    <div>
      {running && events.length === 0 && (
        <div className="mb-4 flex items-center gap-3 rounded-xl bg-accent-soft/60 p-3">
          <RadarIllustration className="size-10" />
          <p className="text-sm text-muted">Connexion à l'agent…</p>
        </div>
      )}
      <ol className="relative space-y-3">
        <span className="absolute bottom-2 left-[11px] top-2 w-px bg-line" />
        {events.map((event, i) => {
          const { icon: Icon, ring } = KINDS[event.kind ?? "step"] ?? KINDS.step;
          const queries = event.data?.queries as string[] | undefined;
          return (
            <li key={i} className="animate-fade-in relative flex gap-3 text-sm">
              <span className={clsx("relative z-10 grid size-6 shrink-0 place-items-center rounded-full ring-4 ring-surface", ring)}>
                <Icon className="size-3" />
              </span>
              <div className="min-w-0 pt-0.5">
                <p className="leading-snug">{event.message}</p>
                {queries && queries.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {queries.map((q) => (
                      <code key={q} className="rounded-md bg-raised px-1.5 py-0.5 font-mono text-[11px] text-muted">{q}</code>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Indicateurs visuels d'une exécution : entonnoir, cache, compression, chiffres clés. */
export function runVisuals(stats: RunStats) {
  const tokens = (stats.tokens_in ?? 0) + (stats.tokens_out ?? 0);
  const cacheHits = (stats.llm_cache_hits ?? 0) + (stats.page_cache_hits ?? 0) + (stats.search_cache_hits ?? 0) + (stats.semantic_cache_hits ?? 0);
  const lookups = cacheHits + (stats.llm_calls ?? 0) + (stats.pages_fetched ?? 0) + (stats.web_searches ?? 0);
  const unique = stats.unique_results ?? stats.search_results ?? 0;
  const pagesRead = (stats.pages_fetched ?? 0) + (stats.page_cache_hits ?? 0);

  return {
    funnel: (
      <Funnel
        steps={[
          { label: "Résultats uniques", value: unique },
          { label: "Jamais vus", value: Math.max(unique - (stats.already_seen ?? 0), 0) },
          { label: "Retenus après tri", value: stats.to_analyze ?? pagesRead },
          { label: "Offres analysées", value: stats.offers_extracted ?? 0 },
          { label: "Offres retenues", value: stats.offers_saved ?? 0 },
        ]}
      />
    ),
    cache: (
      <div className="flex items-center gap-5">
        <Donut value={lookups ? cacheHits / lookups : 0} size={96}>
          <div>
            <p className="text-lg font-semibold tabular-nums">{lookups ? Math.round((cacheHits / lookups) * 100) : 0} %</p>
            <p className="text-[10px] text-muted">en cache</p>
          </div>
        </Donut>
        <dl className="space-y-1.5 text-[13px]">
          {[
            ["Réponses LLM", stats.llm_cache_hits ?? 0],
            ["Pages", stats.page_cache_hits ?? 0],
            ["Recherches", (stats.search_cache_hits ?? 0) + (stats.semantic_cache_hits ?? 0)],
          ].map(([label, value]) => (
            <div key={label as string} className="flex gap-3">
              <dt className="w-24 text-muted">{label}</dt>
              <dd className="font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    ),
    compression: (
      <CompareBar
        before={stats.html_chars ?? 0}
        after={stats.sent_chars ?? 0}
        beforeLabel="HTML téléchargé"
        afterLabel="Envoyé au LLM"
        format={(v) => `${compact(v)} car.`}
      />
    ),
    sources: Object.entries(stats)
      .filter(([key]) => key.startsWith("source:"))
      .map(([key, value]) => ({ name: key.slice(7), count: value ?? 0 })),
    models: Object.entries(stats)
      .filter(([key]) => key.startsWith("model:"))
      .map(([key, value]) => ({ name: key.slice(6), calls: value ?? 0 }))
      .sort((a, b) => b.calls - a.calls),
    figures: [
      ["Tokens", compact(tokens)],
      ["Offres proches", stats.offers_near ?? 0],
      ["Offres lues sans LLM", stats.direct_offers ?? 0],
      ["Durée", `${stats.duration_s ?? 0} s`],
    ] as [string, string | number][],
  };
}
