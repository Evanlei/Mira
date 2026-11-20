"use client";

import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Model } from "@/engine/model";
import { mapImage, modeInfo } from "@/lib/art";
import { displayName, search } from "@/lib/names";

import { ModeIcon, Portrait, cn } from "./ui";

/** A hand of brawler cards, fanned like the game's draft screen. */
export function Fan({ model, picks, size = 64 }: { model: Model; picks: number[]; size?: number }) {
  const n = picks.length;
  return (
    <div className="flex items-end" aria-hidden>
      {picks.map((b, i) => {
        const off = i - (n - 1) / 2;
        return (
          <span
            key={b}
            className="fan-card relative"
            style={{
              marginInlineStart: i ? -size * 0.28 : 0,
              rotate: `${off * 8}deg`,
              translate: `0 ${Math.abs(off) * size * 0.08}px`,
              zIndex: n - Math.abs(Math.round(off)),
            }}
          >
            <Portrait id={model.ids[b]} name={model.names[b]} size={size} className="rounded-2xl ring-4 ring-background" />
          </span>
        );
      })}
    </div>
  );
}

/**
 * The start screen's map chooser: a search box first (you know the map when the draft starts),
 * with mode chips underneath that open just that mode's maps. Nothing is expanded by default.
 */
export function MapGrid({ model, onPick }: { model: Model; onPick: (mp: number) => void }) {
  const [mode, setMode] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) input.current?.focus({ preventScroll: true });
  }, []);

  const modes = useMemo(() => {
    const count = new Map<string, number>();
    model.maps.forEach((m) => count.set(m.mode, (count.get(m.mode) ?? 0) + 1));
    return [...count.entries()].sort((a, b) => modeInfo(a[0]).name.localeCompare(modeInfo(b[0]).name));
  }, [model]);
  const all = useMemo(() => model.maps.map((m, i) => ({ ...m, i })), [model]);
  const hits = useMemo(() => {
    if (!q) return [];
    const qq = q.toLowerCase().replace(/[^a-z0-9]/g, "");
    return all
      .filter((m) => search(m.map, q) || search(modeInfo(m.mode).name, q))
      .sort((a, b) => {
        const pa = a.map.toLowerCase().replace(/[^a-z0-9]/g, "").startsWith(qq) ? 0 : 1;
        const pb = b.map.toLowerCase().replace(/[^a-z0-9]/g, "").startsWith(qq) ? 0 : 1;
        return pa - pb || a.map.localeCompare(b.map);
      })
      .slice(0, 6);
  }, [all, q]);
  const active = hits.length ? hits[((cursor % hits.length) + hits.length) % hits.length] : null;
  const shown = mode ? all.filter((m) => m.mode === mode).sort((a, b) => a.map.localeCompare(b.map)) : [];

  return (
    <div>
      <label className="flex h-12 items-center gap-2.5 rounded-full bg-subtle px-5 ring-foreground focus-within:ring-2">
        <Search size={18} strokeWidth={1.5} absoluteStrokeWidth className="shrink-0 text-faint" />
        <input
          ref={input}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setCursor(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setQ("");
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => c + (e.key === "ArrowDown" ? 1 : -1));
            }
            if (e.key === "Enter" && active) {
              e.preventDefault();
              onPick(active.i);
            }
          }}
          placeholder="Search the map, like “hard rock”"
          aria-label="Search maps"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          className="h-full min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-faint focus-visible:outline-none"
        />
      </label>

      {q ? (
        hits.length ? (
          <ul role="listbox" aria-label="Matching maps" className="-mx-2 mt-2 flex flex-col">
            {hits.map((m) => {
              const img = mapImage(m.mode, m.map);
              const info = modeInfo(m.mode);
              const on = m === active;
              return (
                <li key={m.i} role="option" aria-selected={on}>
                  <button
                    onClick={() => onPick(m.i)}
                    onMouseEnter={() => setCursor(hits.indexOf(m))}
                    className={cn("pressable flex w-full items-center gap-3 rounded-[14px] p-2 text-start", on && "bg-subtle")}
                  >
                    {img ? (
                      // eslint-disable-next-line @next/next/no-img-element -- static map art
                      <img src={img} alt="" className="art h-12 w-9 shrink-0 rounded-[6px] object-cover" />
                    ) : (
                      <span className="h-12 w-9 shrink-0 rounded-[6px] bg-subtle" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-semibold">{m.map}</span>
                      <span className="flex items-center gap-1 text-xs" style={{ color: info.color }}>
                        <ModeIcon mode={m.mode} size={13} />
                        {info.name}
                      </span>
                    </span>
                    {on && <kbd className="hidden rounded border border-border px-1.5 text-xs text-faint [@media(pointer:fine)]:inline">↵</kbd>}
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-1 pt-4 text-sm text-muted">No map matches “{q}”.</p>
        )
      ) : (
        <>
          <div className="mt-5 mb-2.5 text-center text-xs text-faint">or browse by mode</div>
          <div className="no-scrollbar -mx-5 flex gap-2 overflow-x-auto px-5 pb-1 sm:mx-0 sm:flex-wrap sm:justify-center sm:px-0">
            {modes.map(([md, n]) => {
              const info = modeInfo(md);
              return (
                <Chip key={md} active={mode === md} color={info.color} onClick={() => setMode(mode === md ? null : md)}>
                  <ModeIcon mode={md} size={16} />
                  {info.name} <span className="tabular text-muted">{n}</span>
                </Chip>
              );
            })}
          </div>
          {shown.length > 0 && (
            <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {shown.map((m) => {
                const img = mapImage(m.mode, m.map);
                const info = modeInfo(m.mode);
                return (
                  <li key={m.i}>
                    <button
                      onClick={() => onPick(m.i)}
                      className="map-tile card pressable group relative block aspect-[4/3] w-full overflow-hidden rounded-2xl text-start"
                      style={{ ["--mode" as string]: info.color }}
                    >
                      {img && (
                        // eslint-disable-next-line @next/next/no-img-element -- static map art
                        <img src={img} alt="" loading="lazy" className="map-tile-art absolute inset-0 size-full scale-[1.35] object-cover" />
                      )}
                      <span className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/25 to-transparent" />
                      <span className="absolute inset-x-0 bottom-0 p-3">
                        <span className="block truncate text-[15px] leading-tight font-bold text-white">{m.map}</span>
                        <span className="block text-xs font-medium" style={{ color: info.color }}>
                          {info.name}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function Chip({ active, color, onClick, children }: { active: boolean; color?: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "pressable flex h-9 shrink-0 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium",
        active ? "text-foreground ring-1 ring-inset" : "bg-subtle text-foreground/80 hover:text-foreground",
      )}
      style={
        active
          ? { ["--tw-ring-color" as string]: color ?? "var(--accent)", background: `color-mix(in oklab, ${color ?? "var(--accent)"} 16%, transparent)` }
          : undefined
      }
    >
      {children}
    </button>
  );
}

export function featuredBrawlers(model: Model, n: number): number[] {
  const counts = model.data.games?.brawler ?? [];
  return [...counts.keys()].sort((a, b) => counts[b] - counts[a]).slice(0, n);
}

export const featuredLabel = (model: Model, picks: number[]) => picks.map((b) => displayName(model.names[b])).join(", ");
