"use client";

import { LayoutGrid, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Model } from "@/engine/model";
import { turnsRemaining, type BanSuggestion, type Result, type Searcher } from "@/engine/search";
import { applyAll, type Draft, type Target } from "@/lib/draft";
import { displayName, gainPts, pct, search } from "@/lib/names";

import { DataChips } from "./panels";
import { Portrait, cn } from "./ui";

type Row = { key: string; picks: number[]; value: string; sub?: React.ReactNode; off?: string; best?: boolean; reply?: number[] };

/**
 * The one place to act: says whose turn it is, takes a typed brawler (Enter adds it and keeps focus
 * for the next step), and lists the engine's best lines when the box is empty. On your picks each
 * line shows the enemy's likely reply, so you see the next move before you commit.
 */
export function Composer({
  model,
  draft,
  target: t,
  mp,
  searcher,
  result,
  bans,
  isUnavailable,
  onPick,
  onApply,
  onSkipBans,
  onBrowse,
}: {
  model: Model;
  draft: Draft;
  target: Target;
  mp: number;
  searcher: Searcher | null;
  result: Result | null;
  bans: BanSuggestion[] | null;
  isUnavailable: (b: number) => boolean;
  onPick: (b: number) => void;
  onApply: (picks: number[]) => void;
  onSkipBans: () => void;
  onBrowse: () => void;
}) {
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  // Desktop: keep the box focused so a whole draft can be typed. "/" focuses it from anywhere.
  useEffect(() => {
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (fine) input.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        input.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // The enemy's most likely answer to each suggested line (memoized searches, so cheap).
  const replies = useMemo(() => {
    const out = new Map<string, number[]>();
    if (!searcher || !result || t.kind !== "pick" || t.side !== "us") return out;
    for (const o of result.suggestions) {
      const d = applyAll(draft, o.picks);
      const step = searcher.run(d.ours, d.theirs, d.weFirst, 0).line[0];
      out.set(o.picks.join("-"), step && step.side === "them" ? step.chosen.picks : []);
    }
    return out;
  }, [searcher, result, draft, t]);

  if (t.kind === "done") return null;
  const ours = t.side === "us";
  const title =
    t.kind === "ban"
      ? ours ? "Ban one of these" : "What did they ban?"
      : ours ? "Best lines" : "What did they pick?";

  const scoreOf = (b: number): string => {
    if (t.kind === "ban") {
      const s = bans?.find((x) => x.brawler === b);
      return s ? gainPts(s.gain) : "";
    }
    if (!searcher) return "";
    const o = ours ? [...draft.ours, b] : draft.ours;
    const th = ours ? draft.theirs : [...draft.theirs, b];
    return pct(searcher.value(o, th, turnsRemaining(draft.weFirst, o.length, th.length)));
  };

  const rows: Row[] = q
    ? matches(model, q, isUnavailable, draft).map((r) => ({ ...r, value: r.off ? "" : scoreOf(r.picks[0]) }))
    : suggestionRows(model, t, result, bans, mp, replies);
  const live = rows.filter((r) => !r.off);
  const active = live.length ? live[((cursor % live.length) + live.length) % live.length] : null;
  const choose = (r: Row) => {
    if (r.picks.length === 1) onPick(r.picks[0]);
    else onApply(r.picks);
    setQ("");
    setCursor(0);
    input.current?.focus({ preventScroll: true });
  };

  return (
    <section className="flex flex-col gap-3" aria-label={title}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-3">
        <h2 className="flex items-baseline gap-2.5 text-2xl font-extrabold tracking-tight">
          {title}
          {!q && rows.length > 0 && <span className="tabular text-sm font-medium tracking-normal text-faint">{rows.length}</span>}
        </h2>

        <label className="flex h-10 w-full items-center gap-2 rounded-full bg-subtle px-4 ring-foreground focus-within:ring-2 sm:ms-auto sm:w-[280px]">
          <Search size={15} strokeWidth={1.5} absoluteStrokeWidth className="shrink-0 text-muted" />
          <input
            ref={input}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setCursor(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQ("");
              if (e.key === "Enter" && active) {
                e.preventDefault();
                choose(active);
              }
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => c + (e.key === "ArrowDown" ? 1 : -1));
              }
            }}
            placeholder={t.kind === "ban" ? (ours ? "Type a brawler to ban" : "Type their ban") : ours ? "Or type any brawler" : "Type what they picked"}
            aria-label="Type a brawler"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="done"
            className="h-full min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-faint focus-visible:outline-none"
            data-composer
          />
          <kbd className="hidden rounded border border-border px-1.5 text-xs text-muted [@media(pointer:fine)]:inline">/</kbd>
        </label>
      </div>

      <Results
        model={model}
        q={q}
        rows={rows}
        active={active}
        withReply={!q && t.kind === "pick" && ours}
        replyRing={ours ? "var(--them)" : "var(--us)"}
        pickRing={t.kind === "pick" && !q ? (ours ? "var(--us)" : "var(--them)") : null}
        onHover={(r) => setCursor(live.indexOf(r))}
        valueLabel={q ? (t.kind === "ban" ? "win % gained" : ours ? "win chance" : "you’d be at") : t.kind === "ban" ? "gained" : ours ? "Win" : "likely"}
        onChoose={choose}
        empty={q ? `No brawler matches “${q}”.` : t.kind === "ban" && !bans ? "Working out the best bans…" : ""}
      />

      <div className="flex items-center justify-between gap-3 text-sm text-muted">
        <button onClick={onBrowse} className="pressable inline-flex h-10 items-center gap-1.5 hover:text-foreground">
          <LayoutGrid size={16} strokeWidth={1.5} absoluteStrokeWidth />
          Browse all brawlers
        </button>
        {t.kind === "ban" && (
          <button onClick={onSkipBans} className="pressable h-10 rounded-full bg-subtle px-4 font-semibold hover:text-foreground">
            Skip bans
          </button>
        )}
      </div>
    </section>
  );
}

