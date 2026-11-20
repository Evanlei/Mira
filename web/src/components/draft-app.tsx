"use client";

import { ChevronDown, RotateCcw, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Model, type ModelJson } from "@/engine/model";
import { Searcher, suggestBans, type BanSuggestion, type Result } from "@/engine/search";
import { mapImage, modeInfo } from "@/lib/art";
import { EMPTY, apply, applyAll, banned, target, unavailableFor, type Draft } from "@/lib/draft";
import { gainPts, pct } from "@/lib/names";

import { Teams } from "./board";
import { Composer } from "./composer";
import { Summary } from "./panels";
import { MapPanel } from "./map-panel";
import { BrawlerSheet, MapSheet, type Ranked } from "./sheets";
import { Cluster, ModeIcon, cn } from "./ui";

export function DraftApp() {
  const [model, setModel] = useState<Model | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch("/model.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j: ModelJson) => setModel(new Model(j)))
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="p-6 text-[15px] text-them">Couldn’t load the model: {error}</p>;
  if (!model) return <Loading />;
  return <Drafter model={model} />;
}

function Loading() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 pt-20" aria-busy aria-label="Loading">
      {[72, 220, 260].map((h, i) => (
        <div key={i} className="card rounded-[22px]" style={{ height: h }} />
      ))}
    </div>
  );
}

