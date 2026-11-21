"use client";

import clsx from "clsx";
import {
  AlertTriangle, ArrowDown, ChevronDown, ArrowUp, Brain, CheckCircle2, Gauge, KeyRound, ListRestart, Lock, Pin, RefreshCw, Save, Sparkles, Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { BarChart } from "@/components/charts";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardTitle, ErrorNote, PageHeader, Skeleton } from "@/components/ui";
import { KeyField } from "@/components/key-field";
import { api, type SecretInfo, type LLMOverview, type LLMSettings, type LLMStats, type ProviderInfo, type RoutingMode } from "@/lib/api";
import { compact, hueOf, initials } from "@/lib/format";

const MODES: { value: RoutingMode; title: string; icon: typeof Pin; text: string }[] = [
  { value: "fixe", title: "Fixe", icon: Pin, text: "Toujours le premier fournisseur actif. Prévisible, sans bascule." },
  {
    value: "intelligent", title: "Intelligent", icon: Brain,
    text: "Modèle rapide pour trier et extraire, puissant pour noter et rédiger. Entrée longue : montée en gamme. Bascule automatique en cas d'erreur.",
  },
  {
    value: "performance", title: "Performance", icon: Gauge,
    text: "Classe les modèles selon leurs résultats réels (réponses valides, latence) et teste parfois les autres.",
  },
];

interface TestResult {
  ok: boolean;
  latency_ms: number;
  reply?: string;
  error?: string;
}

const DOMAINS: Record<string, string> = {
  groq: "groq.com", gemini: "gemini.google.com", openai: "openai.com", anthropic: "claude.ai",
  mistral: "mistral.ai", openrouter: "openrouter.ai", ollama: "ollama.com",
};

