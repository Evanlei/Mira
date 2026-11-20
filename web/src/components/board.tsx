"use client";

import { Ban } from "lucide-react";

import type { Model } from "@/engine/model";
import { pickSlots, type Draft, type Target } from "@/lib/draft";
import { displayName } from "@/lib/names";

import { Avatar, cn } from "./ui";

/** Two columns (you / them): 3 ban slots, then picks in draft order. The next slot is ringed. */
export function Board({ model, draft, target, onSlot }: { model: Model; draft: Draft; target: Target; onSlot: () => void }) {
  const slots = pickSlots(draft.weFirst);
  const column = (side: "us" | "them") => {
    const picks = side === "us" ? draft.ours : draft.theirs;
    const bans = side === "us" ? draft.bansUs : draft.bansThem;
    const mySlots = slots.filter((s) => s.side === side);
    const nextPick = target.kind === "pick" && target.side === side ? picks.length : -1;
    const nextBan = target.kind === "ban" && target.side === side ? bans.length : -1;
    return (
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("size-2 rounded-full", side === "us" ? "bg-us" : "bg-them")} />
          <span className="text-[13px] font-semibold">{side === "us" ? "Your team" : "Them"}</span>
        </div>
        <div className="grid grid-cols-3 gap-1.5" aria-label={`${side === "us" ? "Your" : "Their"} bans`}>
          {[0, 1, 2].map((i) => {
            const b = bans[i];
            const next = i === nextBan;
            return (
              <button
                key={i}
                onClick={onSlot}
                disabled={!next}
                aria-label={b !== undefined ? `Ban: ${displayName(model.names[b])}` : next ? "Choose ban" : "Empty ban slot"}
                className={cn(
                  "pressable grid h-9 place-items-center rounded-[8px] bg-surface-2",
                  next && "ring-2 ring-accent ring-offset-2 ring-offset-surface",
                  draft.skipBans && b === undefined && "opacity-40",
                )}
              >
                {b !== undefined ? (
                  <span className="relative grayscale">
                    <Avatar id={model.ids[b]} name={model.names[b]} size={24} />
                  </span>
                ) : (
                  <Ban size={14} strokeWidth={1.5} absoluteStrokeWidth className="text-faint" />
                )}
              </button>
            );
          })}
        </div>
        {mySlots.map((s) => {
          const b = picks[s.index];
          const next = s.index === nextPick || (target.kind === "pick" && target.side === side && target.size === 2 && s.index === nextPick + 1);
          return (
            <button
              key={s.order}
              onClick={onSlot}
              disabled={!next}
              aria-label={b !== undefined ? `Pick ${s.order}: ${displayName(model.names[b])}` : `Pick ${s.order}`}
              className={cn(
                "pressable flex h-12 min-w-0 items-center gap-2 rounded-[12px] px-2.5 text-start",
                b !== undefined ? (side === "us" ? "bg-us-soft" : "bg-them-soft") : "bg-surface-2",
                next && "ring-2 ring-accent ring-offset-2 ring-offset-surface",
              )}
            >
              <span className="tabular w-3 text-[11px] font-semibold text-faint">{s.order}</span>
              {b !== undefined ? (
                <>
                  <Avatar id={model.ids[b]} name={model.names[b]} size={26} />
                  <span className="truncate text-[14px] font-medium">{displayName(model.names[b])}</span>
                </>
              ) : (
                <span className="text-[13px] text-faint">{next ? "Choose…" : "—"}</span>
              )}
            </button>
          );
        })}
      </div>
    );
  };
  return (
    <div className="grid grid-cols-2 gap-3">
      {column("us")}
      {column("them")}
    </div>
  );
}
