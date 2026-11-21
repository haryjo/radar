"use client";

import { ArrowLeft, ChevronDown, Info, Square } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Markdown } from "@/components/markdown";
import { LiveOffers, StageStepper, Timeline, runVisuals, useRunStream } from "@/components/run-timeline";
import { useToast } from "@/components/toast";
import { Button, Card, CardTitle, ErrorNote, PageHeader, RunStatusBadge, Skeleton } from "@/components/ui";
import { api, type Run, type SearchLogEntry } from "@/lib/api";
import { dateTime } from "@/lib/format";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const runId = Number(id);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const toast = useToast();

  const load = useCallback(() => {
    api<Run>(`/api/runs/${id}`).then(setRun).catch((e: Error) => setError(e.message));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const stream = useRunStream(runId, () => load());

  if (error) return <ErrorNote message={error} />;
  if (!run) return <Skeleton className="h-96" />;

  async function stop() {
    setStopping(true);
    try {
      await api(`/api/runs/${id}/cancel`, { method: "POST" });
      toast("Arrêt demandé : rien ne sera marqué comme vu.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setStopping(false);
    }
  }

  const finished = run.status !== "running" && stream.done;
  const visuals = runVisuals(run.stats);
  const later = run.stats.kept_for_later ?? 0;
  const keptLive = stream.offers.filter((o) => o.kept).length;
  const searches = (stream.events.find((e) => e.kind === "search")?.data?.searches ?? []) as SearchLogEntry[];

  return (
    <>
      <Link href="/historique" className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink">
        <ArrowLeft className="size-3.5" />Historique
      </Link>
      <PageHeader
        eyebrow={run.watch}
        title={`Exécution #${run.id}`}
        description={`${dateTime(run.started_at)} · déclenchement ${run.trigger}`}
        actions={
          <>
            {!finished && (
              <Button variant="danger" size="sm" onClick={stop} loading={stopping}><Square className="size-3.5" />Arrêter</Button>
            )}
            <RunStatusBadge status={finished ? run.status : "running"} />
          </>
        }
      />

      {/* Suivi en direct */}
      {!finished && (
        <Card className="mb-4 p-5">
          <StageStepper progress={stream.progress} done={false} />
          {stream.offers.length === 0 && (
            <p className="mt-4 text-[13px] text-muted">Les offres apparaîtront ici dès qu'elles seront notées. Tu peux quitter cette page : la veille continue en arrière-plan.</p>
          )}
          {stream.offers.length > 0 && (
            <div className="mt-5 border-t border-line pt-4">
              <CardTitle aside={<span className="text-[12px] text-muted">{keptLive} retenue{keptLive > 1 ? "s" : ""} sur {stream.offers.length}</span>}>
                Offres notées en direct
              </CardTitle>
              <LiveOffers offers={stream.offers} />
            </div>
          )}
        </Card>
      )}

      {run.error && run.status === "error" && <div className="mb-4"><ErrorNote message={run.error} /></div>}
      {finished && later > 0 && (
        <p className="mb-4 flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3.5 py-2.5 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-warning" />
          {later} élément{later > 1 ? "s" : ""} n'{later > 1 ? "ont" : "a"} pas pu être analysé{later > 1 ? "s" : ""} (erreur passagère ou limite atteinte) :
          nouvel essai à la prochaine exécution.
        </p>
      )}

      {finished && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          {visuals.figures.map(([label, value]) => (
            <Card key={label} className="px-4 py-3.5">
              <p className="text-[11px] text-muted">{label}</p>
              <p className="mt-1 text-xl font-semibold tracking-tight tabular-nums">{value}</p>
            </Card>
          ))}
        </div>
      )}

      <div className={finished ? "grid gap-4 lg:grid-cols-[360px_1fr]" : "grid gap-4"}>
        <Card className="h-fit p-5">
          <button onClick={() => setShowLog((v) => !v)} className="flex w-full items-center justify-between text-left lg:pointer-events-none">
            <span className="text-[13px] font-medium">Journal de l'agent</span>
            <ChevronDown className={`size-4 text-muted transition-transform lg:hidden ${showLog ? "rotate-180" : ""}`} />
          </button>
          <div className={`mt-4 ${showLog ? "" : "hidden lg:block"}`}>
            <Timeline events={stream.events} running={!finished} />
          </div>
        </Card>

        <div className="space-y-4">
          {finished && (
            <div className="grid gap-4 xl:grid-cols-2">
              <Card className="p-5">
                <CardTitle>Entonnoir de sélection</CardTitle>
                {visuals.funnel}
              </Card>
              <div className="grid gap-4">
                <Card className="p-5">
                  <CardTitle>Cache</CardTitle>
                  {visuals.cache}
                </Card>
                <Card className="p-5">
                  <CardTitle>Compression des pages</CardTitle>
                  {visuals.compression}
                </Card>
              </div>
              {(visuals.sources.length > 0 || visuals.models.length > 0) && (
                <Card className="p-5 xl:col-span-2">
                  <div className="grid gap-6 sm:grid-cols-2">
                    {visuals.sources.length > 0 && (
                      <div>
                        <CardTitle>Sources structurées</CardTitle>
                        <ul className="space-y-2 text-[13px]">
                          {visuals.sources.map((s) => (
                            <li key={s.name} className="flex justify-between gap-3">
                              <span className="capitalize">{s.name}</span>
                              <span className="tabular-nums text-muted">{s.count} offre{s.count > 1 ? "s" : ""}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {visuals.models.length > 0 && (
                      <div>
                        <CardTitle>Modèles utilisés</CardTitle>
                        <ul className="space-y-2 text-[13px]">
                          {visuals.models.map((m) => (
                            <li key={m.name} className="flex items-center justify-between gap-3">
                              <span className="truncate font-mono text-[12px]">{m.name}</span>
                              <span className="shrink-0 tabular-nums text-muted">{m.calls} appel{m.calls > 1 ? "s" : ""}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </Card>
              )}
            </div>
          )}
          {searches.length > 0 && (
            <Card className="overflow-hidden">
              <details className="group" open={searches.some((x) => x.error)}>
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-[13px] font-medium hover:bg-raised/50">
                  <span>
                    Détail des recherches · {searches.length} requête{searches.length > 1 ? "s" : ""}
                    {searches.some((x) => x.error) && <span className="ml-2 text-warning">{searches.filter((x) => x.error).length} en échec</span>}
                  </span>
                  <ChevronDown className="size-4 text-muted transition-transform group-open:rotate-180" />
                </summary>
                <div className="overflow-x-auto border-t border-line">
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr className="text-left text-[11px] uppercase tracking-wide text-muted">
                        <th className="px-5 py-2 font-medium">Source</th>
                        <th className="px-3 py-2 font-medium">Requête</th>
                        <th className="px-3 py-2 text-right font-medium">Résultats</th>
                        <th className="px-5 py-2 text-right font-medium">Durée</th>
                      </tr>
                    </thead>
                    <tbody>
                      {searches.map((x, i) => (
                        <tr key={i} className="border-t border-line">
                          <td className="px-5 py-2 font-medium">{x.label}</td>
                          <td className="px-3 py-2">
                            <code className="font-mono text-muted">{x.query}</code>
                            {x.error && <p className="mt-0.5 text-danger">{x.error}</p>}
                          </td>
                          <td className={`px-3 py-2 text-right tabular-nums ${x.error ? "text-danger" : x.count ? "" : "text-muted"}`}>{x.error ? "échec" : x.count}</td>
                          <td className="px-5 py-2 text-right tabular-nums text-muted">{(x.ms / 1000).toFixed(1)} s</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </Card>
          )}
          {finished && run.report && (
            <Card className="p-6">
              <Markdown>{run.report}</Markdown>
            </Card>
          )}

        </div>
      </div>
    </>
  );
}
