/** Vide par défaut : les appels passent par le proxy /api de Next (même origine). */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export type OfferStatus = "new" | "interesse" | "ignore" | "postule" | "entretien";

export interface Offer {
  id: string;
  watch: string;
  url: string;
  title: string;
  company: string;
  location: string;
  contract: string;
  remote: string;
  salary: string;
  skills: string[];
  summary: string;
  contact: string;
  published: string;
  score: number;
  reasons: string[];
  red_flags: string[];
  status: OfferStatus;
  found_at: string;
  kept: boolean;
  source?: string | null;
  query?: string | null;
}

export interface SecretInfo {
  name: string;
  label: string;
  set: boolean;
  source: "app" | "env" | null;
  hint: string | null;
  env: string;
}

export interface ExpressOffer {
  title: string;
  company: string;
  location: string;
  url: string;
  source: string;
  score: number;
  reason: string;
  contract?: string;
}

export interface SearchLogEntry {
  source: string;
  label: string;
  query: string;
  count: number;
  error: string | null;
  ms: number;
}

export interface RunStats {
  tokens_in?: number;
  tokens_out?: number;
  llm_calls?: number;
  llm_cache_hits?: number;
  page_cache_hits?: number;
  search_cache_hits?: number;
  semantic_cache_hits?: number;
  pages_fetched?: number;
  already_seen?: number;
  offers_saved?: number;
  html_chars?: number;
  sent_chars?: number;
  injections_blocked?: number;
  unique_results?: number;
  kept_for_later?: number;
  jsonld_offers?: number;
  to_analyze?: number;
  direct_offers?: number;
  offers_near?: number;
  llm_failures?: number;
  search_results?: number;
  offers_extracted?: number;
  blocked_domains?: number;
  duration_s?: number;
  [key: string]: number | undefined;
}

export interface RunEvent {
  type: "event" | "end" | "progress" | "offer";
  kind?: string;
  message?: string;
  ts?: string;
  data?: Record<string, unknown>;
  status?: string;
  stats?: RunStats;
}

export interface Run {
  id: number;
  watch: string;
  trigger: string;
  status: "running" | "success" | "error" | "cancelled";
  started_at: string;
  finished_at: string | null;
  stats: RunStats;
  events: RunEvent[];
  error: string | null;
  report?: string | null;
}

export interface Watch {
  slug: string;
  nom: string;
  valid: boolean;
  error: string | null;
  actif: boolean;
  planning: string | null;
  notification: string | null;
  score_minimum: number | null;
  next_run: string | null;
  running: boolean;
  last_run: Run | null;
  offers_total: number;
  offers_new: number;
  offers_near: number;
  history: number[];
  connecteurs: string[];
  live: { run_id: number; offers_kept: number; progress: { stage: string; done: number; total: number; label: string } | null } | null;
  content?: string;
}

export interface Connector {
  id: string;
  label: string;
  description: string;
  free: boolean;
  key: string | null;
  speed: string;
  scope: string;
  configured: boolean;
}

export interface SetupStatus {
  llm: boolean;
  profile: boolean;
  watch: boolean;
  run: boolean;
  telegram: boolean;
}

export interface TimelineDay {
  date: string;
  offers: number;
  runs: number;
  tokens: number;
  already_seen: number;
  cache_hits: number;
}

export interface Timeline {
  days: TimelineDay[];
  scores: { label: string; count: number }[];
}

export interface Stats {
  runs: number;
  new_offers: number;
  offers_found: number;
  tokens: number;
  cache_hit_rate: number;
  already_seen_skipped: number;
  compression_rate: number;
  watches_active: number;
  watches_total: number;
}

export interface Validation {
  valid: boolean;
  error: string | null;
  next_runs: string[];
  body?: string;
  config?: Record<string, unknown> | null;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Appel JSON avec nouvelles tentatives si l'API redémarre (réseau coupé ou 502/503). */
export async function api<T>(path: string, init?: RequestInit, retries = 2): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    let res: Response;
    try {
      res = await fetch(`${API_URL}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
        cache: "no-store",
      });
    } catch (error) {
      if ((error as Error).name === "AbortError") throw error;
      if (attempt < retries) {
        await sleep(800 * (attempt + 1));
        continue;
      }
      throw new Error("API injoignable : vérifie que les conteneurs tournent (docker compose ps).");
    }
    const idempotent = !init?.method || init.method === "GET";
    if ((res.status === 502 || res.status === 503) && idempotent && attempt < retries) {
      await sleep(800 * (attempt + 1));
      continue;
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const detail = Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join(", ") : body.detail;
      throw new Error(detail ?? `Erreur ${res.status}`);
    }
    return res.status === 204 ? (undefined as T) : res.json();
  }
}

/** Lit un flux SSE (GET ou POST) et appelle onEvent pour chaque message JSON. */
export async function streamSSE<T>(
  path: string,
  onEvent: (event: T) => void,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...(init?.headers ?? {}) },
  });
  if (!res.ok || !res.body) {
    if (res.status === 503 || res.status === 502) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail ?? "API indisponible");
    }
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Erreur ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      if (init?.signal?.aborted) return;
      const data = block
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) {
        try {
          onEvent(JSON.parse(data) as T);
        } catch {
          /* ping ou message non JSON */
        }
      }
    }
  }
}

export type RoutingMode = "fixe" | "intelligent" | "performance";

export interface LLMSettings {
  routing: RoutingMode;
  chain: string[];
  models: Record<string, { fast?: string; strong?: string }>;
  escalate_chars: number;
  exploration: number;
  concurrency: number;
}

export interface ProviderInfo {
  id: string;
  label: string;
  configured: boolean;
  key_env: string | null;
  free_tier: boolean;
  note: string;
  keys_url: string;
  local: boolean;
  defaults: { fast: string; strong: string };
  models: { fast: string; strong: string };
  in_chain: boolean;
  priority: number | null;
}

export interface LLMOverview {
  settings: LLMSettings;
  providers: ProviderInfo[];
  blocked: Record<string, { reason: string; seconds: number }>;
  tasks: Record<string, string>;
}

export interface LLMStats {
  models: { provider: string; label: string; model: string; calls: number; success: number; latency_ms: number; tokens: number; score: number | null }[];
  tasks: { task: string; label: string; calls: number; success: number }[];
  errors: { provider: string; model: string; error: string; ts: string }[];
}

export interface Health {
  status: string;
  routing: RoutingMode;
  provider: string | null;
  providers_ready: number;
}