function matches(model: Model, q: string, isUnavailable: (b: number) => boolean, draft: Draft): Row[] {
  const qq = q.toLowerCase().replace(/[^a-z0-9]/g, "");
  const banned = new Set([...draft.bansUs, ...draft.bansThem]);
  return [...Array(model.B).keys()]
    .filter((b) => search(model.names[b], q))
    .sort((a, b) => {
      // Prefix matches first, then alphabetical.
      const pa = model.names[a].toLowerCase().replace(/[^a-z0-9]/g, "").startsWith(qq) ? 0 : 1;
      const pb = model.names[b].toLowerCase().replace(/[^a-z0-9]/g, "").startsWith(qq) ? 0 : 1;
      return pa - pb || displayName(model.names[a]).localeCompare(displayName(model.names[b]));
    })
    .slice(0, 6)
    .map((b) => ({
      key: String(b),
      picks: [b],
      value: "",
      off: isUnavailable(b) ? (banned.has(b) ? "banned" : "taken") : undefined,
    }));
}

function suggestionRows(model: Model, t: Target, result: Result | null, bans: BanSuggestion[] | null, mp: number, replies: Map<string, number[]>): Row[] {
  if (t.kind === "ban") return (bans ?? []).map((x, i) => ({ key: String(x.brawler), picks: [x.brawler], value: gainPts(x.gain), best: i === 0 }));
  if (!result || t.kind !== "pick") return [];
  const ours = t.side === "us";
  return result.suggestions.map((o, i) => ({
    key: o.picks.join("-"),
    picks: o.picks,
    value: ours ? pct(o.win) : pct(o.prob ?? 0),
    sub: ours ? <DataChips model={model} picks={o.picks} mp={mp} /> : <span className="tabular">you’d be at {pct(o.win)}</span>,
    best: i === 0,
    reply: replies.get(o.picks.join("-")),
  }));
}

const GRID_REPLY = "grid-cols-[20px_auto_minmax(0,1fr)_52px] @xl:grid-cols-[28px_auto_minmax(0,1fr)_150px_60px] @3xl:grid-cols-[36px_116px_minmax(0,1fr)_220px_72px]";
const GRID_PLAIN = "grid-cols-[20px_auto_minmax(0,1fr)_64px] @xl:grid-cols-[28px_auto_minmax(0,1fr)_96px] @3xl:grid-cols-[36px_116px_minmax(0,1fr)_96px]";

