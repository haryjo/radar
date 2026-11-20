"use client";

import clsx from "clsx";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Health } from "@/lib/api";

const ROUTING_LABEL = { fixe: "fixe", intelligent: "intelligent", performance: "performance" } as const;

/** État de l'API et du routage LLM, rafraîchi toutes les 30 s. */
export function StatusPill() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Health>("/api/health", undefined, 0)
        .then((h) => alive && (setHealth(h), setDown(false)))
        .catch(() => alive && setDown(true));
    load();
    const timer = setInterval(load, 30_000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const noLlm = health && health.providers_ready === 0;
  const tone = down ? "bg-danger" : noLlm ? "bg-warning" : health ? "bg-success" : "bg-muted";

  return (
    <Link href="/modeles" className="block rounded-xl border border-line bg-surface px-3 py-2.5 transition-colors hover:border-ink/15">
      <div className="flex items-center gap-2">
        <span className="relative flex size-2">
          {health && !down && !noLlm && <span className={clsx("absolute inset-0 animate-ping rounded-full opacity-60", tone)} />}
          <span className={clsx("relative size-2 rounded-full", tone)} />
        </span>
        <span className="truncate text-[12px] font-medium">
          {down ? "API injoignable" : noLlm ? "Aucun LLM configuré" : health?.provider ?? "Connexion…"}
        </span>
      </div>
      {health && !down && (
        <p className="mt-0.5 pl-4 text-[11px] text-muted">
          Routage {ROUTING_LABEL[health.routing]} · {health.providers_ready} fournisseur{health.providers_ready > 1 ? "s" : ""}
        </p>
      )}
    </Link>
  );
}
