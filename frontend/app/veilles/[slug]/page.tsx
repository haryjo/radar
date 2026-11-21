"use client";

import clsx from "clsx";
import { ChevronRight, History, Inbox, Play, Settings2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { RadarIllustration } from "@/components/illustrations";
import { LiveProgress } from "@/components/live-progress";
import { OfferCard } from "@/components/offer-card";
import { useToast } from "@/components/toast";
import { Button, Card, Empty, ErrorNote, PageHeader, RunStatusBadge, Segmented, Skeleton } from "@/components/ui";
import { WatchEditor } from "@/components/watch-editor";
import { api, type Offer, type Run, type Watch } from "@/lib/api";
import { compact, dateTime, describeCron } from "@/lib/format";

type Tab = "offers" | "runs" | "settings";
type Kept = "kept" | "near" | "all";

export default function WatchPage() {
  const { slug } = useParams<{ slug: string }>();
  const [watch, setWatch] = useState<Watch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("offers");
  const [kept, setKept] = useState<Kept>("kept");
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [launching, setLaunching] = useState(false);
  const router = useRouter();
  const toast = useToast();

  const loadWatch = useCallback(() => {
    api<Watch>(`/api/watches/${slug}`).then(setWatch).catch((e: Error) => setError(e.message));
  }, [slug]);

  useEffect(() => {
    loadWatch();
  }, [loadWatch]);

  useEffect(() => {
    if (tab !== "offers") return;
    const params = new URLSearchParams({ watch: slug, sort: "score", limit: "200" });
    if (kept !== "all") params.set("kept", String(kept === "kept"));
    api<Offer[]>(`/api/offers?${params}`).then(setOffers).catch((e: Error) => setError(e.message));
  }, [slug, tab, kept, refresh]);

  useEffect(() => {
    if (tab === "runs") api<Run[]>(`/api/runs?watch=${slug}&limit=50`).then(setRuns).catch(() => setRuns([]));
  }, [slug, tab]);

  // Pendant une exécution : progression et rechargement des offres à la fin
  useEffect(() => {
    if (!watch?.running) return;
    const timer = setInterval(() => {
      api<Watch>(`/api/watches/${slug}`)
        .then((next) => {
          setWatch(next);
          if (!next.running) setRefresh((n) => n + 1);
        })
        .catch(() => null);
    }, 2500);
    return () => clearInterval(timer);
  }, [slug, watch?.running]);

  async function launch() {
    setLaunching(true);
    try {
      const { run_id } = await api<{ run_id: number }>(`/api/watches/${slug}/run`, { method: "POST" });
      router.push(`/historique/${run_id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      setLaunching(false);
    }
  }

  if (error) return <ErrorNote message={error} />;
  if (!watch) return <Skeleton className="h-[70vh]" />;

  const TABS: { value: Tab; label: string; icon: typeof Inbox; count?: number }[] = [
    { value: "offers", label: "Offres", icon: Inbox, count: watch.offers_total },
    { value: "runs", label: "Exécutions", icon: History },
    { value: "settings", label: "Réglages", icon: Settings2 },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Veille"
        title={watch.nom}
        description={watch.valid ? `${describeCron(watch.planning)} · ${watch.connecteurs.join(", ")}` : watch.error ?? undefined}
        actions={watch.running && watch.live ? (
          <Link href={`/historique/${watch.live.run_id}`} className="text-[13px] font-medium text-accent hover:underline">Suivre l'exécution →</Link>
        ) : (
          <Button variant="primary" onClick={launch} loading={launching} disabled={!watch.valid}>
            <Play className="size-4" />Lancer maintenant
          </Button>
        )}
      />

      {watch.running && watch.live && (
        <Card className="mb-5 flex items-center gap-4 p-4">
          <RadarIllustration className="size-10 shrink-0" />
          <div className="min-w-0 flex-1"><LiveProgress live={watch.live} /></div>
        </Card>
      )}

      <div className="mb-5 flex gap-1 border-b border-line">
        {TABS.map(({ value, label, icon: Icon, count }) => (
          <button
            key={value}
            onClick={() => setTab(value)}
            className={clsx(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors",
              tab === value ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink",
            )}
          >
            <Icon className="size-4" />
            {label}
            {count !== undefined && <span className="rounded-full bg-ink/[0.06] px-1.5 text-[11px] tabular-nums">{count}</span>}
          </button>
        ))}
      </div>

      {tab === "offers" && (
        <>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <Segmented<Kept>
              value={kept}
              onChange={setKept}
              options={[
                { value: "kept", label: `Retenues (${watch.offers_total - watch.offers_near})` },
                { value: "near", label: `Proches (${watch.offers_near})` },
                { value: "all", label: "Toutes" },
              ]}
            />
            <p className="text-[12px] text-muted">Triées par score · score minimum {watch.score_minimum}</p>
          </div>
          {!offers && <div className="space-y-3">{[0, 1].map((i) => <Skeleton key={i} className="h-36" />)}</div>}
          {offers?.length === 0 && (
            <Empty illustration={<RadarIllustration className="size-24" active={false} />} title="Aucune offre pour cette veille">
              {kept === "near" ? "Aucune offre n'a été notée juste sous le seuil." : "Clique sur « Lancer maintenant » ou attends la prochaine exécution planifiée."}
            </Empty>
          )}
          <div className="space-y-3">
            {offers?.map((offer) => (
              <OfferCard key={offer.id} offer={offer} onChange={(u) => setOffers((all) => all?.map((o) => (o.id === u.id ? u : o)) ?? null)} />
            ))}
          </div>
        </>
      )}

      {tab === "runs" && (
        runs === null ? <Skeleton className="h-64" /> : runs.length === 0 ? (
          <Empty illustration={<RadarIllustration className="size-24" active={false} />} title="Aucune exécution pour l'instant" />
        ) : (
          <Card className="overflow-hidden">
            <ul className="divide-y divide-line">
              {runs.map((run) => (
                <li key={run.id}>
                  <Link href={`/historique/${run.id}`} className="group flex items-center gap-4 px-5 py-3.5 hover:bg-raised/60">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium group-hover:text-accent">Exécution #{run.id}</p>
                      <p className="text-[12px] text-muted">{dateTime(run.started_at)} · {run.trigger}</p>
                    </div>
                    <div className="hidden gap-6 text-right text-[12px] text-muted sm:flex">
                      <span><span className="block text-sm font-medium text-ink tabular-nums">{run.stats.offers_saved ?? 0}</span>retenues</span>
                      <span><span className="block text-sm font-medium text-ink tabular-nums">{run.stats.offers_near ?? 0}</span>proches</span>
                      <span><span className="block text-sm font-medium text-ink tabular-nums">{compact((run.stats.tokens_in ?? 0) + (run.stats.tokens_out ?? 0))}</span>tokens</span>
                    </div>
                    <RunStatusBadge status={run.status} />
                    <ChevronRight className="size-4 text-muted" />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )
      )}

      {tab === "settings" && (
        <>
          <p className="mb-4 flex items-center gap-1.5 text-[12px] text-muted">
            <Sparkles className="size-3.5 text-accent" />Les modifications s'appliquent dès l'enregistrement, sans redémarrage.
          </p>
          <WatchEditor key={watch.slug} slug={watch.slug} initial={watch.content ?? ""} embedded />
        </>
      )}
    </>
  );
}
