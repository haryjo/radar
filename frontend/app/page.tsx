"use client";

import { Coins, Download, FileText, Inbox, Info, Search, Sparkles, Zap } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AreaChart, BarChart, Donut, Sparkline } from "@/components/charts";
import { RadarIllustration } from "@/components/illustrations";
import { LiveProgress } from "@/components/live-progress";
import { OfferCard } from "@/components/offer-card";
import { Onboarding } from "@/components/onboarding";
import { Card, CardTitle, Empty, ErrorNote, PageHeader, Segmented, Skeleton, StatCard, ButtonLink } from "@/components/ui";
import { API_URL, api, type Offer, type Stats, type Timeline, type Watch } from "@/lib/api";
import { compact, percent, shortDay } from "@/lib/format";

type View = "kept" | "near" | "interesse" | "applied" | "all";

/** Chaque onglet = un filtre de l'API. */
const VIEWS: { value: View; label: string; params: Record<string, string> }[] = [
  { value: "kept", label: "Retenues", params: { status: "new", kept: "true" } },
  { value: "near", label: "Proches", params: { status: "new", kept: "false" } },
  { value: "interesse", label: "Intéressé", params: { status: "interesse" } },
  { value: "applied", label: "Candidatures", params: { status: "postule,entretien" } },
  { value: "all", label: "Toutes", params: {} },
];
type Metric = "offers" | "tokens" | "already_seen";

const METRICS: { value: Metric; label: string }[] = [
  { value: "offers", label: "Offres" },
  { value: "tokens", label: "Tokens" },
  { value: "already_seen", label: "Déjà vues" },
];

