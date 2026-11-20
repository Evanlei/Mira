"use client";

import { Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import type { Model } from "@/engine/model";
import { mapImage, modeInfo } from "@/lib/art";
import { displayName, search } from "@/lib/names";

import { ModeIcon, Portrait, Sheet, cn } from "./ui";

export function MapSheet({
  model,
  open,
  onClose,
  onPick,
  current,
}: {
  model: Model;
  open: boolean;
  onClose: () => void;
  onPick: (mp: number) => void;
  current: number | null;
}) {
  const [q, setQ] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const groups = useMemo(() => {
    const byMode = new Map<string, number[]>();
    model.maps.forEach((m, i) => {
      if (q && !search(m.map, q) && !search(modeInfo(m.mode).name, q)) return;
      byMode.set(m.mode, [...(byMode.get(m.mode) ?? []), i]);
    });
    return [...byMode.entries()].sort((a, b) => modeInfo(a[0]).name.localeCompare(modeInfo(b[0]).name));
  }, [model, q]);

  return (
    <Sheet open={open} onClose={onClose} title="Choose a map" initialFocus={input}>
      <SearchInput ref={input} value={q} onChange={setQ} placeholder="Search maps or modes" />
      {groups.length === 0 && <p className="py-8 text-center text-sm text-muted">No maps match “{q}”.</p>}
      {groups.map(([mode, maps]) => (
        <section key={mode} className="mt-5">
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-medium text-muted">
            <ModeIcon mode={mode} size={16} />
            {modeInfo(mode).name}
          </h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {[...maps]
              .sort((a, b) => model.maps[a].map.localeCompare(model.maps[b].map))
              .map((i) => {
                const img = mapImage(model.maps[i].mode, model.maps[i].map);
                return (
                  <button
                    key={i}
                    onClick={() => {
                      onPick(i);
                      onClose();
                    }}
                    aria-current={i === current}
                    className={cn(
                      "card pressable group relative h-20 overflow-hidden rounded-xl text-start",
                      i === current && "ring-2 ring-accent",
                    )}
                  >
                    {img && (
                      // eslint-disable-next-line @next/next/no-img-element -- static map art
                      <img src={img} alt="" loading="lazy" className="absolute inset-0 size-full object-cover opacity-30 transition-opacity duration-300 group-hover:opacity-60 dark:opacity-20" />
                    )}
                    <span className="absolute inset-0 bg-gradient-to-b from-background/90 via-background/50 to-transparent" />
                    <span className="relative block p-3 text-sm font-medium">{model.maps[i].map}</span>
                  </button>
                );
              })}
          </div>
        </section>
      ))}
    </Sheet>
  );
}

export type Ranked = { b: number; note: string }[];

export function BrawlerSheet({
  model,
  open,
  onClose,
  onPick,
  title,
  isUnavailable,
  ranked,
  rankedLabel,
}: {
  model: Model;
  open: boolean;
  onClose: () => void;
  onPick: (b: number) => void;
  title: string;
  isUnavailable: (b: number) => boolean;
  ranked: Ranked;
  rankedLabel: string;
}) {
  const [q, setQ] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const all = useMemo(
    () => [...Array(model.B).keys()].sort((a, b) => displayName(model.names[a]).localeCompare(displayName(model.names[b]))),
    [model],
  );
  const shown = q ? all.filter((b) => search(model.names[b], q)) : all;
  const pick = (b: number) => {
    onPick(b);
    setQ("");
    onClose();
  };

  return (
    <Sheet open={open} onClose={onClose} title={title} initialFocus={input}>
      <SearchInput
        ref={input}
        value={q}
        onChange={setQ}
        placeholder="Search brawlers"
        onEnter={() => {
          const first = shown.find((b) => !isUnavailable(b));
          if (first !== undefined) pick(first);
        }}
      />
      {!q && ranked.length > 0 && (
        <section className="mt-4">
          <h3 className="mb-2 text-sm font-medium text-muted">{rankedLabel}</h3>
          <div className="flex flex-wrap gap-1.5">
            {ranked.slice(0, 6).map(({ b, note }) => (
              <button key={b} onClick={() => pick(b)} className="card pressable flex h-9 items-center gap-2 rounded-full ps-1 pe-3 text-sm">
                <Portrait id={model.ids[b]} name={model.names[b]} size={28} className="rounded-full" />
                {displayName(model.names[b])}
                <span className="tabular text-muted">{note}</span>
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="mt-5">
        {!q && <h3 className="mb-2 text-sm font-medium text-muted">All brawlers</h3>}
        <div className="grid grid-cols-4 gap-x-2 gap-y-3 sm:grid-cols-6">
          {shown.map((b) => {
            const off = isUnavailable(b);
            return (
              <button
                key={b}
                disabled={off}
                onClick={() => pick(b)}
                aria-label={displayName(model.names[b]) + (off ? " (taken or banned)" : "")}
                className="pressable flex min-w-0 flex-col items-center gap-1 disabled:opacity-30"
              >
                <Portrait id={model.ids[b]} name={model.names[b]} size={52} className={cn("rounded-xl", off && "grayscale")} />
                <span className="w-full truncate text-center text-xs text-foreground/80">{displayName(model.names[b])}</span>
              </button>
            );
          })}
        </div>
        {shown.length === 0 && <p className="py-8 text-center text-sm text-muted">No brawlers match “{q}”.</p>}
      </section>
    </Sheet>
  );
}

function SearchInput({
  ref,
  value,
  onChange,
  placeholder,
  onEnter,
}: {
  ref: React.Ref<HTMLInputElement>;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  onEnter?: () => void;
}) {
  return (
    <label className="sticky top-0 z-10 -mx-5 block bg-background px-5 pb-1">
      <span className="flex h-11 items-center gap-2 rounded-xl border border-foreground/15 bg-surface px-3 focus-within:border-accent">
        <Search size={16} strokeWidth={1.5} absoluteStrokeWidth className="text-faint" />
        <input
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
          placeholder={placeholder}
          aria-label={placeholder}
          className="h-full min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-faint focus-visible:outline-none"
        />
      </span>
    </label>
  );
}
