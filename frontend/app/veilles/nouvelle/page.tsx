"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@/components/ui";
import { WatchEditor } from "@/components/watch-editor";
import { api } from "@/lib/api";

export default function NewWatchPage() {
  const [template, setTemplate] = useState<string | null>(null);

  useEffect(() => {
    api<{ content: string }>("/api/watches/template")
      .then((t) => setTemplate(t.content))
      .catch(() => setTemplate("---\nnom: Nouvelle veille\nplanning: \"0 8 * * 1-5\"\n---\n\n# Objectif\n"));
  }, []);

  if (template === null) return <Skeleton className="h-[70vh]" />;
  return <WatchEditor initial={template} />;
}
