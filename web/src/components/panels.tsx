"use client";

import { ArrowRight, RotateCcw } from "lucide-react";

import type { Model } from "@/engine/model";
import type { Option, Step } from "@/engine/search";
import { explain } from "@/lib/explain";
import { displayName, pct } from "@/lib/names";

import { Chip, Cluster, cn } from "./ui";

const LOW_DATA = 100;

export function DataChips({ model, picks, mp }: { model: Model; picks: number[]; mp: number }) {
  const changed = model.recentlyChanged();
  const low = picks.filter((b) => model.gamesOnMap(b, mp) < LOW_DATA);
  const patched = picks.filter((b) => changed.has(model.names[b]));
  return (
    <>
      {low.length > 0 && (
        <Chip tone="warn" title={`Fewer than ${LOW_DATA} Masters games on this map`}>
          low data
        </Chip>
      )}
      {patched.length > 0 && <Chip title={`Changed in the latest patch: ${patched.map((b) => displayName(model.names[b])).join(", ")}`}>patched</Chip>}
    </>
  );
}

export function Section({
  title,
  aside,
  toolbar,
  children,
  className,
}: {
  title: string;
  aside?: React.ReactNode;
  /** Shown beside the title on wide screens only. */
  toolbar?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("card rounded-[22px] p-4 lg:p-6", className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-6">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          {toolbar && <span className="hidden lg:block">{toolbar}</span>}
        </span>
        {aside && <span className="text-sm text-muted">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

const names = (m: Model, picks: number[]) => picks.map((b) => displayName(m.names[b])).join(" + ");

export function Line({
  model,
  line,
  previewing,
  onPreview,
  onReset,
}: {
  model: Model;
  line: Step[];
  previewing: boolean;
  onPreview: (step: number, option: Option) => void;
  onReset: () => void;
}) {
  return (
    <Section
      title="How it plays out"
      aside={
        previewing ? (
          <button onClick={onReset} className="pressable inline-flex items-center gap-1 text-sm text-accent">
            <RotateCcw size={13} strokeWidth={1.5} absoluteStrokeWidth />
            reset
          </button>
        ) : (
          "tap an alternative"
        )
      }
    >
      <ol className="flex flex-col">
        {line.map((s, i) => (
          <li key={i} className="flex gap-3 border-border py-3 first:pt-0 last:pb-0 not-last:border-b">
            <span className={cn("mt-3 size-2 shrink-0 rounded-full", s.side === "us" ? "bg-us" : "bg-them")} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-3">
                <span className="flex min-w-0 items-center gap-2.5">
                  <Cluster model={model} picks={s.chosen.picks} size={28} />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-[15px] font-medium">{names(model, s.chosen.picks)}</span>
                    <span className="tabular text-xs text-muted">
                      {s.side === "us" ? "you" : "them"}
                      {s.side === "them" && s.chosen.prob !== null && <> · {pct(s.chosen.prob)} likely</>}
                    </span>
                  </span>
                </span>
                <span className="tabular flex shrink-0 items-center gap-1 text-sm">
                  <ArrowRight size={12} strokeWidth={2.25} absoluteStrokeWidth className="text-faint" />
                  <span className="font-semibold">{pct(s.chosen.win)}</span>
                </span>
              </div>
              {s.alternatives.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {s.alternatives.map((a) => (
                    <button
                      key={a.picks.join("-")}
                      onClick={() => onPreview(i, a)}
                      title={names(model, a.picks)}
                      aria-label={`${names(model, a.picks)}, ${s.side === "us" ? pct(a.win) + " win" : pct(a.prob ?? 0) + " likely"}`}
                      className="card pressable flex h-8 shrink-0 items-center gap-1.5 rounded-full ps-1 pe-2.5 text-xs text-muted hover:text-foreground"
                    >
                      <Cluster model={model} picks={a.picks} size={22} />
                      <span className="tabular text-foreground/80">{s.side === "us" ? pct(a.win) : pct(a.prob ?? 0)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Section>
  );
}

export function Summary({ model, ours, theirs, mp, win }: { model: Model; ours: number[]; theirs: number[]; mp: number; win: number }) {
  const terms = explain(model, ours, theirs, mp).slice(0, 6);
  const max = Math.max(0.01, ...terms.map((t) => Math.abs(t.value)));
  return (
    <Section title="Final draft">
      <div className="flex items-end justify-between gap-4">
        <div>
          <span className="tabular block text-5xl font-semibold tracking-tight">{pct(win)}</span>
          <span className="text-sm text-muted">predicted win chance</span>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Cluster model={model} picks={ours} size={30} />
          <Cluster model={model} picks={theirs} size={30} />
        </div>
      </div>
      <h3 className="mt-5 mb-2 text-sm font-medium text-muted">Biggest factors</h3>
      <ul className="flex flex-col gap-2.5">
        {terms.map((t) => (
          <li key={t.label} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
            <span className="truncate text-sm">{t.label}</span>
            <span className={cn("tabular text-sm font-medium", t.value > 0 ? "text-us" : "text-them")}>
              {t.value > 0 ? "+" : "−"}
              {Math.abs(t.value).toFixed(2)}
            </span>
            <span className="col-span-2 h-1 overflow-hidden rounded-full bg-subtle">
              <span className={cn("block h-full rounded-full", t.value > 0 ? "bg-us" : "bg-them")} style={{ width: `${(Math.abs(t.value) / max) * 100}%` }} />
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-muted">In log-odds: + helps you, − helps them.</p>
    </Section>
  );
}
