export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "jamais";
  const diff = new Date(iso).getTime() - Date.now();
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });
  if (abs < 60_000) return "à l'instant";
  if (abs < 3_600_000) return rtf.format(Math.round(diff / 60_000), "minute");
  if (abs < 86_400_000) return rtf.format(Math.round(diff / 3_600_000), "hour");
  return rtf.format(Math.round(diff / 86_400_000), "day");
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat("fr", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function compact(n: number | undefined): string {
  return new Intl.NumberFormat("fr", { notation: "compact", maximumFractionDigits: 1 }).format(n ?? 0);
}

export function percent(ratio: number | undefined): string {
  return `${Math.round((ratio ?? 0) * 100)} %`;
}

export function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const CRON_DAYS: Record<string, string> = {
  "*": "tous les jours",
  "1-5": "du lundi au vendredi",
  "0": "le dimanche",
  "6": "le samedi",
  "1,3,5": "lundi, mercredi, vendredi",
};

/** Traduction lisible des plannings cron les plus courants. */
export function describeCron(cron: string | null): string {
  if (!cron) return "";
  const [min, hour, dom, mon, dow] = cron.split(/\s+/);
  if (dom === "*" && mon === "*" && /^\d+$/.test(min) && /^\d+$/.test(hour)) {
    const days = CRON_DAYS[dow] ?? `jours ${dow}`;
    return `${days} à ${hour.padStart(2, "0")} h ${min.padStart(2, "0")}`;
  }
  return cron;
}

export function shortDay(isoDate: string): string {
  return new Intl.DateTimeFormat("fr", { day: "numeric", month: "short" }).format(new Date(`${isoDate}T12:00:00`));
}

export function initials(name: string): string {
  const words = name.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)).toUpperCase();
}

/** Teinte stable dérivée d'un texte (couleur d'avatar). */
export function hueOf(text: string): number {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}