function Drafter({ model }: { model: Model }) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [history, setHistory] = useState<Draft[]>([]);
  const [mapOpen, setMapOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const commit = useCallback((next: Draft) => {
    setDraft((cur) => {
      if (next === cur) return cur;
      setHistory((h) => [...h, cur]);
      return next;
    });
  }, []);
  const undo = () => {
    setHistory((h) => {
      if (!h.length) return h;
      setDraft(h[h.length - 1]);
      return h.slice(0, -1);
    });
  };
  const reset = () => commit({ ...EMPTY, map: draft.map, weFirst: draft.weFirst });

  const t = target(draft);
  const mp = draft.map;
  const bannedSet = useMemo(() => banned(draft), [draft]);

  // One searcher per draft state: it runs the current turn's search (well under 100 ms in the
  // browser) and its memo makes scoring a typed brawler cheap.
  const searcher = useMemo(
    () => (mp === null || t.kind === "ban" ? null : new Searcher(model, mp, bannedSet)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [model, mp, t.kind, bannedSet, draft.ours, draft.theirs, draft.weFirst],
  );
  const result: Result | null = useMemo(
    () => (searcher ? searcher.run(draft.ours, draft.theirs, draft.weFirst) : null),
    [searcher, draft.ours, draft.theirs, draft.weFirst],
  );

  // Ban suggestions: ~16 searches, so compute after paint.
  // Results are tagged with the draft they belong to; a stale tag reads as "loading".
  const [banResult, setBanResult] = useState<{ key: string; bans: BanSuggestion[] } | null>(null);
  const banKey = mp === null || t.kind !== "ban" ? null : `${mp}|${draft.weFirst}|${[...bannedSet].sort().join(",")}`;
  useEffect(() => {
    if (banKey === null || mp === null) return;
    const id = setTimeout(() => setBanResult({ key: banKey, bans: suggestBans(model, mp, draft.weFirst, bannedSet, 5) }), 16);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [banKey]);
  const bans = banResult && banResult.key === banKey ? banResult.bans : null;

  const ranked: Ranked = useMemo(() => {
    if (t.kind === "ban") return (bans ?? []).filter((x) => !unavailableFor(draft, x.brawler, t)).map((x) => ({ b: x.brawler, note: gainPts(x.gain) }));
    if (!result || t.kind !== "pick") return [];
    const seen = new Set<number>();
    const out: Ranked = [];
    for (const o of result.suggestions)
      for (const b of o.picks)
        if (!seen.has(b)) {
          seen.add(b);
          out.push({ b, note: t.side === "us" ? pct(o.win) : `${pct(o.prob ?? 0)} likely` });
        }
    return out;
  }, [t, bans, result, draft]);

  const pickerTitle =
    t.kind === "ban" ? (t.side === "us" ? "Your team’s ban" : "Their ban") : t.kind === "pick" ? (t.side === "us" ? "Your pick" : "Their pick") : "";

  const started = draft.ours.length > 0 || draft.theirs.length > 0 || bannedSet.size > 0;
  const games = model.data.n_matches;
  const isUnavailable = (b: number) => unavailableFor(draft, b, t);
  const featured = useMemo(() => {
    // Three most-played brawlers, for the inline cluster in the intro.
    const counts = model.data.games?.brawler ?? [];
    return [...counts.keys()].sort((a, b) => counts[b] - counts[a]).slice(0, 3);
  }, [model]);

  const m = mp === null ? null : model.maps[mp];
  const img = m ? mapImage(m.mode, m.map) : null;
  const setFirst = (weFirst: boolean) => commit({ ...EMPTY, map: draft.map, weFirst });

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="bg-bar text-zinc-100">
        <div className="mx-auto flex h-16 w-full max-w-[1440px] items-center gap-3 px-5 lg:px-12">
          <span className="me-2 text-xl font-extrabold tracking-tight">Mira</span>
          {m ? (
            <>
              <button
                onClick={() => setMapOpen(true)}
                aria-label={`Map: ${m.map}. Change map`}
                className="pressable flex h-10 min-w-0 items-center gap-2.5 rounded-xl bg-white/[0.08] ps-1.5 pe-3 text-sm font-semibold hover:bg-white/[0.14]"
              >
                {img && (
                  // eslint-disable-next-line @next/next/no-img-element -- static map art
                  <img src={img} alt="" className="size-7 shrink-0 rounded-lg object-cover" />
                )}
                <span className="truncate">{m.map}</span>
                <ChevronDown size={14} strokeWidth={2} absoluteStrokeWidth className="shrink-0 text-zinc-400" />
              </button>
              <span className="hidden h-10 items-center gap-2 rounded-xl bg-white/[0.08] px-3 text-sm font-semibold sm:flex">
                <ModeIcon mode={m.mode} size={16} />
                {modeInfo(m.mode).name}
              </span>
            </>
          ) : (
            <span className="hidden text-sm text-zinc-400 sm:inline">Draft coach for Brawl Stars Ranked</span>
          )}
        </div>
      </header>

      <div className="mx-auto w-full max-w-[1440px] flex-1 px-5 pt-6 pb-[max(32px,env(safe-area-inset-bottom))] lg:px-12 lg:pt-8">
        {m === null || mp === null ? (
          <main className="enter mx-auto max-w-2xl space-y-6 pt-6">
            <div className="space-y-3">
              <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">Pick a map to start</h1>
              <p className="text-[17px] leading-relaxed text-muted">
                I’ll suggest your best Brawl Stars Ranked picks and bans, learned from{" "}
                <Cluster model={model} picks={featured} size={28} /> <strong className="tabular text-foreground">{games.toLocaleString()} Masters games</strong>.
              </p>
            </div>
            <MapPanel model={model} mp={mp} onChange={() => setMapOpen(true)} />
            <FirstPick weFirst={draft.weFirst} onChange={setFirst} disabled={started} />
          </main>
        ) : (
          <main className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)] lg:items-start lg:gap-12">
            <figure className="enter hidden flex-col gap-3 lg:flex">
              {img && (
                // eslint-disable-next-line @next/next/no-img-element -- static map art
                <img src={img} alt={`${m.map} layout`} className="art aspect-[690/1050] w-full rounded-3xl object-cover" />
              )}
              <figcaption className="flex items-center gap-2.5 px-1">
                <ModeIcon mode={m.mode} size={18} />
                <span className="flex flex-1 items-baseline gap-2">
                  <span className="text-[15px] font-bold">{m.map}</span>
                  <span className="text-[13px] text-muted">{modeInfo(m.mode).name}</span>
                </span>
                <button onClick={() => setMapOpen(true)} className="pressable card h-8 rounded-full px-3 text-[13px] font-semibold hover:bg-subtle">
                  Change
                </button>
              </figcaption>
            </figure>

            <div className="enter enter-1 @container flex min-w-0 flex-col gap-8 lg:gap-10">
              <div className="lg:hidden">
                <MapPanel model={model} mp={mp} onChange={() => setMapOpen(true)} />
              </div>

              <div role="toolbar" aria-label="Draft controls" className="flex flex-wrap items-center gap-2">
                <FirstPick weFirst={draft.weFirst} onChange={setFirst} disabled={started} />
                <span className="ms-auto flex gap-2">
                  <ToolButton label="Undo" onClick={undo} disabled={!history.length}>
                    <Undo2 size={16} strokeWidth={1.75} absoluteStrokeWidth />
                  </ToolButton>
                  <ToolButton label="Reset" onClick={reset} disabled={!started && !draft.skipBans}>
                    <RotateCcw size={16} strokeWidth={1.75} absoluteStrokeWidth />
                  </ToolButton>
                </span>
              </div>

              <Teams model={model} draft={draft} target={t} />

              {t.kind !== "done" ? (
                <Composer
                  model={model}
                  draft={draft}
                  target={t}
                  mp={mp}
                  searcher={searcher}
                  result={result}
                  bans={bans}
                  isUnavailable={isUnavailable}
                  onPick={(b) => commit(apply(draft, b))}
                  onApply={(picks) => commit(applyAll(draft, picks))}
                  onSkipBans={() => commit({ ...draft, skipBans: true })}
                  onBrowse={() => setPickerOpen(true)}
                />
              ) : (
                result && <Summary model={model} ours={draft.ours} theirs={draft.theirs} mp={mp} win={result.win} />
              )}
            </div>
          </main>
        )}

        <footer className="mt-12 space-y-1 border-t border-border pt-6 text-xs leading-relaxed text-muted">
          <p>
            Trained on all-Masters Ranked matches up to {model.data.data_window[1].slice(0, 10)}
            {model.data.patches?.length ? <>, latest patch {model.data.patches.at(-1)!.date}</> : null}. Win chances assume your
            best play and typical Masters picks from them, so they run high: trust the order more than the number.
          </p>
          <p>Not affiliated with Supercell. Game art © Supercell, via Brawlify.</p>
        </footer>
      </div>

      <MapSheet model={model} open={mapOpen} onClose={() => setMapOpen(false)} current={mp} onPick={(i) => commit({ ...EMPTY, map: i, weFirst: draft.weFirst })} />
      <BrawlerSheet
        model={model}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title={pickerTitle}
        isUnavailable={isUnavailable}
        ranked={ranked}
        rankedLabel={t.kind === "ban" ? "Suggested bans" : t.kind === "pick" && t.side === "us" ? "Suggested" : "Most likely"}
        onPick={(b) => commit(apply(draft, b))}
      />
    </div>
  );
}

