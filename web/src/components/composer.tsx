"use client";

import { LayoutGrid, Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { Model } from "@/engine/model";
import { turnsRemaining, type BanSuggestion, type Result, type Searcher } from "@/engine/search";
import type { Draft, Target } from "@/lib/draft";
import { displayName, gainPts, pct, search } from "@/lib/names";

import { activeOrders } from "./draft-screen";
import { DataChips } from "./panels";
import { Portrait, cn } from "./ui";

type Row = { key: string; picks: number[]; value: string; sub?: React.ReactNode; off?: string; best?: boolean };

/**
 * The one place to act: says whose turn it is, takes a typed brawler (Enter adds it and keeps focus
 * for the next step), and lists the engine's suggestions when the box is empty.
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
  className,
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
  className?: string;
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

  if (t.kind === "done") return null;
  const ours = t.side === "us";
  const orders = activeOrders(draft, t);
  const eyebrow =
    t.kind === "ban"
      ? `Ban ${(ours ? draft.bansUs : draft.bansThem).length + 1} of 3 · ${ours ? "your team" : "their team"}`
      : `${orders.length > 1 ? "Picks" : "Pick"} ${orders.join(" + ")} · ${ours ? "your turn" : "their turn"}`;
  const title =
    t.kind === "ban"
      ? ours ? "Ban one of these" : "What did they ban?"
      : ours ? (t.size === 2 ? "Your best two picks" : "Your best pick") : "What did they pick?";

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
    : suggestionRows(model, t, result, bans, mp);
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
    <section className={cn("card flex min-h-0 flex-col gap-4 rounded-[22px] p-5 lg:p-6", className)} aria-label={title}>
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className={cn("text-xs font-semibold tracking-[0.06em] uppercase", ours ? "text-us" : "text-them")}>{eyebrow}</div>
          <h1 className="mt-1 text-[26px] leading-tight font-extrabold tracking-tight lg:text-[30px]">{title}</h1>
        </div>
        <span className="hidden shrink-0 pb-1 text-sm text-faint sm:block">
          {t.kind === "ban" ? "win % gained" : ours ? "win chance after" : "most likely first"}
        </span>
      </div>

      <label className="flex h-14 shrink-0 items-center gap-3 rounded-2xl bg-subtle px-4 ring-foreground focus-within:ring-2">
        <Search size={20} strokeWidth={1.75} absoluteStrokeWidth className="shrink-0 text-faint" />
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
          placeholder={t.kind === "ban" ? (ours ? "Type a brawler to ban" : "Type their ban") : ours ? "Type any brawler, Enter adds it" : "Type what they picked"}
          aria-label="Type a brawler"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="done"
          className="h-full min-w-0 flex-1 bg-transparent text-[17px] outline-none placeholder:text-faint focus-visible:outline-none"
          data-composer
        />
        <kbd className="hidden rounded-md border border-line-strong px-2 text-xs text-faint [@media(pointer:fine)]:inline">/</kbd>
      </label>

      <Results
        model={model}
        q={q}
        rows={rows}
        active={active}
        onHover={(r) => setCursor(live.indexOf(r))}
        onChoose={choose}
        empty={q ? `No brawler matches “${q}”.` : t.kind === "ban" && !bans ? "Working out the best bans…" : ""}
      />

      <div className="mt-auto flex items-center justify-between gap-3 pt-1 text-sm text-muted">
        <button onClick={onBrowse} className="pressable inline-flex h-10 items-center gap-1.5 hover:text-foreground">
          <LayoutGrid size={16} strokeWidth={1.75} absoluteStrokeWidth />
          Browse all brawlers
        </button>
        {t.kind === "ban" ? (
          <button onClick={onSkipBans} className="pressable h-10 rounded-full border border-border px-4 hover:text-foreground">
            Skip bans
          </button>
        ) : (
          <span className="hidden text-faint sm:inline">Assumes good play from both sides</span>
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

function suggestionRows(model: Model, t: Target, result: Result | null, bans: BanSuggestion[] | null, mp: number): Row[] {
  if (t.kind === "ban") return (bans ?? []).map((x, i) => ({ key: String(x.brawler), picks: [x.brawler], value: gainPts(x.gain), best: i === 0 }));
  if (!result || t.kind !== "pick") return [];
  const ours = t.side === "us";
  return result.suggestions.slice(0, 5).map((o, i) => ({
    key: o.picks.join("-"),
    picks: o.picks,
    value: ours ? pct(o.win) : pct(o.prob ?? 0),
    sub: ours ? <DataChips model={model} picks={o.picks} mp={mp} /> : <span className="tabular">you’d be at {pct(o.win)}</span>,
    best: i === 0,
  }));
}

function Results({
  model,
  q,
  rows,
  active,
  onHover,
  onChoose,
  empty,
}: {
  model: Model;
  q: string;
  rows: Row[];
  active: Row | null;
  onHover: (r: Row) => void;
  onChoose: (r: Row) => void;
  empty: string;
}) {
  const label = q ? "Matches" : "Suggested";
  if (!rows.length) return empty ? <p className="px-1 py-2 text-[15px] text-muted">{empty}</p> : null;

  return (
    <ul role="listbox" aria-label={label} className="-mx-1 flex min-h-0 flex-col gap-1 overflow-y-auto overscroll-contain">
      {rows.map((r) => {
        const isActive = q ? r === active : !!r.best;
        const size = r.best && !q ? 52 : 46;
        return (
          <li key={r.key} role="option" aria-selected={r === active} aria-disabled={!!r.off}>
            <button
              disabled={!!r.off}
              onClick={() => onChoose(r)}
              onMouseEnter={() => !r.off && onHover(r)}
              className={cn(
                "pressable flex w-full items-center gap-4 rounded-2xl ps-2.5 pe-4 text-start disabled:opacity-40",
                r.best && !q ? "h-[76px]" : "h-[68px]",
                isActive ? "bg-subtle ring-1 ring-line-strong ring-inset" : "enabled:hover:bg-subtle",
              )}
            >
              <span className="flex shrink-0">
                {r.picks.map((b, k) => (
                  <Portrait
                    key={b}
                    id={model.ids[b]}
                    name={model.names[b]}
                    size={size}
                    className={cn("rounded-xl", k > 0 && "-ms-3 ring-[3px]", k > 0 && (isActive ? "ring-subtle" : "ring-surface"))}
                  />
                ))}
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className={cn("truncate text-[17px]", r.best && !q ? "font-bold" : "font-semibold")}>
                  {r.picks.map((b) => displayName(model.names[b])).join(" + ")}
                </span>
                {(r.sub || r.off) && <span className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted">{r.off ?? r.sub}</span>}
              </span>
              <span className={cn("tabular tracking-tight", r.best && !q ? "text-[26px] font-extrabold lg:text-[30px]" : "text-[22px] font-bold lg:text-2xl")}>{r.value}</span>
              {r === active && q && <kbd className="hidden rounded-md border border-line-strong px-1.5 text-xs text-faint sm:inline">↵</kbd>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
