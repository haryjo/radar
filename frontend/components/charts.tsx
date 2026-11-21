"use client";

import clsx from "clsx";
import { useEffect, useId, useRef, useState } from "react";

/* Graphiques SVG légers, sans dépendance : couleurs via variables CSS, donc compatibles clair et sombre. */

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function niceMax(value: number) {
  if (value <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((s) => s * magnitude >= value) ?? 10;
  return step * magnitude;
}

function smoothPath(points: [number, number][]) {
  if (points.length < 2) return "";
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    const cx = (x0 + x1) / 2;
    d += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
  }
  return d;
}

export interface Point {
  label: string;
  value: number;
}

const PAD = { top: 12, right: 8, bottom: 22, left: 30 };

/** Courbe lissée avec aire en dégradé et infobulle au survol. */
export function AreaChart({
  data,
  height = 200,
  color = "var(--chart-1)",
  format = (v: number) => String(v),
}: {
  data: Point[];
  height?: number;
  color?: string;
  format?: (v: number) => string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const id = useId().replace(/:/g, "");
  const max = niceMax(Math.max(...data.map((d) => d.value), 0));
  const innerW = Math.max(width - PAD.left - PAD.right, 1);
  const innerH = height - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (data.length > 1 ? (i / (data.length - 1)) * innerW : innerW / 2);
  const y = (v: number) => PAD.top + innerH - (v / max) * innerH;
  const points = data.map((d, i) => [x(i), y(d.value)] as [number, number]);
  const line = smoothPath(points);
  const area = line && `${line} L${x(data.length - 1)},${PAD.top + innerH} L${x(0)},${PAD.top + innerH} Z`;
  const labelEvery = Math.ceil(data.length / Math.max(Math.floor(innerW / 64), 1));

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height} className="overflow-visible">
          <defs>
            <linearGradient id={`fill-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.28" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(max * t)} y2={y(max * t)} stroke="var(--line)" strokeDasharray={t ? "3 4" : undefined} />
              <text x={PAD.left - 8} y={y(max * t)} dy="0.32em" textAnchor="end" className="fill-muted text-[10px] tabular-nums">
                {format(max * t)}
              </text>
            </g>
          ))}
          {data.map((d, i) =>
            i % labelEvery === 0 || i === data.length - 1 ? (
              <text key={d.label} x={x(i)} y={height - 4} textAnchor="middle" className="fill-muted text-[10px]">
                {d.label}
              </text>
            ) : null,
          )}
          <path d={area} fill={`url(#fill-${id})`} />
          <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" />
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} stroke="var(--muted)" strokeOpacity="0.4" strokeDasharray="2 3" />
              <circle cx={x(hover)} cy={y(data[hover].value)} r="4.5" fill="var(--surface)" stroke={color} strokeWidth="2" />
            </g>
          )}
          {data.map((d, i) => (
            <rect
              key={d.label}
              x={x(i) - innerW / data.length / 2}
              y={PAD.top}
              width={innerW / data.length}
              height={innerH}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            />
          ))}
        </svg>
      )}
      {hover !== null && (
        <Tooltip left={x(hover)} top={y(data[hover].value)} label={data[hover].label} value={format(data[hover].value)} />
      )}
    </div>
  );
}

/** Barres verticales arrondies, avec infobulle. */
export function BarChart({
  data,
  height = 160,
  color = "var(--chart-1)",
  format = (v: number) => String(v),
  highlightLast = false,
  max: fixedMax,
}: {
  data: Point[];
  height?: number;
  color?: string;
  format?: (v: number) => string;
  highlightLast?: boolean;
  max?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const max = fixedMax ?? niceMax(Math.max(...data.map((d) => d.value), 0));
  const pad = { ...PAD, left: 34 };
  const innerW = Math.max(width - pad.left - pad.right, 1);
  const innerH = height - pad.top - pad.bottom;
  const slot = innerW / Math.max(data.length, 1);
  const barW = Math.min(Math.max(slot * 0.62, 3), 28);
  const y = (v: number) => pad.top + innerH - (v / max) * innerH;
  const labelEvery = Math.ceil(data.length / Math.max(Math.floor(innerW / 48), 1));

  return (
    <div ref={ref} className="relative" style={{ height }}>
      {width > 0 && (
        <svg width={width} height={height}>
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y(max * t)} y2={y(max * t)} stroke="var(--line)" strokeDasharray={t ? "3 4" : undefined} />
              <text x={pad.left - 8} y={y(max * t)} dy="0.32em" textAnchor="end" className="fill-muted text-[10px] tabular-nums">
                {format(max * t)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = pad.left + slot * i + slot / 2;
            const h = Math.max((d.value / max) * innerH, d.value > 0 ? 2 : 0);
            const faded = (hover !== null && hover !== i) || (highlightLast && hover === null && i !== data.length - 1);
            return (
              <g key={`${d.label}-${i}`} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={cx - slot / 2} y={pad.top} width={slot} height={innerH} fill="transparent" />
                <rect x={cx - barW / 2} y={pad.top + innerH - h} width={barW} height={h} rx={Math.min(4, barW / 2)} fill={color} opacity={faded ? 0.35 : 1} className="transition-opacity" />
                {(i % labelEvery === 0 || i === data.length - 1) && (
                  <text x={cx} y={height - 4} textAnchor="middle" className="fill-muted text-[10px]">{d.label}</text>
                )}
              </g>
            );
          })}
        </svg>
      )}
      {hover !== null && (
        <Tooltip left={pad.left + slot * hover + slot / 2} top={y(data[hover].value)} label={data[hover].label} value={format(data[hover].value)} />
      )}
    </div>
  );
}

