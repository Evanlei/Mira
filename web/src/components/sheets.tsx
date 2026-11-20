"use client";

import { Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import type { Model } from "@/engine/model";
import { displayMode, displayName, search } from "@/lib/names";

import { Avatar, Sheet, cn } from "./ui";

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
      if (q && !search(m.map, q) && !search(m.mode, q)) return;
      byMode.set(m.mode, [...(byMode.get(m.mode) ?? []), i]);
    });
    return [...byMode.entries()].sort((a, b) => displayMode(a[0]).localeCompare(displayMode(b[0])));
  }, [model, q]);

  return (
    <Sheet open={open} onClose={onClose} title="Choose map" initialFocus={input}>
      <SearchInput ref={input} value={q} onChange={setQ} placeholder="Search maps or modes" />
      {groups.length === 0 && <p className="py-8 text-center text-[14px] text-muted">No maps match “{q}”.</p>}
      {groups.map(([mode, maps]) => (
        <section key={mode} className="mt-4">
          <h3 className="mb-1.5 text-[12px] font-semibold tracking-wide text-faint uppercase">{displayMode(mode)}</h3>
          <div className="grid grid-cols-2 gap-2">
            {[...maps]
              .sort((a, b) => model.maps[a].map.localeCompare(model.maps[b].map))
              .map((i) => (
                <button
                  key={i}
                  onClick={() => {
                    onPick(i);
                    onClose();
                  }}
                  aria-current={i === current}
                  className={cn(
                    "pressable surface min-h-11 rounded-[12px] px-3 py-2.5 text-start text-[14px] font-medium",
                    i === current && "bg-accent-soft text-accent",
                  )}
                >
                  {model.maps[i].map}
                </button>
              ))}
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
          <h3 className="mb-1.5 text-[12px] font-semibold tracking-wide text-faint uppercase">{rankedLabel}</h3>
          <div className="flex flex-col gap-1.5">
            {ranked.slice(0, 5).map(({ b, note }) => (
              <button
                key={b}
                onClick={() => pick(b)}
                className="pressable surface flex min-h-12 items-center justify-between gap-3 rounded-[12px] px-3 text-start"
              >
                <span className="flex items-center gap-2">
                  <Avatar id={model.ids[b]} name={model.names[b]} />
                  <span className="text-[15px] font-medium">{displayName(model.names[b])}</span>
                </span>
                <span className="tabular text-[14px] text-muted">{note}</span>
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="mt-4">
        {!q && <h3 className="mb-1.5 text-[12px] font-semibold tracking-wide text-faint uppercase">All brawlers</h3>}
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {shown.map((b) => {
            const off = isUnavailable(b);
            return (
              <button
                key={b}
                disabled={off}
                onClick={() => pick(b)}
                className="pressable surface flex min-h-[76px] flex-col items-center justify-center gap-1.5 rounded-[12px] px-1 py-2 disabled:opacity-35"
              >
                <Avatar id={model.ids[b]} name={model.names[b]} size={32} />
                <span className="w-full truncate text-center text-[12px] font-medium">{displayName(model.names[b])}</span>
              </button>
            );
          })}
        </div>
        {shown.length === 0 && <p className="py-8 text-center text-[14px] text-muted">No brawlers match “{q}”.</p>}
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
    <label className="sticky top-0 z-10 -mx-4 block bg-surface px-4 pb-1">
      <span className="flex h-11 items-center gap-2 rounded-[12px] border border-divider bg-surface-2 px-3">
        <Search size={16} strokeWidth={1.5} absoluteStrokeWidth className="text-faint" />
        <input
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onEnter?.()}
          placeholder={placeholder}
          aria-label={placeholder}
          className="h-full min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-faint"
        />
      </span>
    </label>
  );
}
