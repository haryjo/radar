"use client";

import clsx from "clsx";
import { Bot, FileText, Save, SlidersHorizontal, Star } from "lucide-react";
import { useEffect, useState } from "react";
import { Markdown } from "@/components/markdown";
import { useToast } from "@/components/toast";
import { Button, Card, PageHeader, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

const FILES = [
  { name: "cv", label: "CV", icon: FileText, help: "Tes compétences, expériences et langues. L'agent y cherche les passages utiles pour noter chaque offre." },
  { name: "preferences", label: "Préférences", icon: Star, help: "Contrats, lieux, domaines et ce que tu veux éviter. Toujours pris en compte à la notation." },
  { name: "agent", label: "Règles de l'agent", icon: Bot, help: "Comportement général de l'agent, valable pour toutes les veilles (AGENT.md)." },
  { name: "scoring", label: "Grille de notation", icon: SlidersHorizontal, help: "Comment une offre est notée sur 100 (scoring.md)." },
] as const;

type FileName = (typeof FILES)[number]["name"];

export default function ProfilePage() {
  const toast = useToast();
  const [active, setActive] = useState<FileName>("cv");
  const [contents, setContents] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState<Record<string, string>>({});
  const [tab, setTab] = useState<"edit" | "preview">("edit");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all(FILES.map((f) => api<{ name: string; content: string }>(`/api/files/${f.name}`)))
      .then((all) => {
        const map = Object.fromEntries(all.map((f) => [f.name, f.content]));
        setContents(map);
        setSaved(map);
      })
      .catch((e: Error) => toast(e.message, "error"));
  }, [toast]);

  const file = FILES.find((f) => f.name === active)!;
  const dirty = contents[active] !== saved[active];

  async function save() {
    setSaving(true);
    try {
      const result = await api<{ content: string }>(`/api/files/${active}`, { method: "PUT", body: JSON.stringify({ content: contents[active] }) });
      setSaved((s) => ({ ...s, [active]: result.content }));
      toast(active === "cv" || active === "preferences" ? "Enregistré : le profil est réindexé pour la notation." : "Enregistré.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Personnalisation"
        title="Profil"
        description="Ce que l'agent sait de toi et comment il juge les offres. Plus c'est précis, meilleure est la notation."
        actions={<Button variant="primary" onClick={save} disabled={!dirty} loading={saving}><Save className="size-4" />Enregistrer</Button>}
      />
      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        <nav className="flex gap-1 overflow-x-auto lg:flex-col">
          {FILES.map((f) => {
            const changed = contents[f.name] !== saved[f.name];
            return (
              <button
                key={f.name}
                onClick={() => setActive(f.name)}
                className={clsx(
                  "flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                  active === f.name ? "bg-surface font-medium shadow-card ring-1 ring-line" : "text-muted hover:bg-ink/[0.04] hover:text-ink",
                )}
              >
                <f.icon className={clsx("size-4", active === f.name && "text-accent")} />
                {f.label}
                {changed && <span className="ml-auto size-1.5 rounded-full bg-warning" title="Non enregistré" />}
              </button>
            );
          })}
        </nav>

        <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
            <p className="text-[13px] text-muted">{file.help}</p>
            <div className="flex rounded-lg border border-line p-0.5">
              {(["edit", "preview"] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)} className={clsx("rounded-md px-2.5 py-1 text-[12px]", tab === t ? "bg-raised font-medium" : "text-muted")}>
                  {t === "edit" ? "Modifier" : "Aperçu"}
                </button>
              ))}
            </div>
          </div>
          {contents[active] === undefined ? (
            <Skeleton className="m-4 h-96" />
          ) : tab === "edit" ? (
            <textarea
              value={contents[active]}
              onChange={(e) => setContents((c) => ({ ...c, [active]: e.target.value }))}
              spellCheck={false}
              className="scroll-thin block h-[62vh] w-full resize-none bg-surface p-5 font-mono text-[13px] leading-relaxed outline-none"
            />
          ) : (
            <div className="scroll-thin h-[62vh] overflow-auto p-6"><Markdown>{contents[active]}</Markdown></div>
          )}
        </Card>
      </div>
    </>
  );
}
