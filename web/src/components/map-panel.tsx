"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import type { Model } from "@/engine/model";
import { mapImage, modeInfo } from "@/lib/art";

import { ModeIcon, cn } from "./ui";

/** The chosen map as a card (faded art behind the name, like jmo's build cards), with the full layout one tap away. */
export function MapPanel({ model, mp, onChange }: { model: Model; mp: number | null; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const m = mp === null ? null : model.maps[mp];
  const img = m ? mapImage(m.mode, m.map) : null;

  return (
    <section className="card overflow-hidden rounded-[22px]">
      <button
        onClick={onChange}
        aria-label={m ? `Map: ${m.map}. Change map` : "Choose a map"}
        className="pressable group relative block h-28 w-full overflow-hidden text-start"
      >
        {img && (
          // eslint-disable-next-line @next/next/no-img-element -- static map art
          <img src={img} alt="" className="absolute inset-0 size-full object-cover opacity-40 transition-opacity duration-300 group-hover:opacity-70 dark:opacity-25" />
        )}
        <span className="absolute inset-0 bg-gradient-to-b from-surface/90 via-surface/60 to-surface/20" />
        <span className="relative flex h-full flex-col justify-between p-4">
          <span>
            <span className="flex items-center gap-2 text-base font-semibold">
              {m && <ModeIcon mode={m.mode} size={18} />}
              {m ? m.map : "Choose a map"}
            </span>
            <span className="mt-0.5 block text-sm text-muted">{m ? modeInfo(m.mode).name : "Every map in the current Ranked pool"}</span>
          </span>
          <span className="flex items-center justify-between">
            <span className="rounded-md border border-border/60 bg-background/80 px-2 py-1 text-xs text-foreground/80 backdrop-blur-sm">
              {m ? "change map" : `${model.maps.length} maps`}
            </span>
            <ChevronDown size={16} strokeWidth={1.5} absoluteStrokeWidth className="text-muted" />
          </span>
        </span>
      </button>
      {img && (
        <>
          <div className={cn("px-3 pt-1", open ? "block" : "hidden")}>
            {/* eslint-disable-next-line @next/next/no-img-element -- static map art */}
            <img src={img} alt={`${m!.map} layout`} className="art mx-auto block aspect-[690/1050] w-full max-w-sm rounded-[12px] object-contain" />
          </div>
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="pressable flex h-10 w-full items-center justify-center gap-1 border-t border-border text-xs text-muted hover:text-foreground"
          >
            {open ? "Hide map" : "Show full map"}
            <ChevronDown size={14} strokeWidth={1.5} absoluteStrokeWidth className={cn("transition-transform duration-150", open && "rotate-180")} />
          </button>
        </>
      )}
    </section>
  );
}
