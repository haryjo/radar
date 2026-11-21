"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BarChart } from "@/components/charts";
import { RadarIllustration } from "@/components/illustrations";
import { Card, CardTitle, Empty, ErrorNote, PageHeader, RunStatusBadge, Segmented, Skeleton } from "@/components/ui";
import { api, type Run } from "@/lib/api";
import { compact, dateTime } from "@/lib/format";

type Metric = "tokens" | "offers" | "seen";

function tokensOf(run: Run) {
  return (run.stats.tokens_in ?? 0) + (run.stats.tokens_out ?? 0);
}


export default function HistoryPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [metric, setMetric] = useState<Metric>("tokens");

  useEffect(() => {
    const load = () => api<Run[]>("/api/runs?limit=100").then(setRuns).catch((e: Error) => setError(e.message));
    load();
    const timer = setInterval(load, 10_000);
    return () => clearInterval(timer);
  }, []);

  const recent = (runs ?? []).filter((r) => r.status !== "running").slice(0, 24).reverse();
  const value = (r: Run) => (metric === "tokens" ? tokensOf(r) : metric === "offers" ? r.stats.offers_saved ?? 0 : r.stats.already_seen ?? 0);

  return (
    <>
      <PageHeader eyebrow="Suivi" title="Historique" description="Chaque exécution d'une veille, avec ses mesures de coût et d'optimisation." />
      {error && <ErrorNote message={error} />}
      {!runs && !error && <Skeleton className="h-80" />}
      {runs?.length === 0 && (
        <Empty illustration={<RadarIllustration className="size-28" active={false} />} title="Aucune exécution pour l'instant">
          Lance une veille pour voir apparaître ses mesures ici.
        </Empty>
      )}

      {runs && runs.length > 0 && (
        <>
          <Card className="mb-4 p-5">
            <CardTitle
              aside={
                <Segmented<Metric>
                  value={metric}
                  onChange={setMetric}
                  options={[
                    { value: "tokens", label: "Tokens" },
                    { value: "offers", label: "Offres" },
                    { value: "seen", label: "Déjà vues" },
                  ]}
                />
              }
            >
              {recent.length} dernières exécutions
            </CardTitle>
            <BarChart
              data={recent.map((r) => ({ label: `#${r.id}`, value: value(r) }))}
              height={180}
              color={metric === "tokens" ? "var(--chart-1)" : "var(--chart-2)"}
              format={(v) => compact(v)}
              highlightLast
            />
          </Card>

          <Card className="overflow-hidden">
            <ul className="divide-y divide-line">
              {runs.map((run) => (
                <li key={run.id}>
                  <Link href={`/historique/${run.id}`} className="group flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-raised/60">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium group-hover:text-accent">{run.watch}</p>
                      <p className="text-[12px] text-muted">#{run.id} · {dateTime(run.started_at)} · {run.trigger}</p>
                    </div>
                    <div className="hidden gap-6 text-right text-[12px] text-muted sm:flex">
                      <span><span className="block text-sm font-medium text-ink tabular-nums">{run.stats.offers_saved ?? 0}</span>offres</span>
                      <span><span className="block text-sm font-medium text-ink tabular-nums">{compact(tokensOf(run))}</span>tokens</span>
                      <span><span className="block text-sm font-medium text-ink tabular-nums">{run.stats.already_seen ?? 0}</span>déjà vues</span>
                    </div>
                    <RunStatusBadge status={run.status} />
                    <ChevronRight className="size-4 text-muted" />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
