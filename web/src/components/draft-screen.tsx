"use client";

import { RotateCcw, Undo2 } from "lucide-react";
import type { ReactNode } from "react";

import type { Model } from "@/engine/model";
import type { Option } from "@/engine/search";
import { mapImage, modeInfo } from "@/lib/art";
import { pickSlots, type Draft, type Target } from "@/lib/draft";
import { displayName, pct } from "@/lib/names";

import { ModeIcon, Portrait, cn } from "./ui";

/** Slots the current turn fills, e.g. picks 4 and 5 on a double pick. */
export function activeOrders(draft: Draft, t: Target): number[] {
  if (t.kind !== "pick") return [];
  const filled = t.side === "us" ? draft.ours.length : draft.theirs.length;
  return pickSlots(draft.weFirst)
    .filter((s) => s.side === t.side && s.index >= filled && s.index < filled + t.size)
    .map((s) => s.order);
}

export function TopBar({
  model,
  mp,
  onHome,
  onChangeMap,
  firstPick,
  onUndo,
  canUndo,
  onReset,
  canReset,
}: {
  model: Model;
  mp: number;
  onHome: () => void;
  onChangeMap: () => void;
  firstPick: ReactNode;
  onUndo: () => void;
  canUndo: boolean;
  onReset: () => void;
  canReset: boolean;
}) {
  const m = model.maps[mp];
  const info = modeInfo(m.mode);
  const img = mapImage(m.mode, m.map);
  return (
    <header className="flex items-center gap-3 border-b border-border px-4 py-3 sm:px-6 lg:gap-6 lg:px-8">
      <button onClick={onHome} className="pressable shrink-0 text-xl tracking-tight lg:text-[22px]" title="Back to maps">
        <span className="font-extrabold">Mira</span> <span className="hidden text-muted sm:inline">(draft coach)</span>
      </button>
      <button
        onClick={onChangeMap}
        className="pressable ms-auto flex h-10 min-w-0 items-center gap-2 rounded-full border border-border bg-surface ps-1 pe-3.5 text-sm font-semibold lg:ms-4 lg:text-[15px]"
        aria-label={`Map: ${m.map}, ${info.name}. Change map`}
      >
        {img ? (
          // eslint-disable-next-line @next/next/no-img-element -- static map art
          <img src={img} alt="" className="size-[30px] shrink-0 rounded-full object-cover" />
        ) : (
          <span className="size-[30px] shrink-0 rounded-full bg-subtle" />
        )}
        <ModeIcon mode={m.mode} size={17} />
        <span className="truncate">{m.map}</span>
        <span className="hidden font-medium sm:inline" style={{ color: info.color }}>
          {info.name}
        </span>
        <span className="hidden font-medium text-faint lg:inline">· change</span>
      </button>
      <div className="hidden lg:ms-auto lg:block">{firstPick}</div>
      <div className="flex shrink-0 gap-1">
        <IconButton label="Undo" onClick={onUndo} disabled={!canUndo}>
          <Undo2 size={18} strokeWidth={1.75} absoluteStrokeWidth />
        </IconButton>
        <span className="hidden sm:block">
          <IconButton label="Reset draft" onClick={onReset} disabled={!canReset}>
            <RotateCcw size={18} strokeWidth={1.75} absoluteStrokeWidth />
          </IconButton>
        </span>
      </div>
    </header>
  );
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className="pressable grid size-10 place-items-center rounded-full bg-surface text-muted hover:text-foreground disabled:opacity-35"
    >
      {children}
    </button>
  );
}

/** One team's column on wide screens: its three picks in draft order, then its bans. */
export function TeamPanel({
  model,
  draft,
  target: t,
  side,
  likely,
}: {
  model: Model;
  draft: Draft;
  target: Target;
  side: "us" | "them";
  /** Their most likely next pick, shown in their next empty slot. */
  likely?: Option | null;
}) {
  const slots = pickSlots(draft.weFirst).filter((s) => s.side === side);
  const picks = side === "us" ? draft.ours : draft.theirs;
  const bans = side === "us" ? draft.bansUs : draft.bansThem;
  const now = new Set(activeOrders(draft, t));
  const banNow = t.kind === "ban" && t.side === side ? bans.length : -1;
  const mirror = side === "them";
  const nextEmpty = slots.find((s) => s.index >= picks.length)?.order;

  return (
    <section aria-label={side === "us" ? "Your team" : "Enemy team"} className="card flex flex-col gap-3 rounded-[22px] p-4">
      <div className={cn("flex items-center justify-between", mirror && "flex-row-reverse")}>
        <span className={cn("flex items-center gap-2 text-[17px] font-bold", side === "us" ? "text-us" : "text-them", mirror && "flex-row-reverse")}>
          <span className={cn("size-2 rounded-full", side === "us" ? "bg-us" : "bg-them")} />
          {side === "us" ? "Your team" : "Enemy team"}
        </span>
        <span className="text-[13px] text-faint">picks {slots.map((s) => s.order).join(" · ")}</span>
      </div>

      <div className="grid grid-cols-3 gap-2" dir={mirror ? "rtl" : undefined}>
        {slots.map((s) => {
          const b = picks[s.index];
          const isNow = now.has(s.order);
          const showLikely = !isNow && b === undefined && side === "them" && likely && s.order === nextEmpty;
          const label =
            b !== undefined
              ? `Pick ${s.order}: ${displayName(model.names[b])}`
              : isNow
                ? `Pick ${s.order}: picking now`
                : showLikely
                  ? `Pick ${s.order}: likely ${likely.picks.map((x) => displayName(model.names[x])).join(" + ")}`
                  : `Pick ${s.order}`;
          return (
            <div
              key={s.order}
              title={label}
              aria-label={label}
              className={cn(
                "relative aspect-square overflow-hidden rounded-2xl",
                b !== undefined ? "" : isNow ? "bg-subtle ring-2 ring-foreground ring-inset" : "border border-dashed border-line-strong",
              )}
            >
              {b !== undefined ? (
                <Portrait id={model.ids[b]} name={model.names[b]} className="size-full" />
              ) : showLikely ? (
                <>
                  <Portrait id={model.ids[likely.picks[0]]} name={model.names[likely.picks[0]]} className="size-full opacity-25 grayscale" />
                  {likely.prob !== null && (
                    <span dir="ltr" className="tabular absolute inset-x-0 bottom-1 text-center text-[11px] font-medium text-muted">likely {pct(likely.prob)}</span>
                  )}
                </>
              ) : null}
              <span
                className={cn(
                  "tabular absolute top-1.5 start-1.5 grid size-5 place-items-center rounded-md text-[11px] font-bold",
                  b !== undefined ? "bg-black/60 text-white" : isNow ? "text-foreground" : "text-faint",
                )}
              >
                {s.order}
              </span>
            </div>
          );
        })}
      </div>

      <div className={cn("flex items-center gap-2 pt-1", mirror && "flex-row-reverse")}>
        <span className={cn("w-8 text-xs text-faint", mirror && "text-end")}>bans</span>
        {[0, 1, 2].map((i) => (
          <BanSlot key={i} model={model} b={bans[i]} now={i === banNow} skipped={draft.skipBans} size={34} />
        ))}
      </div>
    </section>
  );
}

