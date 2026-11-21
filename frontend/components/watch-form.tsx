"use client";

import clsx from "clsx";
import { Check, KeyRound, X, Zap } from "lucide-react";
import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { api, type Connector } from "@/lib/api";

/* Formulaire guidé : il lit et écrit le même fichier Markdown que le mode avancé. */

export interface WatchFields {
  nom: string;
  planning: string;
  actif: boolean;
  max_resultats: number;
  score_minimum: number;
  mots_cles: string[];
  localisation: string | null;
  fraicheur_jours: number;
  sources: string[];
  exclure: string[];
  connecteurs: string[];
  notification: "app" | "telegram" | "aucune";
  langue: string;
  budget_tokens: number | null;
  apify_actor: string | null;
  apify_input: Record<string, unknown> | null;
}

const ORDER: (keyof WatchFields)[] = [
  "nom", "planning", "actif", "max_resultats", "score_minimum", "mots_cles", "localisation", "fraicheur_jours",
  "sources", "exclure", "connecteurs", "notification", "langue", "budget_tokens", "apify_actor", "apify_input",
];

function yamlValue(value: unknown): string {
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((v) => JSON.stringify(v)).join(", ")}]`;
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Fichier Markdown à partir du formulaire (YAML compatible : chaînes et listes au format JSON). */
export function toMarkdown(fields: WatchFields, body: string): string {
  const lines = ORDER.filter((key) => {
    const v = fields[key];
    return v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0 && key !== "connecteurs");
  }).map((key) => `${key}: ${yamlValue(fields[key])}`);
  return `---\n${lines.join("\n")}\n---\n\n${body.trim()}\n`;
}

const SCHEDULES = [
  { cron: "0 8 * * 1-5", label: "Jours ouvrés, 8 h" },
  { cron: "0 8 * * *", label: "Tous les jours, 8 h" },
  { cron: "0 8,18 * * *", label: "Deux fois par jour" },
  { cron: "30 18 * * 1,3,5", label: "Lun, mer, ven, 18 h 30" },
  { cron: "0 8 * * 1", label: "Chaque lundi, 8 h" },
];

/** Champ de formulaire. `group` : plusieurs boutons (role="group"), sinon un seul contrôle dans un <label>. */
function Field({ label, hint, group, children }: { label: string; hint?: string; group?: boolean; children: ReactNode }) {
  const inner = (
    <>
      <span className="text-[13px] font-medium">{label}</span>
      {hint && <span className="block text-[12px] text-muted">{hint}</span>}
      <div className="mt-2">{children}</div>
    </>
  );
  return group ? <div role="group" aria-label={label} className="block">{inner}</div> : <label className="block">{inner}</label>;
}

const inputClass = "h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm outline-none transition-colors focus:border-accent";

function ChipsInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  const [draft, setDraft] = useState("");
  function commit() {
    const items = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (items.length) onChange([...value, ...items.filter((i) => !value.includes(i))]);
    setDraft("");
  }
  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  }
  return (
    <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-lg border border-line bg-surface px-2 py-1.5 focus-within:border-accent">
      {value.map((item) => (
        <span key={item} className="inline-flex items-center gap-1 rounded-md bg-accent-soft px-2 py-0.5 text-[12px] text-accent">
          {item}
          <button type="button" onClick={() => onChange(value.filter((v) => v !== item))} aria-label={`Retirer ${item}`}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKey}
        onBlur={commit}
        placeholder={value.length ? "" : placeholder}
        className="min-w-32 flex-1 bg-transparent text-sm outline-none"
      />
    </div>
  );
}

export function WatchForm({ fields, body, onChange }: {
  fields: WatchFields;
  body: string;
  onChange: (fields: WatchFields, body: string) => void;
}) {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [customCron, setCustomCron] = useState(!SCHEDULES.some((s) => s.cron === fields.planning));
  const [apifyInput, setApifyInput] = useState(fields.apify_input ? JSON.stringify(fields.apify_input, null, 2) : "");
  const [apifyError, setApifyError] = useState<string | null>(null);

  useEffect(() => {
    api<Connector[]>("/api/connectors").then(setConnectors).catch(() => null);
  }, []);

  const set = <K extends keyof WatchFields>(key: K, value: WatchFields[K]) => onChange({ ...fields, [key]: value }, body);

  function toggleConnector(id: string) {
    const has = fields.connecteurs.includes(id);
    const next = has ? fields.connecteurs.filter((c) => c !== id) : [...fields.connecteurs, id];
    if (next.length) set("connecteurs", next);
  }

  return (
    <div className="space-y-8">
      <section className="grid gap-5 sm:grid-cols-2">
        <Field label="Nom de la veille">
          <input value={fields.nom} onChange={(e) => set("nom", e.target.value)} className={inputClass} placeholder="Stage IA à Antananarivo" />
        </Field>
        <Field label="Localisation" hint="Ville, pays ou « télétravail »">
          <input value={fields.localisation ?? ""} onChange={(e) => set("localisation", e.target.value || null)} className={inputClass} placeholder="Antananarivo ou télétravail" />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Mots-clés" hint="Intitulés de poste ou compétences. Entrée ou virgule pour ajouter.">
            <ChipsInput value={fields.mots_cles} onChange={(v) => set("mots_cles", v)} placeholder="développeur python, stage IA…" />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="À exclure" hint="Une offre contenant l'un de ces termes est écartée, sans appel au LLM.">
            <ChipsInput value={fields.exclure} onChange={(v) => set("exclure", v)} placeholder="stage non rémunéré, senior…" />
          </Field>
        </div>
      </section>

      <section>
        <p className="text-[13px] font-medium">Où chercher</p>
        <p className="text-[12px] text-muted">Les API d'offres sont bien plus rapides que la recherche web : elles renvoient des offres déjà structurées.</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {connectors.map((c) => {
            const on = fields.connecteurs.includes(c.id);
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => toggleConnector(c.id)}
                className={clsx(
                  "relative rounded-xl border p-3.5 text-left transition-all",
                  on ? "border-accent bg-accent-soft/40 ring-2 ring-accent-soft" : "border-line hover:border-ink/20",
                )}
              >
                <span className={clsx("absolute right-3 top-3 grid size-4 place-items-center rounded border", on ? "border-accent bg-accent text-white" : "border-line")}>
                  {on && <Check className="size-3" />}
                </span>
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  {c.label}
                  {c.speed === "rapide" && <Zap className="size-3.5 text-chart-2" />}
                </span>
                <span className="mt-0.5 block text-[11px] text-muted">{c.scope}</span>
                <span className="mt-1.5 block text-[12px] leading-snug text-muted">{c.description}</span>
                {!c.configured && c.key && (
                  <span className="mt-2 inline-flex items-center gap-1 rounded-md bg-warning/15 px-1.5 py-0.5 text-[11px] text-warning">
                    <KeyRound className="size-3" />{c.key} manquant
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {fields.connecteurs.includes("apify") && (
          <div className="mt-4 grid gap-4 rounded-xl border border-line bg-raised/40 p-4 sm:grid-cols-2">
            <Field label="Actor Apify" hint="Identifiant de l'Actor, visible dans son URL sur apify.com">
              <input value={fields.apify_actor ?? ""} onChange={(e) => set("apify_actor", e.target.value || null)} className={clsx(inputClass, "font-mono text-[13px]")} placeholder="auteur/nom-de-l-actor" />
            </Field>
            <Field label="Entrée de l'Actor (JSON, optionnel)" hint="{requete} est remplacé par chaque requête de recherche.">
              <textarea
                value={apifyInput}
                onChange={(e) => {
                  setApifyInput(e.target.value);
                  if (!e.target.value.trim()) {
                    setApifyError(null);
                    set("apify_input", null);
                    return;
                  }
                  try {
                    const parsed = JSON.parse(e.target.value);
                    setApifyError(null);
                    set("apify_input", parsed);
                  } catch {
                    setApifyError("JSON invalide");
                  }
                }}
                rows={3}
                spellCheck={false}
                className="w-full rounded-lg border border-line bg-surface p-2.5 font-mono text-[12px] outline-none focus:border-accent"
                placeholder={'{"position": "{requete}", "maxItems": 20}'}
              />
              {apifyError && <span className="text-[11px] text-danger">{apifyError}</span>}
            </Field>
          </div>
        )}
      </section>

      <section className="grid gap-5 sm:grid-cols-2">
        <Field label="Quand chercher" group>
          <div className="flex flex-wrap gap-1.5">
            {SCHEDULES.map((s) => (
              <button
                key={s.cron}
                type="button"
                onClick={() => {
                  setCustomCron(false);
                  set("planning", s.cron);
                }}
                className={clsx("rounded-lg border px-2.5 py-1.5 text-[12px]", !customCron && fields.planning === s.cron ? "border-accent bg-accent-soft/50 font-medium text-accent" : "border-line text-muted hover:text-ink")}
              >
                {s.label}
              </button>
            ))}
            <button type="button" onClick={() => setCustomCron(true)} className={clsx("rounded-lg border px-2.5 py-1.5 text-[12px]", customCron ? "border-accent bg-accent-soft/50 font-medium text-accent" : "border-line text-muted")}>
              Personnalisé
            </button>
          </div>
          {customCron && (
            <input value={fields.planning} onChange={(e) => set("planning", e.target.value)} className={clsx(inputClass, "mt-2 font-mono")} placeholder="minute heure jour mois jour-semaine" />
          )}
        </Field>
        <Field label="Ancienneté maximale des offres">
          <select value={fields.fraicheur_jours} onChange={(e) => set("fraicheur_jours", Number(e.target.value))} className={inputClass}>
            {[1, 3, 7, 14, 30].map((d) => <option key={d} value={d}>{d === 1 ? "24 heures" : `${d} jours`}</option>)}
          </select>
        </Field>
        <Field label={`Score minimum : ${fields.score_minimum}/100`} hint="En dessous, l'offre est notée mais pas retenue.">
          <input type="range" min={0} max={100} step={5} value={fields.score_minimum} onChange={(e) => set("score_minimum", Number(e.target.value))} className="w-full accent-[var(--accent)]" />
        </Field>
        <Field label="Offres retenues au maximum par exécution">
          <input type="number" min={1} max={30} value={fields.max_resultats} onChange={(e) => set("max_resultats", Math.max(1, Math.min(30, Number(e.target.value) || 1)))} className={inputClass} />
        </Field>
        <Field label="Notification" group>
          <div className="flex rounded-lg border border-line p-0.5">
            {(["app", "telegram", "aucune"] as const).map((n) => (
              <button key={n} type="button" onClick={() => set("notification", n)} className={clsx("flex-1 rounded-md px-2 py-1.5 text-[12px]", fields.notification === n ? "bg-raised font-medium shadow-sm" : "text-muted")}>
                {{ app: "Dans l'app", telegram: "Telegram", aucune: "Aucune" }[n]}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Veille active" group>
          <button type="button" role="switch" aria-checked={fields.actif} onClick={() => set("actif", !fields.actif)} className="flex items-center gap-2.5 text-sm">
            <span className={clsx("relative h-6 w-11 rounded-full transition-colors", fields.actif ? "bg-accent" : "bg-ink/15")}>
              <span className={clsx("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", fields.actif ? "left-[22px]" : "left-0.5")} />
            </span>
            {fields.actif ? "Exécutée selon le planning" : "En pause (lancement manuel seulement)"}
          </button>
        </Field>
      </section>

      <section>
        <Field label="Instructions pour l'agent" hint="En langage naturel : objectif, priorités, ce qui augmente ou baisse l'intérêt d'une offre.">
          <textarea
            value={body}
            onChange={(e) => onChange(fields, e.target.value)}
            rows={10}
            className="w-full rounded-xl border border-line bg-surface p-4 font-mono text-[13px] leading-relaxed outline-none focus:border-accent"
          />
        </Field>
      </section>
    </div>
  );
}
