"use client";

import type { Model } from "@/engine/model";
import { pickSlots, type Draft, type Target } from "@/lib/draft";
import { mapImage, modeInfo } from "@/lib/art";
import { displayName } from "@/lib/names";

import { ModeIcon, Portrait, cn } from "./ui";

/** Both teams: three pick slots in draft order, and three small ban slots. */
export function Board({ model, draft, target }: { model: Model; draft: Draft; target: Target }) {
  const slots = pickSlots(draft.weFirst);

  const team = (side: "us" | "them") => {
    const picks = side === "us" ? draft.ours : draft.theirs;
    const bans = side === "us" ? draft.bansUs : draft.bansThem;
    const mySlots = slots.filter((s) => s.side === side);
    const nextPick = target.kind === "pick" && target.side === side ? picks.length : -1;
    const nextBan = target.kind === "ban" && target.side === side ? bans.length : -1;
    const isNextPick = (i: number) =>
      i === nextPick || (target.kind === "pick" && target.side === side && target.size === 2 && i === nextPick + 1);

    return (
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 text-sm font-medium">
            <span className={cn("size-2 rounded-full", side === "us" ? "bg-us" : "bg-them")} />
            {side === "us" ? "Your team" : "Enemy team"}
          </span>
          <span className="flex items-center gap-1.5" aria-label={side === "us" ? "Your bans" : "Their bans"}>
            <span className="me-1 text-xs text-faint">bans</span>
            {[0, 1, 2].map((i) => {
              const b = bans[i];
              const next = i === nextBan;
              return (
                <span
                  key={i}
                  title={b !== undefined ? `Banned: ${displayName(model.names[b])}` : undefined}
                  className={cn(
                    "relative size-7 overflow-hidden rounded-md",
                    b === undefined && "bg-subtle",
                    next && "ring-2 ring-accent ring-offset-2 ring-offset-surface",
                    draft.skipBans && b === undefined && "opacity-40",
                  )}
                >
                  {b !== undefined && (
                    <>
                      <Portrait id={model.ids[b]} name={model.names[b]} className="size-full opacity-50 grayscale" />
                      <span aria-hidden className="absolute top-1/2 left-1/2 h-px w-[140%] -translate-1/2 -rotate-45 bg-them" />
                    </>
                  )}
                </span>
              );
            })}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2">
          {mySlots.map((s) => {
            const b = picks[s.index];
            const next = isNextPick(s.index);
            return (
              <div key={s.order} className="flex min-w-0 flex-col items-center gap-1.5">
                {b !== undefined ? (
                  <Portrait id={model.ids[b]} name={model.names[b]} size={56} className="rounded-xl" />
                ) : (
                  <span
                    className={cn(
                      "tabular grid size-14 place-items-center rounded-xl text-sm",
                      next ? "bg-accent/10 text-accent ring-2 ring-accent" : "bg-subtle text-faint",
                    )}
                  >
                    {s.order}
                  </span>
                )}
                <span className={cn("w-full truncate text-center text-xs", b !== undefined ? "text-foreground/80" : next ? "text-accent" : "text-transparent")}>
                  {b !== undefined ? displayName(model.names[b]) : next ? "up next" : "·"}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-5">
      {team("us")}
      <hr className="border-border" />
      {team("them")}
    </div>
  );
}

/** Wide screens: the in-game draft screen. Your team | the whole map | their team. */
export function DraftScreen({
  model,
  draft,
  target,
  mp,
  onChangeMap,
}: {
  model: Model;
  draft: Draft;
  target: Target;
  mp: number;
  onChangeMap: () => void;
}) {
  const slots = pickSlots(draft.weFirst);
  const m = model.maps[mp];
  const img = mapImage(m.mode, m.map);

  const team = (side: "us" | "them") => {
    const picks = side === "us" ? draft.ours : draft.theirs;
    const bans = side === "us" ? draft.bansUs : draft.bansThem;
    const mySlots = slots.filter((s) => s.side === side);
    const nextPick = target.kind === "pick" && target.side === side ? picks.length : -1;
    const nextBan = target.kind === "ban" && target.side === side ? bans.length : -1;
    const isNext = (i: number) =>
      i === nextPick || (target.kind === "pick" && target.side === side && target.size === 2 && i === nextPick + 1);
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <div className={cn("flex items-center gap-2 text-base font-semibold", side === "them" && "flex-row-reverse")}>
          <span className={cn("size-2 rounded-full", side === "us" ? "bg-us" : "bg-them")} />
          {side === "us" ? "Your team" : "Enemy team"}
        </div>
        <ol className="flex flex-col gap-2.5">
          {mySlots.map((s) => {
            const b = picks[s.index];
            const next = isNext(s.index);
            return (
              <li
                key={s.order}
                className={cn(
                  "flex h-[68px] items-center gap-3.5 rounded-2xl p-2",
                  side === "them" && "flex-row-reverse text-end",
                  b !== undefined ? "bg-subtle" : next ? "bg-accent/10 ring-2 ring-accent" : "bg-subtle/60",
                )}
              >
                {b !== undefined ? (
                  <Portrait id={model.ids[b]} name={model.names[b]} size={56} className="rounded-xl" />
                ) : (
                  <span className={cn("tabular grid size-14 shrink-0 place-items-center rounded-xl text-base", next ? "text-accent" : "text-faint")}>{s.order}</span>
                )}
                <span className="min-w-0">
                  <span className={cn("block truncate text-base", b !== undefined ? "font-medium" : next ? "text-accent" : "text-faint")}>
                    {b !== undefined ? displayName(model.names[b]) : next ? "Up next" : "—"}
                  </span>
                  <span className="block text-xs text-faint">pick {s.order}</span>
                </span>
              </li>
            );
          })}
        </ol>
        <div className={cn("flex items-center gap-2", side === "them" && "flex-row-reverse")}>
          <span className="text-xs text-faint">bans</span>
          {[0, 1, 2].map((i) => {
            const b = bans[i];
            return (
              <span
                key={i}
                title={b !== undefined ? `Banned: ${displayName(model.names[b])}` : undefined}
                className={cn(
                  "relative size-10 overflow-hidden rounded-lg",
                  b === undefined && "bg-subtle",
                  i === nextBan && "ring-2 ring-accent ring-offset-2 ring-offset-surface",
                  draft.skipBans && b === undefined && "opacity-40",
                )}
              >
                {b !== undefined && (
                  <>
                    <Portrait id={model.ids[b]} name={model.names[b]} className="size-full opacity-50 grayscale" />
                    <span aria-hidden className="absolute top-1/2 left-1/2 h-px w-[140%] -translate-1/2 -rotate-45 bg-them" />
                  </>
                )}
              </span>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-start gap-8">
      {team("us")}
      <div className="flex w-[200px] flex-col items-center gap-3 xl:w-[220px]">
        <button onClick={onChangeMap} className="pressable group flex w-full items-center justify-between gap-2 text-start" aria-label={`Map: ${m.map}. Change map`}>
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-sm text-muted">
              <ModeIcon mode={m.mode} size={15} />
              {modeInfo(m.mode).name}
            </span>
            <span className="block truncate text-base font-semibold">{m.map}</span>
          </span>
          <span className="shrink-0 rounded-md border border-border px-2 py-1 text-xs text-muted group-hover:text-foreground">change</span>
        </button>
        {img && (
          // eslint-disable-next-line @next/next/no-img-element -- static map art
          <img src={img} alt={`${m.map} layout`} className="art aspect-[690/1050] w-full rounded-xl object-cover" />
        )}
      </div>
      {team("them")}
    </div>
  );
}
