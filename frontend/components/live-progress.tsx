"use client";

import { STAGES } from "./run-timeline";
import type { Watch } from "@/lib/api";

/** Barre compacte d'avancement d'une veille en cours (cartes, tableau de bord). */
export function LiveProgress({ live }: { live: NonNullable<Watch["live"]> }) {
  const p = live.progress;
  const index = p ? STAGES.findIndex((s) => s.id === p.stage) : 0;
  const stageRatio = p && p.total ? p.done / p.total : 0;
  const overall = Math.min(((Math.max(index, 0) + stageRatio) / STAGES.length) * 100, 99);
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[12px]">
        <span className="truncate">
          <span className="font-medium">{p ? STAGES[index]?.label ?? "En cours" : "Démarrage"}</span>
          {p && p.total > 1 && <span className="text-muted"> · {p.done}/{p.total}</span>}
        </span>
        {live.offers_kept > 0 && <span className="shrink-0 text-success">{live.offers_kept} retenue{live.offers_kept > 1 ? "s" : ""}</span>}
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink/[0.07]">
        <div className="h-full rounded-full bg-accent transition-all duration-700" style={{ width: `${Math.max(overall, 4)}%` }} />
      </div>
    </div>
  );
}