/** Logo du fournisseur (favicon de son site, chargé à l'affichage) avec repli sur un monogramme. */
function ProviderLogo({ provider, size = 40 }: { provider: ProviderInfo; size?: number }) {
  const [failed, setFailed] = useState(false);
  const hue = hueOf(provider.id);
  const domain = DOMAINS[provider.id];
  return (
    <span
      className="grid shrink-0 place-items-center overflow-hidden rounded-xl border border-line bg-white text-[13px] font-semibold"
      style={{ width: size, height: size, ...(failed || !domain ? {
        background: `color-mix(in oklch, oklch(0.7 0.12 ${hue}) 16%, var(--surface))`,
        color: `color-mix(in oklch, oklch(0.6 0.14 ${hue}) 75%, var(--ink))`,
      } : {}) }}
    >
      {failed || !domain ? initials(provider.label) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`} alt="" width={size * 0.55} height={size * 0.55}
          onError={() => setFailed(true)} className="object-contain" />
      )}
    </span>
  );
}

const PRESETS: { id: string; title: string; text: string; icon: typeof Pin; routing: RoutingMode; chain: string[] }[] = [
  { id: "free", title: "Gratuit et rapide", text: "Groq puis Gemini, Mistral et OpenRouter en secours.", icon: Zap, routing: "intelligent", chain: ["groq", "gemini", "mistral", "openrouter"] },
  { id: "quality", title: "Qualité maximale", text: "Claude et ChatGPT, classés selon leurs résultats.", icon: Sparkles, routing: "performance", chain: ["anthropic", "openai", "gemini"] },
  { id: "local", title: "100 % local", text: "Ollama sur ta machine, aucune donnée ne sort.", icon: Lock, routing: "fixe", chain: ["ollama"] },
];

export default function ModelsPage() {
  const toast = useToast();
  const [overview, setOverview] = useState<LLMOverview | null>(null);
  const [draft, setDraft] = useState<LLMSettings | null>(null);
  const [stats, setStats] = useState<LLMStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tests, setTests] = useState<Record<string, TestResult | "loading">>({});
  const [catalog, setCatalog] = useState<Record<string, string[]>>({});
  const [secrets, setSecrets] = useState<SecretInfo[]>([]);

  const load = useCallback(() => {
    api<LLMOverview>("/api/llm")
      .then((data) => {
        setOverview(data);
        setDraft(data.settings);
      })
      .catch((e: Error) => setError(e.message));
    api<LLMStats>("/api/llm/stats?days=7").then(setStats).catch(() => null);
    api<SecretInfo[]>("/api/secrets").then(setSecrets).catch(() => null);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const providers = useMemo(() => {
    if (!overview || !draft) return [];
    const order = new Map(draft.chain.map((id, i) => [id, i]));
    return [...overview.providers].sort((a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99) || Number(b.configured) - Number(a.configured));
  }, [overview, draft]);

  if (error) return <ErrorNote message={error} />;
  if (!overview || !draft) return <Skeleton className="h-[70vh]" />;

  const dirty = JSON.stringify(draft) !== JSON.stringify(overview.settings);

  function update(patch: Partial<LLMSettings>) {
    setDraft((d) => (d ? { ...d, ...patch } : d));
  }

  function toggle(id: string) {
    const chain = draft!.chain.includes(id) ? draft!.chain.filter((p) => p !== id) : [...draft!.chain, id];
    update({ chain });
  }

  function move(id: string, delta: number) {
    const chain = [...draft!.chain];
    const i = chain.indexOf(id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= chain.length) return;
    [chain[i], chain[j]] = [chain[j], chain[i]];
    update({ chain });
  }

  function setModel(id: string, tier: "fast" | "strong", value: string) {
    update({ models: { ...draft!.models, [id]: { ...draft!.models[id], [tier]: value } } });
  }

  function modelOf(p: ProviderInfo, tier: "fast" | "strong") {
    return draft!.models[p.id]?.[tier] ?? p.models[tier];
  }

  async function save() {
    setSaving(true);
    try {
      const data = await api<LLMOverview>("/api/llm/settings", { method: "PUT", body: JSON.stringify(draft) });
      setOverview(data);
      setDraft(data.settings);
      toast("Réglages enregistrés : ils s'appliquent dès le prochain appel.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function test(p: ProviderInfo, tier: "fast" | "strong") {
    const key = `${p.id}:${tier}`;
    setTests((t) => ({ ...t, [key]: "loading" }));
    try {
      const result = await api<TestResult>("/api/llm/test", { method: "POST", body: JSON.stringify({ provider: p.id, model: modelOf(p, tier) }) });
      setTests((t) => ({ ...t, [key]: result }));
    } catch (e) {
      setTests((t) => ({ ...t, [key]: { ok: false, latency_ms: 0, error: (e as Error).message } }));
    }
  }

  async function loadCatalog(p: ProviderInfo) {
    try {
      const { models } = await api<{ models: string[] }>(`/api/llm/providers/${p.id}/models`);
      setCatalog((c) => ({ ...c, [p.id]: models }));
      toast(`${models.length} modèles disponibles chez ${p.label}`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  const activeCount = draft.chain.filter((id) => overview.providers.find((p) => p.id === id)?.configured).length;

  return (
    <>
      <PageHeader
        eyebrow="Intelligence"
        title="Modèles"
        description="Choisis tes fournisseurs LLM, leur ordre de priorité et la façon dont l'agent les répartit entre les tâches."
        actions={
          <>
            <Button variant="ghost" onClick={load}><RefreshCw className="size-4" />Actualiser</Button>
            <Button variant="primary" onClick={save} disabled={!dirty || draft.chain.length === 0} loading={saving}>
              <Save className="size-4" />Enregistrer
            </Button>
          </>
        }
      />

      {activeCount === 0 && (
        <div className="mb-5"><ErrorNote message="Aucun fournisseur actif n'a de clé API : ajoute par exemple GROQ_API_KEY ou GEMINI_API_KEY (gratuites) dans .env, puis redémarre avec docker compose up -d." /></div>
      )}

      {/* Préréglages */}
      <div className="mb-3">
        <h2 className="font-semibold tracking-tight">Démarrage rapide</h2>
        <p className="text-[13px] text-muted">Un préréglage remplit fournisseurs et routage ; tu peux ensuite tout ajuster.</p>
      </div>
      <div className="mb-8 grid gap-3 md:grid-cols-3">
        {PRESETS.map((preset) => {
          const missing = preset.chain.filter((id) => !overview.providers.find((p) => p.id === id)?.configured);
          const usable = preset.chain.length - missing.length;
          const applied = draft.routing === preset.routing && JSON.stringify(draft.chain) === JSON.stringify(preset.chain);
          return (
            <button
              key={preset.id}
              onClick={() => update({ routing: preset.routing, chain: preset.chain })}
              className={clsx("rounded-2xl border bg-surface p-4 text-left shadow-card transition-all",
                applied ? "border-accent ring-4 ring-accent-soft" : "border-line hover:border-ink/15")}
            >
              <div className="flex items-center gap-2">
                <preset.icon className="size-4 text-accent" />
                <span className="font-medium">{preset.title}</span>
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-muted">{preset.text}</p>
              <div className="mt-3 flex items-center gap-1.5">
                {preset.chain.map((id) => {
                  const provider = overview.providers.find((p) => p.id === id)!;
                  return (
                    <span key={id} className={clsx(!provider.configured && "opacity-35 grayscale")} title={`${provider.label}${provider.configured ? "" : " (clé manquante)"}`}>
                      <ProviderLogo provider={provider} size={26} />
                    </span>
                  );
                })}
                <span className={clsx("ml-auto text-[11px]", usable ? "text-muted" : "text-warning")}>
                  {usable ? `${usable}/${preset.chain.length} prêt${usable > 1 ? "s" : ""}` : "aucune clé"}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Mode de routage */}
      <h2 className="mb-3 font-semibold tracking-tight">Répartition entre les modèles</h2>
      <div className="mb-8 grid gap-3 md:grid-cols-3">
        {MODES.map(({ value, title, icon: Icon, text }) => {
          const selected = draft.routing === value;
          return (
            <button
              key={value}
              onClick={() => update({ routing: value })}
              className={clsx(
                "relative rounded-2xl border bg-surface p-5 text-left shadow-card transition-all",
                selected ? "border-accent ring-4 ring-accent-soft" : "border-line hover:border-ink/15",
              )}
            >
              {selected && <CheckCircle2 className="absolute right-4 top-4 size-4 text-accent" />}
              <span className={clsx("mb-3 grid size-9 place-items-center rounded-xl", selected ? "bg-accent text-white" : "bg-raised text-muted")}>
                <Icon className="size-4" />
              </span>
              <p className="font-medium">{title}</p>
              <p className="mt-1 text-[13px] leading-relaxed text-muted">{text}</p>
            </button>
          );
        })}
      </div>

      {/* Fournisseurs */}
      <div className="mb-3 flex items-end justify-between">
        <div>
          <h2 className="font-semibold tracking-tight">Fournisseurs</h2>
          <p className="text-[13px] text-muted">Active ceux à utiliser et ordonne-les : le premier est prioritaire, les suivants servent de secours.</p>
        </div>
      </div>
      <div className="mb-10 space-y-3">
        {providers.map((p, index) => {
          const active = draft.chain.includes(p.id);
          const firstInactive = !active && (index === 0 || draft.chain.includes(providers[index - 1].id));
          const position = draft.chain.indexOf(p.id);
          return (
            <div key={p.id}>
            {firstInactive && <p className="mb-2 mt-6 text-[12px] font-medium uppercase tracking-wide text-muted">Autres fournisseurs disponibles</p>}
            <Card className={clsx("transition-all", active ? "p-5" : "p-4 opacity-80 hover:opacity-100")}>
              <div className="flex flex-wrap items-start gap-4">
                <ProviderLogo provider={p} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium">{p.label}</p>
                    {active && <Badge tone="accent">{position === 0 ? "Principal" : `Secours n° ${position}`}</Badge>}
                    {p.configured ? (
                      <Badge tone="green" dot>{p.local ? "Local" : "Clé configurée"}</Badge>
                    ) : (
                      <Badge tone="amber"><KeyRound className="size-3" />{p.key_env} manquante</Badge>
                    )}
                    {p.free_tier && <Badge>Offre gratuite</Badge>}
                  </div>
                  <p className="mt-1 text-[13px] text-muted">
                    {p.note}{" "}
                    {!p.configured && p.keys_url && (
                      <a href={p.keys_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">Obtenir une clé</a>
                    )}
                  </p>
                  {!p.local && secrets.find((x) => x.name === p.id) && (
                    <div className="mt-2.5 max-w-xl">
                      <KeyField
                        secret={secrets.find((x) => x.name === p.id)!}
                        onChange={(next) => {
                          setSecrets((all) => all.map((x) => (x.name === next.name ? next : x)));
                          load();
                        }}
                      />
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  {active && (
                    <>
                      <Button size="sm" variant="ghost" onClick={() => move(p.id, -1)} disabled={position === 0} aria-label="Monter"><ArrowUp className="size-4" /></Button>
                      <Button size="sm" variant="ghost" onClick={() => move(p.id, 1)} disabled={position === draft.chain.length - 1} aria-label="Descendre"><ArrowDown className="size-4" /></Button>
                    </>
                  )}
                  <button
                    role="switch"
                    aria-checked={active}
                    onClick={() => toggle(p.id)}
                    className={clsx("relative ml-1 h-6 w-11 rounded-full transition-colors", active ? "bg-accent" : "bg-ink/15")}
                  >
                    <span className={clsx("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", active ? "left-[22px]" : "left-0.5")} />
                  </button>
                </div>
              </div>

              {active && (<>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {(["fast", "strong"] as const).map((tier) => {
                  const result = tests[`${p.id}:${tier}`];
                  return (
                    <div key={tier} className="rounded-xl border border-line bg-raised/50 p-3">
                      <div className="mb-1.5 flex items-center justify-between">
                        <span className="flex items-center gap-1.5 text-[12px] font-medium">
                          {tier === "fast" ? <Zap className="size-3.5 text-chart-2" /> : <Sparkles className="size-3.5 text-accent" />}
                          {tier === "fast" ? "Rapide · tri, extraction" : "Puissant · notation, synthèse, chat"}
                        </span>
                        {result && result !== "loading" && (
                          <span className={clsx("text-[11px]", result.ok ? "text-success" : "text-danger")}>
                            {result.ok ? `OK · ${result.latency_ms} ms` : "Échec"}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-1.5">
                        <input
                          value={modelOf(p, tier)}
                          onChange={(e) => setModel(p.id, tier, e.target.value)}
                          list={`models-${p.id}`}
                          spellCheck={false}
                          className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 font-mono text-[12px] outline-none focus:border-accent"
                        />
                        <Button size="sm" onClick={() => test(p, tier)} loading={result === "loading"} disabled={!p.configured}>Tester</Button>
                      </div>
                      {result && result !== "loading" && !result.ok && <p className="mt-1.5 line-clamp-2 text-[11px] text-danger">{result.error}</p>}
                    </div>
                  );
                })}
              </div>
              <div className="mt-2 flex items-center gap-3 text-[11px] text-muted">
                <button onClick={() => loadCatalog(p)} disabled={!p.configured} className="inline-flex items-center gap-1 hover:text-ink disabled:opacity-40">
                  <ListRestart className="size-3" />Charger la liste des modèles
                </button>
                <span>Par défaut : {p.defaults.fast} / {p.defaults.strong}</span>
              </div>
              <datalist id={`models-${p.id}`}>
                {(catalog[p.id] ?? []).map((m) => <option key={m} value={m} />)}
              </datalist>
              </>)}
            </Card>
            </div>
          );
        })}
      </div>

      {/* Autres intégrations */}
      <h2 className="mb-1 font-semibold tracking-tight">Autres clés</h2>
      <p className="mb-3 text-[13px] text-muted">Chiffrées sur le serveur, jamais réaffichées. Une clé saisie ici remplace celle de .env.</p>
      <Card className="mb-10 divide-y divide-line">
        {[
          { name: "apify", title: "Apify", text: "Pour la source « Apify » des veilles (scraping via un Actor).", url: "https://console.apify.com/settings/integrations" },
          { name: "telegram_bot_token", title: "Bot Telegram", text: "Jeton donné par @BotFather, pour recevoir les nouvelles offres.", url: "https://t.me/BotFather" },
          { name: "telegram_chat_id", title: "Identifiant de chat Telegram", text: "Ton chat_id (écris d'abord un message à ton bot).", url: "" },
        ].map((item) => {
          const secret = secrets.find((x) => x.name === item.name);
          return (
            <div key={item.name} className="grid gap-3 p-5 md:grid-cols-[1fr_minmax(0,1.3fr)] md:items-center">
              <div>
                <p className="text-sm font-medium">{item.title}</p>
                <p className="text-[12px] text-muted">
                  {item.text}{" "}
                  {item.url && <a href={item.url} target="_blank" rel="noreferrer" className="text-accent hover:underline">Ouvrir</a>}
                </p>
              </div>
              {secret && (
                <KeyField
                  secret={secret}
                  placeholder={item.name === "telegram_chat_id" ? "123456789" : undefined}
                  onChange={(next) => setSecrets((all) => all.map((x) => (x.name === next.name ? next : x)))}
                />
              )}
            </div>
          );
        })}
      </Card>

      {/* Réglages avancés */}
      <Card className="mb-10 grid gap-5 p-5 md:grid-cols-3">
        <label className="block">
          <span className="text-[13px] font-medium">Montée en gamme</span>
          <span className="block text-[12px] text-muted">Taille d'entrée (caractères) au-delà de laquelle le modèle puissant est utilisé.</span>
          <input type="number" min={2000} step={1000} value={draft.escalate_chars} onChange={(e) => update({ escalate_chars: Number(e.target.value) })}
            className="mt-2 h-8 w-full rounded-lg border border-line bg-surface px-2.5 text-sm outline-none focus:border-accent" />
        </label>
        <label className="block">
          <span className="text-[13px] font-medium">Exploration : {Math.round(draft.exploration * 100)} %</span>
          <span className="block text-[12px] text-muted">Mode performance : part des appels qui testent un autre modèle.</span>
          <input type="range" min={0} max={0.5} step={0.05} value={draft.exploration} onChange={(e) => update({ exploration: Number(e.target.value) })}
            className="mt-3 w-full accent-[var(--accent)]" />
        </label>
        <label className="block">
          <span className="text-[13px] font-medium">Appels simultanés par fournisseur</span>
          <span className="block text-[12px] text-muted">Baisse à 1 si tu atteins souvent le quota gratuit.</span>
          <input type="number" min={1} max={8} value={draft.concurrency} onChange={(e) => update({ concurrency: Number(e.target.value) })}
            className="mt-2 h-8 w-full rounded-lg border border-line bg-surface px-2.5 text-sm outline-none focus:border-accent" />
        </label>
      </Card>

      {/* Performance mesurée */}
      <h2 className="mb-3 font-semibold tracking-tight">Performance mesurée (7 jours)</h2>
      {!stats || stats.models.length === 0 ? (
        <Card className="p-6 text-center text-sm text-muted">Aucun appel enregistré pour l'instant. Lance une veille ou un test.</Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          <Card className="p-5">
            <CardTitle>Taux de réussite par modèle</CardTitle>
            <BarChart data={stats.models.slice(0, 8).map((m) => ({ label: m.model.split("/").pop()!.slice(0, 14), value: Math.round(m.success * 100) }))}
              height={170} color="var(--chart-2)" max={100} format={(v) => `${Math.round(v)} %`} />
          </Card>
          <Card className="overflow-hidden">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-muted">
                  <th className="px-4 py-2.5 font-medium">Modèle</th>
                  <th className="px-3 py-2.5 text-right font-medium">Appels</th>
                  <th className="px-3 py-2.5 text-right font-medium">Réussite</th>
                  <th className="px-3 py-2.5 text-right font-medium">Latence</th>
                  <th className="px-4 py-2.5 text-right font-medium">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {stats.models.map((m) => (
                  <tr key={`${m.provider}/${m.model}`} className="border-b border-line last:border-0">
                    <td className="max-w-0 px-4 py-2.5">
                      <p className="truncate font-mono text-[12px]">{m.model}</p>
                      <p className="text-[11px] text-muted">{m.label}{overview.blocked[`${m.provider}/${m.model}`] && <span className="ml-1 inline-flex items-center gap-0.5 text-warning"><Lock className="size-3" />en pause</span>}</p>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{m.calls}</td>
                    <td className={clsx("px-3 py-2.5 text-right tabular-nums", m.success < 0.8 ? "text-warning" : "text-success")}>{Math.round(m.success * 100)} %</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{m.latency_ms ? `${(m.latency_ms / 1000).toFixed(1)} s` : "–"}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{compact(m.tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          {stats.errors.length > 0 && (
            <Card className="overflow-hidden lg:col-span-2">
              <details className="group">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-[13px] font-medium hover:bg-raised/50">
                  <span className="inline-flex items-center gap-2">
                    <AlertTriangle className="size-4 text-warning" />
                    Dernières erreurs
                    <span className="rounded-full bg-warning/15 px-1.5 text-[11px] text-warning">{stats.errors.length}</span>
                  </span>
                  <ChevronDown className="size-4 text-muted transition-transform group-open:rotate-180" />
                </summary>
                <ul className="space-y-2.5 border-t border-line px-5 py-4 text-[12px]">
                  {stats.errors.map((e, i) => (
                    <li key={i} className="grid gap-0.5 sm:grid-cols-[180px_1fr] sm:gap-3">
                      <span className="truncate font-mono text-muted">{e.model}</span>
                      <span className="break-words text-danger">{e.error}</span>
                    </li>
                  ))}
                </ul>
              </details>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
