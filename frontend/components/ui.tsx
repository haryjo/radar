import clsx from "clsx";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function buttonClass(variant: Variant = "secondary", size: "sm" | "md" = "md", className?: string) {
  return clsx(
    "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all active:scale-[0.98]",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-45",
    size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-9 px-3.5 text-sm",
    variant === "primary" && "bg-ink text-canvas shadow-sm hover:opacity-90",
    variant === "secondary" && "border border-line bg-surface hover:bg-raised",
    variant === "ghost" && "text-muted hover:bg-ink/5 hover:text-ink",
    variant === "danger" && "text-danger hover:bg-danger/10",
    className,
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }) {
  return (
    <button className={buttonClass(variant, size, className)} disabled={loading || props.disabled} {...props}>
      {loading && <Loader2 className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

/** Lien de navigation avec l'apparence d'un bouton (pas de bouton imbriqué dans un lien). */
export function ButtonLink({ href, variant = "secondary", size = "md", className, children }: {
  href: string; variant?: Variant; size?: "sm" | "md"; className?: string; children: ReactNode;
}) {
  return <Link href={href} className={buttonClass(variant, size, className)}>{children}</Link>;
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-2xl border border-line bg-surface shadow-card", className)}>{children}</div>;
}

export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
      <p className="text-[13px] font-medium">{children}</p>
      {aside}
    </div>
  );
}

type Tone = "neutral" | "accent" | "green" | "amber" | "red";

export function Badge({ tone = "neutral", dot, children }: { tone?: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
        tone === "neutral" && "bg-ink/[0.06] text-muted",
        tone === "accent" && "bg-accent-soft text-accent",
        tone === "green" && "bg-success/12 text-success",
        tone === "amber" && "bg-warning/15 text-warning",
        tone === "red" && "bg-danger/12 text-danger",
      )}
    >
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function Chip({ children }: { children: ReactNode }) {
  return <span className="rounded-md border border-line bg-raised px-1.5 py-0.5 text-[11px] text-muted">{children}</span>;
}

export function ScoreRing({ score, size = 44 }: { score: number; size?: number }) {
  const color = score >= 80 ? "var(--success)" : score >= 65 ? "var(--accent)" : "var(--warning)";
  const dash = (score / 100) * 94.2;
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }} title={`Score ${score}/100`}>
      <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90">
        <circle cx="18" cy="18" r="15" fill="none" stroke="var(--line)" strokeWidth="3" />
        <circle cx="18" cy="18" r="15" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${dash} 94.2`} />
      </svg>
      <span className="text-[13px] font-semibold tabular-nums">{score}</span>
    </div>
  );
}

export function StatCard({ label, value, hint, icon, children }: {
  label: string; value: ReactNode; hint?: string; icon?: ReactNode; children?: ReactNode;
}) {
  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted">{label}</p>
        {icon && <span className="grid size-7 place-items-center rounded-lg bg-accent-soft text-accent">{icon}</span>}
      </div>
      <p className="mt-2 text-[26px] font-semibold leading-none tracking-tight tabular-nums">{value}</p>
      {hint && <p className="mt-1.5 text-[11px] text-muted">{hint}</p>}
      {children && <div className="-mx-1 mt-3">{children}</div>}
    </Card>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: {
  title: string; description?: string; actions?: ReactNode; eyebrow?: string;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.12em] text-accent">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1.5 max-w-xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ illustration, title, children, action }: {
  illustration: ReactNode; title: string; children?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="bg-dots flex flex-col items-center justify-center rounded-2xl border border-dashed border-line px-6 py-14 text-center">
      <div className="mb-5">{illustration}</div>
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1.5 max-w-sm text-sm text-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return <p className="rounded-xl border border-danger/25 bg-danger/8 px-3.5 py-2.5 text-sm text-danger">{message}</p>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-2xl bg-ink/[0.05]", className)} />;
}

export function Segmented<T extends string>({ value, options, onChange }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="flex rounded-lg border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "whitespace-nowrap rounded-md px-2.5 py-1 text-[13px] transition-colors sm:px-3",
            value === o.value ? "bg-raised font-medium text-ink shadow-sm" : "text-muted hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

const RUN_STATUS: Record<string, { tone: Tone; label: string }> = {
  success: { tone: "green", label: "Terminée" },
  error: { tone: "red", label: "Erreur" },
  cancelled: { tone: "amber", label: "Arrêtée" },
  running: { tone: "accent", label: "En cours" },
};

export function RunStatusBadge({ status }: { status: string }) {
  const { tone, label } = RUN_STATUS[status] ?? RUN_STATUS.running;
  return <Badge tone={tone} dot>{label}</Badge>;
}
