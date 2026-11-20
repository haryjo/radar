"use client";

import clsx from "clsx";
import { Cpu, FileText, History, LayoutGrid, MessageSquare, Radar, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { StatusPill } from "./status-pill";
import { ThemeToggle } from "./theme-toggle";

const NAV = [
  { href: "/", label: "Offres", icon: LayoutGrid },
  { href: "/veilles", label: "Veilles", icon: FileText },
  { href: "/historique", label: "Historique", icon: History },
  { href: "/assistant", label: "Assistant", icon: MessageSquare },
  { href: "/profil", label: "Profil", icon: UserRound },
  { href: "/modeles", label: "Modèles", icon: Cpu },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-surface/70 px-3 py-5 backdrop-blur-xl md:flex">
      <Link href="/" className="mb-8 flex items-center gap-2.5 px-2">
        <span className="relative grid size-8 place-items-center rounded-xl bg-ink text-canvas">
          <Radar className="size-4" />
          <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-accent ring-2 ring-surface" />
        </span>
        <span>
          <span className="block text-[15px] font-semibold leading-tight tracking-tight">Radar</span>
          <span className="block text-[11px] text-muted">Veille d'offres</span>
        </span>
      </Link>

      <nav className="flex flex-col gap-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                active ? "bg-ink/[0.06] font-medium text-ink" : "text-muted hover:bg-ink/[0.04] hover:text-ink",
              )}
            >
              {active && <span className="absolute -left-3 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent" />}
              <Icon className={clsx("size-4", active && "text-accent")} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 px-1">
        <StatusPill />
        <ThemeToggle />
      </div>
    </aside>
  );
}

export function MobileNav() {
  const pathname = usePathname();
  return (
    <nav className="scroll-thin fixed inset-x-0 bottom-0 z-20 flex overflow-x-auto border-t border-line bg-surface/85 px-1 py-2 backdrop-blur-xl md:hidden">
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link key={href} href={href} className={clsx("flex min-w-[52px] flex-1 shrink-0 flex-col items-center gap-0.5 text-[10px]", isActive(pathname, href) ? "text-accent" : "text-muted")}>
          <Icon className="size-4" />
          {label}
        </Link>
      ))}
      <ThemeToggle compact />
    </nav>
  );
}
