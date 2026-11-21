import clsx from "clsx";

/** Radar animé, sobre : cercles concentriques, balayage et quelques points détectés. */
export function RadarIllustration({ className, active = true }: { className?: string; active?: boolean }) {
  return (
    <div className={clsx("relative aspect-square", className)} aria-hidden>
      <svg viewBox="0 0 120 120" className="absolute inset-0 size-full text-accent">
        <defs>
          <radialGradient id="radar-bg" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.10" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="60" cy="60" r="58" fill="url(#radar-bg)" />
        {[56, 42, 28, 14].map((r) => (
          <circle key={r} cx="60" cy="60" r={r} fill="none" stroke="currentColor" strokeOpacity="0.16" strokeWidth="0.75" />
        ))}
        <line x1="60" y1="2" x2="60" y2="118" stroke="currentColor" strokeOpacity="0.1" strokeWidth="0.75" />
        <line x1="2" y1="60" x2="118" y2="60" stroke="currentColor" strokeOpacity="0.1" strokeWidth="0.75" />
        <circle cx="60" cy="60" r="2" fill="currentColor" />
      </svg>
      {active && (
        <svg viewBox="0 0 120 120" className="animate-sweep absolute inset-0 size-full text-accent">
          <defs>
            <linearGradient id="radar-sweep" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="currentColor" stopOpacity="0" />
              <stop offset="100%" stopColor="currentColor" stopOpacity="0.35" />
            </linearGradient>
          </defs>
          <path d="M60 60 L60 4 A56 56 0 0 1 108.5 32 Z" fill="url(#radar-sweep)" />
        </svg>
      )}
      {[
        ["left-[68%] top-[30%]", "0s"],
        ["left-[30%] top-[62%]", "0.8s"],
        ["left-[74%] top-[70%]", "1.6s"],
      ].map(([pos, delay]) => (
        <span key={pos} className={clsx("absolute size-1.5 -translate-1/2", pos)}>
          {active && <span className="animate-ping-slow absolute inset-0 rounded-full bg-accent" style={{ animationDelay: delay }} />}
          <span className="absolute inset-0 rounded-full bg-accent" />
        </span>
      ))}
    </div>
  );
}

/** Pile de fichiers Markdown stylisée (état vide des veilles). */
export function FilesIllustration({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 120 90" className={clsx("text-accent", className)} aria-hidden>
      <rect x="34" y="14" width="56" height="70" rx="6" fill="currentColor" fillOpacity="0.06" stroke="currentColor" strokeOpacity="0.2" />
      <rect x="26" y="8" width="56" height="70" rx="6" className="fill-surface" stroke="currentColor" strokeOpacity="0.35" />
      <text x="34" y="24" fontSize="8" fontFamily="monospace" fill="currentColor" fillOpacity="0.7">---</text>
      {[32, 40, 48].map((y, i) => (
        <rect key={y} x="34" y={y} width={[30, 22, 34][i]} height="3" rx="1.5" fill="currentColor" fillOpacity="0.25" />
      ))}
      <text x="34" y="62" fontSize="8" fontFamily="monospace" fill="currentColor" fillOpacity="0.7"># .md</text>
      <circle cx="86" cy="66" r="10" fill="currentColor" />
      <path d="M81.5 66.5l3 3 6-6.5" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Bulles de discussion (état vide de l'assistant). */
export function ChatIllustration({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 120 80" className={clsx("text-accent", className)} aria-hidden>
      <rect x="10" y="10" width="62" height="30" rx="10" fill="currentColor" fillOpacity="0.1" />
      {[22, 32].map((y, i) => (
        <rect key={y} x="20" y={y - 3} width={[40, 26][i]} height="4" rx="2" fill="currentColor" fillOpacity="0.35" />
      ))}
      <rect x="44" y="44" width="66" height="26" rx="10" fill="currentColor" />
      <rect x="54" y="52" width="30" height="4" rx="2" fill="white" fillOpacity="0.85" />
      <rect x="54" y="60" width="44" height="4" rx="2" fill="white" fillOpacity="0.55" />
      <circle cx="102" cy="18" r="3" fill="currentColor" fillOpacity="0.5" />
      <circle cx="94" cy="28" r="2" fill="currentColor" fillOpacity="0.3" />
    </svg>
  );
}