export default function OffersPage() {
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [status, setStatus] = useState<View>("kept");
  const [sort, setSort] = useState<"recent" | "score">("score");
  const [metric, setMetric] = useState<Metric>("offers");
  const [watch, setWatch] = useState("");
  const [minScore, setMinScore] = useState(0);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    api<Stats>("/api/stats").then(setStats).catch(() => null);
    api<Timeline>("/api/stats/timeline?days=14").then(setTimeline).catch(() => null);
    api<Watch[]>("/api/watches").then(setWatches).catch(() => null);
  }, []);

  // Une veille tourne : on suit son avancement et on recharge les offres à la fin
  const running = watches.filter((w) => w.running && w.live);
  const runningKey = running.map((w) => w.slug).join(",");
  useEffect(() => {
    if (!runningKey) return;
    const timer = setInterval(() => {
      api<Watch[]>("/api/watches")
        .then((next) => {
          setWatches(next);
          if (!next.some((w) => w.running)) setRefresh((n) => n + 1);
        })
        .catch(() => null);
    }, 2500);
    return () => clearInterval(timer);
  }, [runningKey]);

  useEffect(() => {
    const params = new URLSearchParams({ min_score: String(minScore), limit: "100", sort,
      ...VIEWS.find((v) => v.value === status)!.params });
    if (watch) params.set("watch", watch);
    if (query.trim()) params.set("q", query.trim());
    const handle = setTimeout(() => {
      api<Offer[]>(`/api/offers?${params}`)
        .then((data) => {
          setOffers(data);
          setError(null);
        })
        .catch((e: Error) => setError(e.message));
    }, query ? 250 : 0);
    return () => clearTimeout(handle);
  }, [status, watch, minScore, query, refresh, sort]);

  const exportParams = new URLSearchParams({
    min_score: String(minScore),
    sort,
    ...VIEWS.find((v) => v.value === status)!.params,
    ...(watch ? { watch } : {}),
    ...(query.trim() ? { q: query.trim() } : {}),
  }).toString();
  const watchNames = useMemo(() => Object.fromEntries(watches.map((w) => [w.slug, w.nom])), [watches]);
  const series = (key: Metric) => timeline?.days.map((d) => d[key]) ?? [];
  const chartData = timeline?.days.map((d) => ({ label: shortDay(d.date), value: d[metric] })) ?? [];
  const totalScored = timeline?.scores.reduce((sum, s) => sum + s.count, 0) ?? 0;

  function replace(updated: Offer) {
    setOffers((prev) => prev?.map((o) => (o.id === updated.id ? updated : o)) ?? null);
  }

  return (
    <>
      <PageHeader
        eyebrow="Tableau de bord"
        title="Offres"
        description="Les nouvelles offres trouvées par tes veilles, notées selon ton profil."
        actions={
          <>
            <a
              href={`${API_URL}/api/offers/export.csv?${exportParams}`}
              download
              className="inline-flex h-9 items-center gap-1.5 rounded-lg px-3.5 text-sm font-medium text-muted transition-colors hover:bg-ink/5 hover:text-ink"
            >
              <Download className="size-4" />Exporter
            </a>
            <ButtonLink href="/veilles"><FileText className="size-4" />Gérer les veilles</ButtonLink>
          </>
        }
      />

      <Onboarding />

      {running.map((w) => (
        <Link key={w.slug} href={`/historique/${w.live!.run_id}`} className="mb-4 block">
          <Card className="flex items-center gap-4 border-accent/40 p-4 transition-colors hover:border-accent">
            <RadarIllustration className="size-10 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="mb-1.5 text-sm font-medium">{w.nom} <span className="font-normal text-muted">· recherche en cours</span></p>
              <LiveProgress live={w.live!} />
            </div>
            <span className="hidden text-[12px] font-medium text-accent sm:block">Suivre →</span>
          </Card>
        </Link>
      ))}

      {/* Indicateurs avec tendance sur 14 jours */}
      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Nouvelles offres" value={stats?.new_offers ?? "–"} hint={`${stats?.offers_found ?? 0} trouvées cette semaine`} icon={<Sparkles className="size-3.5" />}>
          <Sparkline values={series("offers")} />
        </StatCard>
        <StatCard label="Veilles actives" value={stats ? `${stats.watches_active}/${stats.watches_total}` : "–"} hint={`${stats?.runs ?? 0} exécutions cette semaine`} icon={<FileText className="size-3.5" />}>
          <Sparkline values={timeline?.days.map((d) => d.runs) ?? []} color="var(--chart-3)" />
        </StatCard>
        <StatCard label="Tokens consommés" value={stats ? compact(stats.tokens) : "–"} hint="sur 7 jours" icon={<Coins className="size-3.5" />}>
          <Sparkline values={series("tokens")} color="var(--chart-2)" />
        </StatCard>
        <StatCard label="URLs déjà vues évitées" value={stats ? compact(stats.already_seen_skipped) : "–"} hint="grâce à la veille incrémentale" icon={<Zap className="size-3.5" />}>
          <Sparkline values={series("already_seen")} color="var(--chart-2)" />
        </StatCard>
      </div>

      {/* Graphiques */}
      <div className="mb-10 grid gap-3 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <CardTitle aside={<Segmented value={metric} options={METRICS} onChange={setMetric} />}>Activité sur 14 jours</CardTitle>
          {timeline ? (
            <AreaChart data={chartData} height={210} color={metric === "offers" ? "var(--chart-1)" : "var(--chart-2)"} format={(v) => compact(v)} />
          ) : (
            <Skeleton className="h-[210px]" />
          )}
        </Card>

        <div className="grid gap-3">
          <Card className="flex items-center gap-5 p-5">
            <Donut value={stats?.cache_hit_rate ?? 0} size={92}>
              <span className="text-lg font-semibold tabular-nums">{percent(stats?.cache_hit_rate)}</span>
            </Donut>
            <div>
              <p className="text-[13px] font-medium">Taux de cache</p>
              <p className="mt-1 text-[12px] leading-relaxed text-muted">
                Pages compressées de <span className="font-medium text-ink">{percent(stats?.compression_rate)}</span> avant envoi au LLM.
              </p>
            </div>
          </Card>
          <Card className="p-5">
            <CardTitle aside={<span className="text-[11px] text-muted">{totalScored} offres</span>}>Répartition des scores</CardTitle>
            {timeline ? (
              <BarChart data={timeline.scores.map((s) => ({ label: s.label, value: s.count }))} height={112} color="var(--chart-1)" />
            ) : (
              <Skeleton className="h-28" />
            )}
          </Card>
        </div>
      </div>

      {/* Liste des offres */}
      <div className="sticky top-0 z-10 -mx-2 mb-4 flex flex-wrap items-center gap-2 bg-canvas/85 px-2 py-2 backdrop-blur-xl">
        <Segmented<View> value={status} onChange={setStatus} options={VIEWS.map(({ value, label }) => ({ value, label }))} />
        <select value={sort} onChange={(e) => setSort(e.target.value as "recent" | "score")} className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px]" aria-label="Tri">
          <option value="score">Meilleur score</option>
          <option value="recent">Plus récentes</option>
        </select>
        <select value={watch} onChange={(e) => setWatch(e.target.value)} className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px]">
          <option value="">Toutes les veilles</option>
          {watches.map((w) => <option key={w.slug} value={w.slug}>{w.nom}</option>)}
        </select>
        <select value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px]">
          {[0, 60, 70, 80, 90].map((s) => <option key={s} value={s}>{s ? `Score ≥ ${s}` : "Tout score"}</option>)}
        </select>
        <label className="relative ml-auto">
          <Search className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher une offre…"
            className="h-8 w-56 rounded-lg border border-line bg-surface pl-8 pr-2 text-[13px] outline-none transition-colors focus:border-accent"
          />
        </label>
      </div>

      <p className="-mt-1 mb-4 flex items-start gap-1.5 text-[12px] text-muted">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        {status === "near"
          ? "Offres notées un peu sous ton score minimum (jusqu'à 20 points) : elles peuvent quand même t'intéresser."
          : "Radar ne postule jamais à ta place : « Ouvrir l'offre » mène à l'annonce, et les statuts (Intéressé, J'ai postulé, Entretien) servent à ton suivi et apprennent tes goûts à l'agent."}
      </p>

      {error && <ErrorNote message={`API injoignable : ${error}`} />}
      {!offers && !error && <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}</div>}
      {offers && offers.length === 0 && (
        <Empty
          illustration={<RadarIllustration className="size-28" />}
          title={status === "kept" ? "Aucune nouvelle offre retenue pour l'instant" : status === "near" ? "Aucune offre proche" : "Aucune offre ici"}
          action={<ButtonLink href="/veilles" variant="primary"><Inbox className="size-4" />Lancer une veille</ButtonLink>}
        >
          Le radar tourne : les prochaines offres apparaîtront ici après l'exécution planifiée de tes veilles.
        </Empty>
      )}
      <div className="space-y-3">
        {offers?.map((offer) => (
          <OfferCard key={offer.id} offer={offer} onChange={replace} watchName={watch ? undefined : watchNames[offer.watch] ?? (offer.watch === "assistant" ? "Assistant" : offer.watch)} />
        ))}
      </div>
    </>
  );
}
