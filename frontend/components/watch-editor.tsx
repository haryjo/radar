"use client";

import clsx from "clsx";
import { CheckCircle2, Code2, Eye, ListChecks, Play, Save, Trash2, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Validation, type Watch } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { Markdown } from "./markdown";
import { useToast } from "./toast";
import { Button, Card, ErrorNote, PageHeader, ButtonLink } from "./ui";
import { WatchForm, toMarkdown, type WatchFields } from "./watch-form";

function slugify(text: string) {
  return text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);
}

function bodyOf(content: string) {
  return content.replace(/^---[\s\S]*?---\s*/, "");
}

export function WatchEditor({ slug, initial, embedded = false }: { slug?: string; initial: string; embedded?: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const isNew = !slug;
  const [content, setContent] = useState(initial);
  const [newSlug, setNewSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [validation, setValidation] = useState<Validation | null>(null);
  const [tab, setTab] = useState<"form" | "edit" | "preview">("form");
  const [form, setForm] = useState<{ fields: WatchFields; body: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [baseline, setBaseline] = useState(initial);
  const dirty = content !== baseline;

  // Lecture initiale du fichier pour remplir le formulaire
  useEffect(() => {
    api<Validation>("/api/watches/validate", { method: "POST", body: JSON.stringify({ content: initial }) })
      .then((v) => {
        setValidation(v);
        if (v.config) setForm({ fields: v.config as unknown as WatchFields, body: v.body ?? "" });
        else setTab("edit");
      })
      .catch(() => setTab("edit"));
  }, [initial]);

  function onFormChange(fields: WatchFields, body: string) {
    setForm({ fields, body });
    setContent(toMarkdown(fields, body));
    if (isNew && !slugTouched) setNewSlug(slugify(fields.nom));
  }

  async function switchTab(next: "form" | "edit" | "preview") {
    if (next === "form" && tab !== "form") {
      // Relecture immédiate du Markdown courant (pas de version périmée)
      const fresh = await api<Validation>("/api/watches/validate", { method: "POST", body: JSON.stringify({ content }) }).catch(() => null);
      if (!fresh?.config) {
        setError("Le fichier contient une erreur : corrige-la dans l'onglet Markdown avant de revenir au formulaire.");
        return;
      }
      setValidation(fresh);
      setForm({ fields: fresh.config as unknown as WatchFields, body: fresh.body ?? "" });
    }
    setError(null);
    setTab(next);
  }

  // Validation en direct de l'en-tête YAML (même code Pydantic que le serveur).
  useEffect(() => {
    const handle = setTimeout(() => {
      api<Validation>("/api/watches/validate", { method: "POST", body: JSON.stringify({ content }) })
        .then(setValidation)
        .catch(() => null);
    }, 400);
    return () => clearTimeout(handle);
  }, [content]);

  async function save(andRun = false) {
    setSaving(true);
    setError(null);
    try {
      const watch = isNew
        ? await api<Watch>("/api/watches", { method: "POST", body: JSON.stringify({ slug: newSlug, content }) })
        : await api<Watch>(`/api/watches/${slug}`, { method: "PUT", body: JSON.stringify({ content }) });
      if (andRun) {
        const { run_id } = await api<{ run_id: number }>(`/api/watches/${watch.slug}/run`, { method: "POST" });
        router.push(`/historique/${run_id}`);
        return;
      }
      if (isNew) router.push(`/veilles/${watch.slug}`);
      else {
        setBaseline(content);
        toast("Veille enregistrée et replanifiée.");
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!slug || !window.confirm("Supprimer définitivement ce fichier de veille ?")) return;
    try {
      await api(`/api/watches/${slug}`, { method: "DELETE" });
      toast("Veille supprimée.");
      router.push("/veilles");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  const canSave = validation?.valid && (isNew ? /^[a-z0-9][a-z0-9-]{1,60}$/.test(newSlug) : dirty);
  const ACTIONS = (<>
            {!isNew && <Button variant="danger" onClick={remove}><Trash2 className="size-4" /></Button>}
            <ButtonLink href="/veilles" variant="ghost">Annuler</ButtonLink>
            <Button onClick={() => save(true)} disabled={!validation?.valid || (isNew && !canSave)} loading={saving}>
              <Play className="size-4" />{isNew || dirty ? "Enregistrer et lancer" : "Lancer"}
            </Button>
            <Button variant="primary" onClick={() => save(false)} disabled={!canSave} loading={saving}>
              <Save className="size-4" />{saved ? "Enregistré" : "Enregistrer"}
            </Button>
          </>);


  return (
    <>
      {embedded ? (
        <div className="mb-4 flex flex-wrap items-center justify-end gap-2">{ACTIONS}</div>
      ) : (
        <PageHeader
          title={isNew ? "Nouvelle veille" : "Modifier la veille"}
          description={isNew ? "Décris ce que tu cherches : l'agent s'occupe du reste, selon le planning choisi." : `config/veilles/${slug}.md`}
          actions={ACTIONS}
        />
      )}

      {isNew && (
        <label className="mb-4 block">
          <span className="text-[13px] text-muted">Identifiant du fichier</span>
          <div className="mt-1 flex items-center rounded-xl border border-line bg-surface px-3 focus-within:border-accent">
            <span className="font-mono text-[13px] text-muted">veilles/</span>
            <input value={newSlug} onChange={(e) => { setSlugTouched(true); setNewSlug(e.target.value.toLowerCase()); }} placeholder="stage-data-tana" className="h-9 flex-1 bg-transparent font-mono text-[13px] outline-none" />
            <span className="font-mono text-[13px] text-muted">.md</span>
          </div>
        </label>
      )}

      {error && <div className="mb-4"><ErrorNote message={error} /></div>}

      <div className="grid items-start gap-4 lg:grid-cols-[1fr_260px]">
        <Card className="overflow-hidden">
          <div className="flex border-b border-line px-2">
            {([["form", "Formulaire", ListChecks], ["edit", "Markdown", Code2], ["preview", "Aperçu", Eye]] as const).map(([t, label, Icon]) => (
              <button key={t} onClick={() => switchTab(t)} className={clsx("inline-flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-[13px]", tab === t ? "border-accent font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
                <Icon className="size-3.5" />{label}
              </button>
            ))}
          </div>
          {tab === "form" ? (
            <div className="p-5">
              {form ? <WatchForm fields={form.fields} body={form.body} onChange={onFormChange} /> : <p className="text-sm text-muted">Chargement…</p>}
            </div>
          ) : tab === "edit" ? (
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              spellCheck={false}
              className="scroll-thin block h-[60vh] w-full resize-none bg-surface p-4 font-mono text-[13px] leading-relaxed outline-none"
            />
          ) : (
            <div className="scroll-thin h-[60vh] overflow-auto p-5"><Markdown>{bodyOf(content)}</Markdown></div>
          )}
        </Card>

        <div className="space-y-3">
          <Card className="p-4 lg:sticky lg:top-6">
            {validation?.valid ? (
              <p className="flex items-center gap-1.5 text-sm font-medium text-success"><CheckCircle2 className="size-4" />Fichier valide</p>
            ) : (
              <p className="flex items-center gap-1.5 text-sm font-medium text-danger"><XCircle className="size-4" />Fichier invalide</p>
            )}
            {validation?.error && <p className="mt-2 text-[13px] text-danger">{validation.error}</p>}
            {validation?.next_runs && validation.next_runs.length > 0 && (
              <div className="mt-3">
                <p className="text-[11px] uppercase tracking-wide text-muted">Prochaines exécutions</p>
                <ul className="mt-1 space-y-0.5 text-[13px]">
                  {validation.next_runs.map((t) => <li key={t}>{dateTime(t)}</li>)}
                </ul>
              </div>
            )}
          </Card>
          <Card className="p-4 text-[12px] leading-relaxed text-muted">
            <p className="mb-1.5 font-medium text-ink">Bon à savoir</p>
            <p>Le formulaire et le mode Markdown modifient le même fichier : <code>config/veilles/{slug ?? (newSlug || "…")}.md</code>.</p>
            <p className="mt-2">Pour aller vite, active au moins une API d'offres (Jobicy, Himalayas…) en plus de la recherche web.</p>
          </Card>
        </div>
      </div>
    </>
  );
}
