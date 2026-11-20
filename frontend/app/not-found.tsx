import { RadarIllustration } from "@/components/illustrations";
import { ButtonLink } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="bg-dots flex flex-col items-center rounded-2xl border border-dashed border-line px-6 py-16 text-center">
      <RadarIllustration className="mb-5 size-24" />
      <p className="font-medium">Rien sur le radar à cette adresse</p>
      <p className="mt-1.5 text-sm text-muted">La page demandée n'existe pas ou a été déplacée.</p>
      <ButtonLink href="/" variant="primary" className="mt-5">Retour aux offres</ButtonLink>
    </div>
  );
}
