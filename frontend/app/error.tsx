"use client";

import { RotateCcw } from "lucide-react";
import { useEffect } from "react";
import { RadarIllustration } from "@/components/illustrations";
import { Button } from "@/components/ui";

/** Une erreur dans une page n'efface plus toute l'interface : on peut réessayer sans recharger. */
export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="bg-dots flex flex-col items-center rounded-2xl border border-dashed border-line px-6 py-16 text-center">
      <RadarIllustration className="mb-5 size-24" active={false} />
      <p className="font-medium">Cette page n'a pas pu s'afficher</p>
      <p className="mt-1.5 max-w-md text-sm text-muted">{error.message || "Erreur inattendue."}</p>
      <Button variant="primary" className="mt-5" onClick={reset}>
        <RotateCcw className="size-4" />Réessayer
      </Button>
    </div>
  );
}