function Tooltip({ left, top, label, value }: { left: number; top: number; label: string; value: string }) {
  return (
    <div
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-[calc(100%+10px)] whitespace-nowrap rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow-card"
      style={{ left, top }}
    >
      <span className="text-muted">{label}</span>
      <span className="ml-2 font-semibold tabular-nums">{value}</span>
    </div>
  );
}

/** Mini-courbe pour les cartes (s'étire à la largeur disponible). */
export function Sparkline({ values, color = "var(--chart-1)", className }: { values: number[]; color?: string; className?: string }) {
  const id = useId().replace(/:/g, "");
  if (values.length < 2) values = [0, ...values, 0].slice(-Math.max(values.length, 2));
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * 100, 28 - (v / max) * 24] as [number, number]);
  const line = smoothPath(pts);
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className={clsx("h-8 w-full overflow-visible", className)} aria-hidden>
      <defs>
        <linearGradient id={`sp-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L100,30 L0,30 Z`} fill={`url(#sp-${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.75" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
    </svg>
  );
}

/** Anneau de progression (taux de cache, score...). */
export function Donut({ value, size = 112, color = "var(--chart-2)", children }: { value: number; size?: number; color?: string; children?: React.ReactNode }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 100 100" className="size-full -rotate-90">
        <circle cx="50" cy="50" r={r} fill="none" stroke="var(--line)" strokeWidth="9" />
        <circle
          cx="50" cy="50" r={r} fill="none" stroke={color} strokeWidth="9" strokeLinecap="round"
          strokeDasharray={`${c * v} ${c}`} style={{ transition: "stroke-dasharray 0.8s ease-out" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">{children}</div>
    </div>
  );
}

/** Entonnoir horizontal : chaque étape filtre la précédente. */
export function Funnel({ steps }: { steps: { label: string; value: number; hint?: string }[] }) {
  const max = Math.max(...steps.map((s) => s.value), 1);
  return (
    <div className="space-y-2.5">
      {steps.map((step, i) => {
        const prev = i > 0 ? steps[i - 1].value : null;
        const ratio = prev ? Math.round((step.value / prev) * 100) : null;
        return (
          <div key={step.label}>
            <div className="mb-1 flex items-baseline justify-between text-[13px]">
              <span className="text-muted">{step.label}</span>
              <span className="tabular-nums">
                <span className="font-semibold">{step.value}</span>
                {ratio !== null && <span className="ml-2 text-[11px] text-muted">{ratio} %</span>}
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-raised">
              <div
                className="h-full rounded-full transition-[width] duration-700 ease-out"
                style={{
                  width: `${Math.max((step.value / max) * 100, step.value ? 2 : 0)}%`,
                  background: `color-mix(in oklch, var(--chart-1) ${100 - i * 12}%, var(--chart-2))`,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Barre comparative avant / après (ex. caractères HTML vs envoyés au LLM). */
export function CompareBar({ before, after, beforeLabel, afterLabel, format = (v: number) => String(v) }: {
  before: number; after: number; beforeLabel: string; afterLabel: string; format?: (v: number) => string;
}) {
  const ratio = before ? after / before : 0;
  return (
    <div className="space-y-2 text-[13px]">
      <div>
        <div className="mb-1 flex justify-between"><span className="text-muted">{beforeLabel}</span><span className="tabular-nums">{format(before)}</span></div>
        <div className="h-2 rounded-full bg-muted/30" />
      </div>
      <div>
        <div className="mb-1 flex justify-between"><span className="text-muted">{afterLabel}</span><span className="tabular-nums">{format(after)}</span></div>
        <div className="h-2 overflow-hidden rounded-full bg-raised">
          <div className="h-full rounded-full bg-chart-2 transition-[width] duration-700" style={{ width: `${Math.max(ratio * 100, after ? 1.5 : 0)}%` }} />
        </div>
      </div>
    </div>
  );
}
