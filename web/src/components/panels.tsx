"use client";

import { ArrowRight, Info, RotateCcw } from "lucide-react";

import type { Model } from "@/engine/model";
import type { BanSuggestion, Option, Result, Step } from "@/engine/search";
import { explain } from "@/lib/explain";
import { displayName, gainPts, pct } from "@/lib/names";

import { Avatar, Badge, BrawlerChip, cn } from "./ui";

const LOW_DATA = 100;

function DataBadges({ model, picks, mp }: { model: Model; picks: number[]; mp: number }) {
  const changed = model.recentlyChanged();
  const low = picks.filter((b) => model.gamesOnMap(b, mp) < LOW_DATA);
  const patched = picks.filter((b) => changed.has(model.names[b]));
  return (
    <>
      {low.length > 0 && (
        <Badge tone="warn" title={`Fewer than ${LOW_DATA} Masters games on this map`}>
          low data
        </Badge>
      )}
      {patched.length > 0 && (
        <Badge tone="accent" title={`Changed in the latest patch: ${patched.map((b) => displayName(model.names[b])).join(", ")}`}>
          recalibrating
        </Badge>
      )}
    </>
  );
}

export function Card({ title, aside, children, className }: { title: string; aside?: React.ReactNode; children: React.ReactNode; className?: string }) {
  // Concentric: card radius 28 = row radius 12 + padding 16.
  return (
    <section className={cn("surface rounded-[28px] p-4", className)}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

const picksLabel = (m: Model, picks: number[]) => picks.map((b) => displayName(m.names[b])).join(" + ");

export function Suggestions({
  model,
  result,
  mp,
  onApply,
}: {
  model: Model;
  result: Result;
  mp: number;
  onApply: (picks: number[]) => void;
}) {
  const ours = result.side === "us";
  const title = ours ? (result.turnSize === 2 ? "Your next 2 picks" : "Your next pick") : `Their likely pick${result.turnSize === 2 ? "s" : ""}`;
  return (
    <Card
      title={title}
      aside={
        ours ? (
          <span className="tabular text-[13px] text-muted">best line {pct(result.win)}</span>
        ) : (
          <span className="text-[13px] text-muted">tap what they picked</span>
        )
      }
    >
      <ol className="flex flex-col gap-1.5">
        {result.suggestions.slice(0, 5).map((o, i) => (
          <li key={o.picks.join("-")}>
            <button
              onClick={() => onApply(o.picks)}
              className="pressable flex min-h-14 w-full items-center gap-3 rounded-[12px] bg-surface-2 px-3 py-2 text-start"
            >
              <span className="tabular w-4 text-[13px] font-semibold text-faint">{i + 1}</span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                  {o.picks.map((b) => (
                    <BrawlerChip key={b} id={model.ids[b]} name={model.names[b]} />
                  ))}
                </span>
                <span className="flex gap-1.5">
                  <DataBadges model={model} picks={o.picks} mp={mp} />
                </span>
              </span>
              <span className="flex flex-col items-end">
                <span className="tabular text-[17px] font-semibold">{ours ? pct(o.win) : pct(o.prob ?? 0)}</span>
                <span className="text-[11px] text-faint">{ours ? "win" : `likely · you ${pct(o.win)}`}</span>
              </span>
            </button>
          </li>
        ))}
      </ol>
      {ours && (
        <p className="mt-3 flex gap-1.5 text-[12px] leading-snug text-faint">
          <Info size={14} strokeWidth={1.5} absoluteStrokeWidth className="mt-px shrink-0" />
          Win % assumes best play from you and typical Masters picks from them, so it runs high. Trust the order more
          than the number.
        </p>
      )}
    </Card>
  );
}

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
    <Card
      title="Most likely line"
      aside={
        previewing ? (
          <button onClick={onReset} className="pressable flex h-8 items-center gap-1.5 rounded-full bg-accent-soft px-3 text-[13px] font-medium text-accent">
            <RotateCcw size={13} strokeWidth={2} absoluteStrokeWidth />
            Reset
          </button>
        ) : (
          <span className="text-[13px] text-muted">tap an alternative to explore</span>
        )
      }
    >
      <ol className="flex flex-col">
        {line.map((s, i) => (
          <li key={i} className="flex gap-3 border-divider py-2.5 not-last:border-b">
            <span
              className={cn(
                "mt-0.5 h-6 shrink-0 rounded-full px-2 text-[11px] leading-6 font-semibold",
                s.side === "us" ? "bg-us-soft text-us" : "bg-them-soft text-them",
              )}
            >
              {s.side === "us" ? "You" : "Them"}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {s.chosen.picks.map((b) => (
                  <BrawlerChip key={b} id={model.ids[b]} name={model.names[b]} size="sm" />
                ))}
                <span className="tabular flex items-center gap-1 text-[13px] text-muted">
                  {s.side === "them" && s.chosen.prob !== null && <span>{pct(s.chosen.prob)} likely</span>}
                  <ArrowRight size={12} strokeWidth={1.5} absoluteStrokeWidth />
                  <span className="font-semibold text-text">{pct(s.chosen.win)}</span>
                </span>
              </div>
              {s.alternatives.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {s.alternatives.map((a) => (
                    <button
                      key={a.picks.join("-")}
                      onClick={() => onPreview(i, a)}
                      className="pressable h-8 rounded-full bg-surface-2 px-2.5 text-[12px] text-muted"
                    >
                      {picksLabel(model, a.picks)}{" "}
                      <span className="tabular">{s.side === "us" ? pct(a.win) : pct(a.prob ?? 0)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function Bans({ model, bans, loading, onApply }: { model: Model; bans: BanSuggestion[] | null; loading: boolean; onApply: (b: number) => void }) {
  return (
    <Card title="Suggested bans" aside={<span className="text-[13px] text-muted">gain in win %</span>}>
      {loading || !bans ? (
        <div className="flex flex-col gap-1.5" aria-busy>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 rounded-[12px] bg-surface-2" />
          ))}
        </div>
      ) : (
        <ol className="flex flex-col gap-1.5">
          {bans.map((x) => (
            <li key={x.brawler}>
              <button
                onClick={() => onApply(x.brawler)}
                className="pressable flex min-h-12 w-full items-center justify-between rounded-[12px] bg-surface-2 px-3 text-start"
              >
                <BrawlerChip id={model.ids[x.brawler]} name={model.names[x.brawler]} />
                <span className={cn("tabular text-[15px] font-semibold", x.gain >= 0.0005 ? "text-text" : "text-faint")}>
                  {gainPts(x.gain)}
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export function Summary({ model, ours, theirs, mp, win }: { model: Model; ours: number[]; theirs: number[]; mp: number; win: number }) {
  const terms = explain(model, ours, theirs, mp).slice(0, 6);
  const max = Math.max(0.01, ...terms.map((t) => Math.abs(t.value)));
  return (
    <Card title="Final draft">
      <div className="flex items-baseline gap-2">
        <span className="tabular text-[40px] leading-none font-semibold">{pct(win)}</span>
        <span className="text-[14px] text-muted">predicted win chance</span>
      </div>
      <h3 className="mt-4 mb-2 text-[12px] font-semibold tracking-wide text-faint uppercase">Biggest factors</h3>
      <ul className="flex flex-col gap-2">
        {terms.map((t) => (
          <li key={t.label} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1">
            <span className="truncate text-[13px]">{t.label}</span>
            <span className={cn("tabular text-[13px] font-semibold", t.value > 0 ? "text-us" : "text-them")}>
              {t.value > 0 ? "+" : "−"}
              {Math.abs(t.value).toFixed(2)}
            </span>
            <span className="col-span-2 h-1 overflow-hidden rounded-full bg-surface-2">
              <span
                className={cn("block h-full rounded-full", t.value > 0 ? "bg-us" : "bg-them")}
                style={{ width: `${(Math.abs(t.value) / max) * 100}%` }}
              />
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[12px] text-faint">Values are in log-odds: + helps you, − helps them.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {[...ours.map((b) => ["us", b] as const), ...theirs.map((b) => ["them", b] as const)].map(([side, b]) => (
          <span key={b} className={cn("rounded-full p-0.5", side === "us" ? "bg-us-soft" : "bg-them-soft")}>
            <Avatar id={model.ids[b]} name={model.names[b]} size={24} />
          </span>
        ))}
      </div>
    </Card>
  );
}
