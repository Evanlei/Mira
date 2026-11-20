"use client";

import type { Model } from "@/engine/model";
import { pickSlots, type Draft, type Target } from "@/lib/draft";
import { displayName } from "@/lib/names";

import { Portrait, cn } from "./ui";

/**
 * Both teams, mirrored: yours on the left, theirs on the right. Picks in draft order, bans below.
 * The slots you fill this turn breathe (the turn glow); bans being chosen get a ring.
 */
export function Teams({ model, draft, target }: { model: Model; draft: Draft; target: Target }) {
  const slots = pickSlots(draft.weFirst);

  const team = (side: "us" | "them") => {
    const picks = side === "us" ? draft.ours : draft.theirs;
    const bans = side === "us" ? draft.bansUs : draft.bansThem;
    const mySlots = slots.filter((s) => s.side === side);
    const nextPick = target.kind === "pick" && target.side === side ? picks.length : -1;
    const nextBan = target.kind === "ban" && target.side === side ? bans.length : -1;
    const isNext = (i: number) =>
      i === nextPick || (target.kind === "pick" && target.side === side && target.size === 2 && i === nextPick + 1);
    const mirror = side === "them";

    return (
      <div className={cn("flex min-w-0 flex-col gap-3", mirror && "@3xl:items-end")}>
        <span className={cn("text-sm font-bold", side === "them" && "text-muted")}>{side === "us" ? "Your team" : "Enemy team"}</span>
        <ol className="flex gap-2.5 sm:gap-3">
          {mySlots.map((s) => {
            const b = picks[s.index];
            const next = isNext(s.index);
            return (
              <li key={s.order} className="flex min-w-0 flex-col gap-2">
                {b !== undefined ? (
                  <Portrait id={model.ids[b]} name={model.names[b]} className="size-[72px] rounded-2xl sm:size-24 sm:rounded-[20px]" />
                ) : (
                  <span
                    className={cn(
                      "tabular grid size-[72px] place-items-center rounded-2xl text-2xl font-extrabold sm:size-24 sm:rounded-[20px] sm:text-[28px]",
                      next ? "turn-glow bg-surface" : "border-[1.5px] border-dashed border-border text-faint",
                    )}
                  >
                    {s.order}
                  </span>
                )}
                <span className={cn("w-[72px] truncate text-[13px] sm:w-24", b !== undefined ? "text-muted" : next ? "font-semibold" : "text-muted")}>
                  {b !== undefined ? displayName(model.names[b]) : next ? (side === "us" ? "Your pick" : "Their pick") : `Pick ${s.order}`}
                </span>
              </li>
            );
          })}
        </ol>
        <div className={cn("flex items-center gap-1.5", mirror && "@3xl:flex-row-reverse")} aria-label={side === "us" ? "Your bans" : "Their bans"}>
          <span className={cn("text-xs text-muted", mirror ? "@3xl:ms-1 @3xl:me-0 me-1" : "me-1")}>Bans</span>
          {[0, 1, 2].map((i) => {
            const b = bans[i];
            return (
              <span
                key={i}
                title={b !== undefined ? `Banned: ${displayName(model.names[b])}` : undefined}
                className={cn(
                  "size-6 overflow-hidden rounded-md",
                  b === undefined && "bg-foreground/[0.06]",
                  i === nextBan && "ring-2 ring-foreground ring-offset-2 ring-offset-background",
                  draft.skipBans && b === undefined && "opacity-40",
                )}
              >
                {b !== undefined && <Portrait id={model.ids[b]} name={model.names[b]} className="size-full opacity-55 grayscale" />}
              </span>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <section aria-label="Teams" className="flex flex-col gap-6 @3xl:flex-row @3xl:items-start @3xl:justify-between">
      {team("us")}
      <span aria-hidden className="hidden self-center text-sm font-bold tracking-[0.08em] text-faint @3xl:block">
        VS
      </span>
      <hr className="border-border @3xl:hidden" />
      {team("them")}
    </section>
  );
}
