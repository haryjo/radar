"use client";

import clsx from "clsx";
import { AlertCircle, Bell, CalendarClock, Play, Plus, Radar } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Sparkline } from "@/components/charts";
import { LiveProgress } from "@/components/live-progress";
import { FilesIllustration } from "@/components/illustrations";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, Skeleton, ButtonLink } from "@/components/ui";
import { api, type Watch } from "@/lib/api";
import { describeCron, relativeTime } from "@/lib/format";

function StatusBadge({ watch }: { watch: Watch }) {
  if (!watch.valid) return <Badge tone="red" dot>Invalide</Badge>;
  if (watch.running) return <Badge tone="accent" dot>En cours</Badge>;
  if (watch.actif) return <Badge tone="green" dot>Active</Badge>;
  return <Badge dot>En pause</Badge>;
}

export default function WatchesPage() {
  const router = useRouter();
  const toast = useToast();
  const [watches, setWatches] = useState<Watch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState<string | null>(null);

  useEffect(() => {
    api<Watch[]>("/api/watches").then(setWatches).catch((e: Error) => setError(e.message));
  }, []);

  // Rafraîchissement automatique tant qu'une veille tourne
  const anyRunning = watches?.some((w) => w.running) ?? false;
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(() => {
      api<Watch[]>("/api/watches").then(setWatches).catch(() => null);
    }, 2500);
    return () => clearInterval(timer);
  }, [anyRunning]);

  async function run(slug: string) {
    setStarting(slug);
    try {
      const { run_id } = await api<{ run_id: number }>(`/api/watches/${slug}/run`, { method: "POST" });
      router.push(`/historique/${run_id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      setStarting(null);
    }
  }

  const newButton = (
    <ButtonLink href="/veilles/nouvelle" variant="primary"><Plus className="size-4" />Nouvelle veille</ButtonLink>
  );

  return (
    <>
      <PageHeader
        eyebrow="Configuration"
        title="Veilles"
        description="Chaque veille est un fichier Markdown dans config/veilles. Le modifier suffit à la replanifier."
        actions={newButton}
      />
      {error && <div className="mb-4"><ErrorNote message={error} /></div>}
      {!watches && !error && <div className="grid gap-3 sm:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-52" />)}</div>}
      {watches?.length === 0 && (
        <Empty illustration={<FilesIllustration className="w-32" />} title="Aucune veille" action={newButton}>
          Crée ta première veille ici, ou dépose un fichier .md dans config/veilles.
        </Empty>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {watches?.map((w) => (
          <Card key={w.slug} className={clsx("group flex flex-col overflow-hidden transition-colors hover:border-ink/15", !w.actif && "opacity-80")}>
            <div className="flex items-start gap-3 p-5 pb-4">
              <div className="relative grid size-10 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                <Radar className={clsx("size-[18px]", w.running && "animate-spin [animation-duration:3s]")} />
                {w.actif && w.valid && <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-success" />}
              </div>
              <Link href={`/veilles/${w.slug}`} className="min-w-0 flex-1">
                <p className="truncate font-medium group-hover:text-accent">{w.nom}</p>
                <p className="truncate font-mono text-[11px] text-muted">veilles/{w.slug}.md</p>
              </Link>
              <StatusBadge watch={w} />
            </div>

            <div className="flex-1 px-5">
              {w.live ? (
                <LiveProgress live={w.live} />
              ) : w.error ? (
                <p className="flex gap-1.5 rounded-lg bg-danger/8 p-2.5 text-[12px] text-danger"><AlertCircle className="mt-0.5 size-3.5 shrink-0" />{w.error}</p>
              ) : (
                <div className="flex items-end justify-between gap-4">
                  <div className="space-y-1.5 text-[13px] text-muted">
                    <p className="flex items-center gap-1.5"><CalendarClock className="size-3.5" />{describeCron(w.planning)}</p>
                    <p className="flex items-center gap-1.5"><Bell className="size-3.5" />Notification {w.notification}</p>
                    <p className="flex flex-wrap gap-1 pt-0.5">
                      {w.connecteurs.map((c) => <span key={c} className="rounded-md bg-raised px-1.5 py-0.5 text-[10px] capitalize">{c}</span>)}
                    </p>
                  </div>
                  <div className="w-28 text-right">
                    <Sparkline values={w.history.length ? w.history : [0, 0]} />
                    <p className="text-[10px] text-muted">offres par exécution</p>
                  </div>
                </div>
              )}
            </div>

            <div className="mt-4 flex items-center justify-between border-t border-line bg-raised/50 px-5 py-3">
              <div className="flex items-baseline gap-4 text-[12px] text-muted">
                <span><span className="text-base font-semibold text-ink tabular-nums">{w.offers_new}</span> nouvelles</span>
                <span>{w.next_run ? `Prochaine ${relativeTime(w.next_run)}` : `Dernière ${relativeTime(w.last_run?.started_at)}`}</span>
              </div>
              {w.running && w.last_run ? (
                <Link
                  href={`/historique/${w.last_run.id}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent-soft px-2.5 text-[13px] font-medium text-accent"
                >
                  <Play className="size-3.5" />Suivre
                </Link>
              ) : (
                <Button size="sm" onClick={() => run(w.slug)} loading={starting === w.slug} disabled={!w.valid}>
                  <Play className="size-3.5" />Lancer
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}
