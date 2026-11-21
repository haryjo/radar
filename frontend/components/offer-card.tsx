"use client";

import clsx from "clsx";
import { AlertTriangle, ArrowUpRight, CalendarCheck, Check, EyeOff, MapPin, Send, Star } from "lucide-react";
import { useState } from "react";
import { api, type Offer, type OfferStatus } from "@/lib/api";
import { hostname, hueOf, initials, relativeTime } from "@/lib/format";
import { Badge, Card, Chip, ScoreRing } from "./ui";

/** Statuts de suivi : ils ne contactent personne et ne postulent jamais à ta place.
 *  Ils organisent ton suivi et apprennent tes goûts à l'agent (mémoire long terme). */
const ACTIONS: { status: OfferStatus; label: string; icon: typeof Star; help: string; when?: OfferStatus[] }[] = [
  { status: "interesse", label: "Intéressé", icon: Star, help: "À garder : l'agent favorisera les offres similaires" },
  { status: "postule", label: "J'ai postulé", icon: Send, help: "Marque que tu as envoyé ta candidature (suivi)" },
  { status: "entretien", label: "Entretien", icon: CalendarCheck, help: "Tu as obtenu un entretien", when: ["postule", "entretien"] },
  { status: "ignore", label: "Ignorer", icon: EyeOff, help: "Pas pour moi : l'agent évitera ce type d'offre" },
];

const SOURCE_LABEL: Record<string, string> = {
  web: "Web", jsonld: "Web (fiche structurée)", jobicy: "Jobicy", arbeitnow: "Arbeitnow", remoteok: "Remote OK",
  himalayas: "Himalayas", apify: "Apify", assistant: "Recherche express",
};


/** Monogramme coloré de l'entreprise, lisible en clair comme en sombre (aucune requête externe). */
export function CompanyAvatar({ name, url, size = 44 }: { name: string; url: string; size?: number }) {
  const label = name || hostname(url);
  const hue = hueOf(label);
  return (
    <div
      className="relative grid shrink-0 place-items-center overflow-hidden rounded-xl border border-line text-[13px] font-semibold"
      style={{
        width: size,
        height: size,
        background: `color-mix(in oklch, oklch(0.7 0.12 ${hue}) 16%, var(--surface))`,
        color: `color-mix(in oklch, oklch(0.6 0.14 ${hue}) 75%, var(--ink))`,
      }}
    >
      {initials(label)}
    </div>
  );
}

export function OfferCard({ offer, onChange, watchName }: { offer: Offer; onChange: (offer: Offer) => void; watchName?: string }) {
  const [busy, setBusy] = useState<OfferStatus | null>(null);

  async function setStatus(status: OfferStatus) {
    setBusy(status);
    try {
      onChange(await api<Offer>(`/api/offers/${offer.id}`, { method: "PATCH", body: JSON.stringify({ status }) }));
    } finally {
      setBusy(null);
    }
  }

  const facts = [offer.contract, offer.remote].filter(Boolean);

  return (
    <Card className={clsx("group animate-fade-in p-5 transition-all hover:border-ink/15", offer.status === "ignore" && "opacity-55")}>
      <div className="flex gap-4">
        <CompanyAvatar name={offer.company} url={offer.url} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <a href={offer.url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 font-medium leading-snug hover:text-accent">
                <span className="truncate">{offer.title}</span>
                <ArrowUpRight className="size-3.5 shrink-0 text-muted opacity-0 transition-opacity group-hover:opacity-100" />
              </a>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-muted">
                <span className="font-medium text-ink/80">{offer.company || hostname(offer.url)}</span>
                {offer.location && (
                  <span className="inline-flex items-center gap-0.5"><MapPin className="size-3" />{offer.location}</span>
                )}
                {facts.map((f) => <span key={f}>· {f}</span>)}
              </p>
            </div>
            <ScoreRing score={offer.score} />
          </div>

          {offer.summary && <p className="mt-3 text-sm leading-relaxed text-ink/80">{offer.summary}</p>}

          {(offer.reasons.length > 0 || offer.red_flags.length > 0) && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {offer.reasons.map((r) => (
                <span key={r} className="inline-flex items-center gap-1 rounded-lg bg-success/10 px-2 py-1 text-[12px] text-ink/80">
                  <Check className="size-3 text-success" />{r}
                </span>
              ))}
              {offer.red_flags.map((r) => (
                <span key={r} className="inline-flex items-center gap-1 rounded-lg bg-warning/12 px-2 py-1 text-[12px] text-ink/80">
                  <AlertTriangle className="size-3 text-warning" />{r}
                </span>
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            <div className="flex flex-wrap items-center gap-1">
              {offer.skills.slice(0, 5).map((s) => <Chip key={s}>{s}</Chip>)}
              <span className="ml-1 text-[11px] text-muted" title={offer.query ? `Trouvée avec la requête « ${offer.query} »` : undefined}>
                {SOURCE_LABEL[offer.source ?? "web"] ?? offer.source}
                {offer.query && <> · « {offer.query.length > 32 ? `${offer.query.slice(0, 32)}…` : offer.query} »</>}
                {watchName && <> · {watchName}</>} · {relativeTime(offer.found_at)}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {!offer.kept && offer.status === "new" && <Badge tone="amber">Proche</Badge>}
              <a
                href={offer.contact?.startsWith("http") ? offer.contact : offer.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-7 items-center gap-1 rounded-md bg-accent-soft px-2 text-[12px] font-medium text-accent hover:opacity-85"
                title="Ouvre l'annonce d'origine pour postuler"
              >
                <ArrowUpRight className="size-3.5" />
                <span className="hidden sm:inline">Ouvrir l'offre</span>
              </a>
              {ACTIONS.filter((a) => !a.when || a.when.includes(offer.status)).map(({ status, label, icon: Icon, help }) => (
                <button
                  key={status}
                  onClick={() => setStatus(offer.status === status ? "new" : status)}
                  disabled={busy !== null}
                  title={help}
                  className={clsx(
                    "inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] transition-colors",
                    offer.status === status ? "bg-ink text-canvas" : "text-muted hover:bg-ink/5 hover:text-ink",
                  )}
                >
                  <Icon className={clsx("size-3.5", busy === status && "animate-pulse")} />
                  <span className="hidden sm:inline">{label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