function BanSlot({ model, b, now, skipped, size }: { model: Model; b: number | undefined; now: boolean; skipped: boolean; size: number }) {
  return (
    <span
      title={b !== undefined ? `Banned: ${displayName(model.names[b])}` : undefined}
      className={cn(
        "relative shrink-0 overflow-hidden rounded-[10px]",
        b === undefined && (now ? "ring-2 ring-foreground ring-inset" : "border border-dashed border-line-strong"),
        skipped && b === undefined && "opacity-40",
      )}
      style={{ width: size, height: size }}
    >
      {b !== undefined && (
        <>
          <Portrait id={model.ids[b]} name={model.names[b]} className="size-full opacity-55 grayscale" />
          <span aria-hidden className="absolute top-1/2 left-1/2 h-px w-[140%] -translate-1/2 -rotate-45 bg-them" />
        </>
      )}
    </span>
  );
}

/** The whole map layout, filling the space under your team. */
export function MapFigure({ model, mp, className }: { model: Model; mp: number; className?: string }) {
  const m = model.maps[mp];
  const img = mapImage(m.mode, m.map);
  const info = modeInfo(m.mode);
  if (!img) return null;
  return (
    <figure className={cn("card m-0 flex min-h-0 flex-col gap-3 rounded-[22px] p-4", className)}>
      <figcaption className="flex items-baseline justify-between gap-2 text-sm">
        <span className="truncate font-semibold">{m.map}</span>
        <span className="flex shrink-0 items-center gap-1" style={{ color: info.color }}>
          <ModeIcon mode={m.mode} size={14} />
          {info.name}
        </span>
      </figcaption>
      <div className="flex min-h-0 flex-1 justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element -- static map art */}
        <img src={img} alt={`${m.map} layout`} className="art aspect-[690/1050] h-full max-h-full w-auto max-w-full rounded-xl object-cover" />
      </div>
    </figure>
  );
}

/** Phones: both teams in one compact strip (picks in order, bans small on the right). */
export function TeamStrip({ model, draft, target: t }: { model: Model; draft: Draft; target: Target }) {
  const slots = pickSlots(draft.weFirst);
  const now = new Set(activeOrders(draft, t));
  const row = (side: "us" | "them") => {
    const picks = side === "us" ? draft.ours : draft.theirs;
    const bans = side === "us" ? draft.bansUs : draft.bansThem;
    const banNow = t.kind === "ban" && t.side === side ? bans.length : -1;
    return (
      <div className="flex items-center gap-2">
        <span className={cn("w-11 text-xs font-bold", side === "us" ? "text-us" : "text-them")}>{side === "us" ? "YOU" : "THEM"}</span>
        {slots
          .filter((s) => s.side === side)
          .map((s) => {
            const b = picks[s.index];
            const isNow = now.has(s.order);
            return b !== undefined ? (
              <Portrait key={s.order} id={model.ids[b]} name={model.names[b]} size={48} className="rounded-[11px]" />
            ) : (
              <span
                key={s.order}
                className={cn(
                  "tabular grid size-12 place-items-center rounded-[11px] text-sm",
                  isNow ? "bg-subtle font-bold text-foreground ring-2 ring-foreground ring-inset" : "border border-dashed border-line-strong text-faint",
                )}
              >
                {s.order}
              </span>
            );
          })}
        <span className="ms-auto flex gap-1">
          {[0, 1, 2].map((i) => (
            <BanSlot key={i} model={model} b={bans[i]} now={i === banNow} skipped={draft.skipBans} size={26} />
          ))}
        </span>
      </div>
    );
  };
  return (
    <section aria-label="Teams" className="card flex flex-col gap-2.5 rounded-[20px] p-3">
      {row("us")}
      {row("them")}
    </section>
  );
}