/** Who picks first: a two-way switch. Locked once the draft has started (reset to change). */
function FirstPick({ weFirst, onChange, disabled }: { weFirst: boolean; onChange: (weFirst: boolean) => void; disabled?: boolean }) {
  const opt = (value: boolean, label: string) => {
    const on = weFirst === value;
    return (
      <button
        role="radio"
        aria-checked={on}
        onClick={() => onChange(value)}
        disabled={disabled && !on}
        className={cn(
          "pressable h-8 rounded-lg px-3 text-[13px] disabled:opacity-40",
          on ? "bg-foreground font-bold text-white" : "font-semibold text-foreground/80 enabled:hover:bg-subtle",
        )}
      >
        {label}
      </button>
    );
  };
  return (
    <div
      role="radiogroup"
      aria-label="Who picks first"
      title={disabled ? "Reset the draft to change" : undefined}
      className="card flex h-10 items-center gap-0.5 rounded-xl p-1"
    >
      <span className="ps-1.5 pe-2 text-[13px] text-muted">First pick</span>
      {opt(true, "Us")}
      {opt(false, "Them")}
    </div>
  );
}

function ToolButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="pressable card flex h-10 items-center gap-2 rounded-xl px-3 text-[13px] font-semibold text-foreground/80 enabled:hover:bg-subtle disabled:opacity-40 sm:pe-3.5"
    >
      {children}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}
