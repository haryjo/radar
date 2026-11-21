"use client";

import clsx from "clsx";
import { ArrowRight, Check, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type SetupStatus } from "@/lib/api";
import { Card } from "./ui";

const STEPS: { key: keyof SetupStatus; title: string; text: string; href: string; cta: string }[] = [
  { key: "llm", title: "Connecter un modèle d'IA", text: "Ajoute une clé gratuite (Groq ou Gemini) dans .env, puis teste-la.", href: "/modeles", cta: "Modèles" },
  { key: "profile", title: "Décrire ton profil", text: "Complète ton CV et tes préférences : la notation des offres s'appuie dessus.", href: "/profil", cta: "Mon profil" },
  { key: "watch", title: "Créer une veille", text: "Ce que tu cherches, où, et à quelle fréquence.", href: "/veilles/nouvelle", cta: "Créer" },
  { key: "run", title: "Lancer une première recherche", text: "Suis l'agent en direct et découvre tes premières offres.", href: "/veilles", cta: "Lancer" },
];

/** Liste « Bien démarrer » : disparaît d'elle-même quand tout est prêt (ou si on la ferme). */
export function Onboarding() {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    try {
      setHidden(localStorage.getItem("onboarding-hidden") === "1");
    } catch {
      setHidden(false);
    }
    api<SetupStatus>("/api/setup").then(setStatus).catch(() => null);
  }, []);

  if (!status || hidden) return null;
  const done = STEPS.filter((s) => status[s.key]).length;
  if (done === STEPS.length) return null;
  const next = STEPS.find((s) => !status[s.key]);

  return (
    <Card className="relative mb-6 overflow-hidden p-5">
      <div className="absolute inset-x-0 top-0 h-1 bg-ink/[0.06]">
        <div className="h-full bg-accent transition-all" style={{ width: `${(done / STEPS.length) * 100}%` }} />
      </div>
      <button
        onClick={() => {
          try {
            localStorage.setItem("onboarding-hidden", "1");
          } catch {}
          setHidden(true);
        }}
        className="absolute right-3 top-3 text-muted hover:text-ink"
        aria-label="Masquer"
      >
        <X className="size-4" />
      </button>
      <p className="font-medium">Bien démarrer</p>
      <p className="text-[13px] text-muted">{done} étape{done > 1 ? "s" : ""} sur {STEPS.length} terminée{done > 1 ? "s" : ""}</p>
      <ol className="mt-4 grid gap-2 md:grid-cols-4">
        {STEPS.map((step, i) => {
          const ok = status[step.key];
          const isNext = step === next;
          return (
            <li key={step.key} className={clsx("rounded-xl border p-3.5", isNext ? "border-accent bg-accent-soft/40" : "border-line")}>
              <div className="flex items-center gap-2">
                <span className={clsx("grid size-5 place-items-center rounded-full text-[11px] font-semibold", ok ? "bg-success text-white" : isNext ? "bg-accent text-white" : "bg-ink/[0.08] text-muted")}>
                  {ok ? <Check className="size-3" /> : i + 1}
                </span>
                <span className={clsx("text-[13px] font-medium", ok && "text-muted line-through")}>{step.title}</span>
              </div>
              {!ok && (
                <>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-muted">{step.text}</p>
                  {isNext && (
                    <Link href={step.href} className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline">
                      {step.cta}<ArrowRight className="size-3" />
                    </Link>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