function Results({
  model,
  q,
  rows,
  active,
  withReply,
  pickRing,
  replyRing,
  onHover,
  valueLabel,
  onChoose,
  empty,
}: {
  model: Model;
  q: string;
  rows: Row[];
  active: Row | null;
  withReply: boolean;
  pickRing: string | null;
  replyRing: string;
  onHover: (r: Row) => void;
  valueLabel: string;
  onChoose: (r: Row) => void;
  empty: string;
}) {
  const label = q ? "Matches" : "Suggested";
  if (!rows.length) return empty ? <p className="px-1 pt-2 pb-2 text-sm text-muted">{empty}</p> : null;
  const grid = withReply ? GRID_REPLY : GRID_PLAIN;

  return (
    <div className="flex flex-col gap-2">
      <div aria-hidden className={cn("grid items-center gap-x-3 px-3 text-xs text-muted sm:px-4", grid)}>
        <span />
        <span>{q ? label : withReply ? "You" : ""}</span>
        <span />
        {withReply && <span className="hidden @xl:block">Them · likely reply</span>}
        <span className="text-end">{valueLabel}</span>
      </div>
      {/* Every line the search kept, in a fixed-height pane: a partly visible last row says "scroll". */}
      <ul
        role="listbox"
        aria-label={label}
        className="-mx-2 flex max-h-[min(31rem,58dvh)] flex-col gap-2 overflow-y-auto lg:max-h-[max(20rem,calc(100dvh-32rem))] overscroll-contain px-2 pt-0.5 pb-3 [scrollbar-width:thin]"
      >
        {rows.map((r, i) => {
          const isActive = r === active;
          const best = r.best && !q;
          const rowBg = best ? "var(--foreground)" : "var(--surface)";
          const ring = (color: string | null) => (color ? { boxShadow: `0 0 0 2px ${rowBg}, 0 0 0 4px ${color}` } : undefined);
          return (
            <li key={r.key} role="option" aria-selected={isActive} aria-disabled={!!r.off}>
              <button
                disabled={!!r.off}
                onClick={() => onChoose(r)}
                onMouseEnter={() => !r.off && onHover(r)}
                className={cn(
                  "pressable grid min-h-16 w-full items-center gap-x-3 rounded-[22px] px-3 py-2.5 text-start disabled:opacity-40 sm:px-4",
                  grid,
                  best ? "bg-foreground text-background shadow-[var(--shadow-lift)]" : "card",
                  isActive && q && "ring-2 ring-foreground",
                )}
              >
                <span className={cn("tabular text-center text-[15px] font-bold", best ? "font-extrabold" : "text-muted")}>{q ? "" : i + 1}</span>
                <span className="flex shrink-0 gap-2.5">
                  {r.picks.map((b) => (
                    <Portrait key={b} id={model.ids[b]} name={model.names[b]} size={40} className="rounded-[10px] sm:size-11! sm:rounded-xl" style={ring(pickRing)} />
                  ))}
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className={cn("truncate text-[15px]", best ? "font-bold" : "font-semibold")}>{r.picks.map((b) => displayName(model.names[b])).join(" + ")}</span>
                  </span>
                  {(r.sub || r.off) && (
                    <span className={cn("flex flex-wrap items-center gap-1.5 text-xs", best ? "text-background/70 [&_span]:border-background/30 [&_span]:text-background/80" : "text-muted")}>
                      {r.off ?? r.sub}
                    </span>
                  )}
                </span>
                {withReply && (
                  <span className="hidden min-w-0 items-center gap-3 @xl:flex">
                    {r.reply?.length ? (
                      <>
                        <span className="flex shrink-0 gap-2.5">
                          {r.reply.map((b) => (
                            <Portrait key={b} id={model.ids[b]} name={model.names[b]} size={40} className="rounded-[10px] sm:size-11! sm:rounded-xl" style={ring(replyRing)} />
                          ))}
                        </span>
                        <span className={cn("truncate text-sm", best ? "text-background/75" : "text-muted")}>{r.reply.map((b) => displayName(model.names[b])).join(" + ")}</span>
                      </>
                    ) : (
                      <span className={cn("text-sm", best ? "text-background/75" : "text-muted")}>last pick</span>
                    )}
                  </span>
                )}
                <span className={cn("tabular text-end", best ? "text-xl font-extrabold" : "text-lg font-bold text-foreground/80")}>
                  {r.value}
                  {isActive && q && <kbd className="ms-2 hidden rounded border border-border px-1.5 text-xs font-normal text-muted sm:inline">↵</kbd>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
