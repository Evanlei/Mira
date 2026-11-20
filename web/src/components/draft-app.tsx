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
import { PlayerButton, PlayerSheet, usePlayer, useReady } from "./player";
import { BrawlerSheet, MapSheet, type Ranked } from "./sheets";
import { Fan, MapGrid, featuredBrawlers, featuredLabel } from "./start";
import { ModeIcon, cn } from "./ui";

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
  const [playerOpen, setPlayerOpen] = useState(false);
  const [onlyReady, setOnlyReady] = useState(true);
  const { player, loading: playerLoading, connect, disconnect } = usePlayer();
  const ready = useReady(model, player);
  // The brawlers your lines may use: your power-11s when connected and "Only my 11s" is on.
  const mine = ready && onlyReady ? ready : null;

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
  // browser) and its memo makes scoring a typed brawler cheap. With `mine`, our picks come from
  // the player's power-11 brawlers (their side still drafts from everything); when that pool
  // can't fill a turn the engine falls back to every brawler, since teammates field their own.
  const searcher = useMemo(
    () => (mp === null || t.kind === "ban" ? null : new Searcher(model, mp, bannedSet, mine)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [model, mp, t.kind, bannedSet, draft.ours, draft.theirs, draft.weFirst, mine],
  );
  const result: Result | null = useMemo(
    () => (searcher ? searcher.run(draft.ours, draft.theirs, draft.weFirst) : null),
    [searcher, draft.ours, draft.theirs, draft.weFirst],
  );

  // Ban suggestions: ~16 searches, so compute after paint.
  // Results are tagged with the draft they belong to; a stale tag reads as "loading".
  const [banResult, setBanResult] = useState<{ key: string; bans: BanSuggestion[] } | null>(null);
  const poolKey = mine ? [...mine].sort((a, b) => a - b).join(".") : "all";
  const banKey = mp === null || t.kind !== "ban" ? null : `${mp}|${draft.weFirst}|${[...bannedSet].sort().join(",")}|${poolKey}`;
  useEffect(() => {
    if (banKey === null || mp === null) return;
    const id = setTimeout(() => setBanResult({ key: banKey, bans: suggestBans(model, mp, draft.weFirst, bannedSet, 15, 15, mine) }), 16);
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
  const featured = useMemo(() => featuredBrawlers(model, 5), [model]);

  const m = mp === null ? null : model.maps[mp];
  const img = m ? mapImage(m.mode, m.map) : null;
  const setFirst = (weFirst: boolean) => commit({ ...EMPTY, map: draft.map, weFirst });

  return (
    <div className="flex min-h-full flex-1 flex-col">
      {m && (
        <header className="border-b border-border">
          <div className="mx-auto flex h-16 w-full max-w-[1440px] items-center gap-3 px-5 lg:gap-5 lg:px-12">
            <button onClick={() => commit({ ...EMPTY, weFirst: draft.weFirst })} className="pressable shrink-0 text-xl tracking-tight" title="Back to maps">
              <span className="font-extrabold">Mira</span> <span className="hidden text-muted sm:inline">(draft coach)</span>
            </button>
            <button
              onClick={() => setMapOpen(true)}
              aria-label={`Map: ${m.map}, ${modeInfo(m.mode).name}. Change map`}
              className="pressable ms-auto flex h-10 min-w-0 items-center gap-2 rounded-full border border-border bg-surface ps-1 pe-3.5 text-sm font-semibold lg:ms-2"
            >
              {img ? (
                // eslint-disable-next-line @next/next/no-img-element -- static map art
                <img src={img} alt="" className="art size-[30px] shrink-0 rounded-full object-cover" />
              ) : (
                <span className="size-[30px] shrink-0 rounded-full bg-subtle" />
              )}
              <ModeIcon mode={m.mode} size={17} />
              <span className="truncate">{m.map}</span>
              <span className="hidden font-medium sm:inline" style={{ color: modeInfo(m.mode).color }}>
                {modeInfo(m.mode).name}
              </span>
              <ChevronDown size={14} strokeWidth={2} absoluteStrokeWidth className="shrink-0 text-faint" />
            </button>
            <span className="hidden sm:ms-auto sm:block">
              <PlayerButton player={player} onOpen={() => setPlayerOpen(true)} />
            </span>
          </div>
        </header>
      )}

      <div className="mx-auto w-full max-w-[1440px] flex-1 px-5 pt-6 pb-[max(32px,env(safe-area-inset-bottom))] lg:px-12 lg:pt-8">
        {m === null || mp === null ? (
          <div className="enter">
            <div className="flex items-center justify-between gap-3">
              <p className="text-lg tracking-tight">
                <span className="font-extrabold">Mira</span> <span className="text-muted">(draft coach)</span>
              </p>
              <PlayerButton player={player} onOpen={() => setPlayerOpen(true)} />
            </div>
            <main className="mx-auto flex max-w-2xl flex-col items-center pt-10 text-center sm:pt-16">
              <div title={`Most played: ${featuredLabel(model, featured)}`}>
                <Fan model={model} picks={featured} size={72} />
              </div>
              <h1 className="mt-8 text-4xl font-medium tracking-tight text-balance sm:text-5xl">Which map are you on?</h1>
              <p className="mt-4 max-w-md text-[15px] leading-relaxed text-pretty text-muted">
                I’ll suggest your best Ranked picks and bans, learned from{" "}
                <strong className="tabular font-semibold text-foreground">{games.toLocaleString()} Masters games</strong>.
              </p>
              <div className="enter enter-1 mt-8 w-full text-start">
                <MapGrid model={model} onPick={(i) => commit({ ...EMPTY, map: i, weFirst: draft.weFirst })} />
              </div>
              <div className="enter enter-2 mt-8">
                <FirstPick weFirst={draft.weFirst} onChange={setFirst} disabled={started} />
              </div>
            </main>
          </div>
        ) : (
          <main className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)] lg:items-start lg:gap-12">
            <figure className="enter sticky top-6 hidden lg:block">
              {img && (
                // eslint-disable-next-line @next/next/no-img-element -- static map art
                <img src={img} alt={`${m.map} layout`} className="art aspect-[690/1050] w-full rounded-3xl object-cover" />
              )}
            </figure>

            <div className="enter enter-1 @container flex min-w-0 flex-col gap-8 lg:gap-10">
              <div className="lg:hidden">
                <MapPanel model={model} mp={mp} onChange={() => setMapOpen(true)} />
              </div>

              <div role="toolbar" aria-label="Draft controls" className="flex flex-wrap items-center gap-2">
                {!started && <FirstPick weFirst={draft.weFirst} onChange={setFirst} />}
                {ready && (
                  <button
                    role="switch"
                    aria-checked={onlyReady}
                    onClick={() => setOnlyReady((v) => !v)}
                    title={`${ready.size} of your brawlers are at power 11`}
                    className={cn(
                      "pressable flex h-10 items-center gap-2 rounded-full px-4 text-[13px] font-semibold",
                      onlyReady ? "bg-foreground text-background" : "bg-subtle text-muted hover:text-foreground",
                    )}
                  >
                    Only my 11s
                    <span className={cn("tabular font-medium", onlyReady ? "text-background/60" : "text-faint")}>{ready.size}</span>
                  </button>
                )}
                <span className="ms-auto flex gap-2">
                  <ToolButton label="Undo" onClick={undo} disabled={!history.length}>
                    <Undo2 size={16} strokeWidth={2} absoluteStrokeWidth />
                  </ToolButton>
                  <ToolButton label="Reset" onClick={reset} disabled={!started && !draft.skipBans}>
                    <RotateCcw size={16} strokeWidth={2} absoluteStrokeWidth />
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
                  ready={mine}
                />
              ) : (
                result && <Summary model={model} ours={draft.ours} theirs={draft.theirs} mp={mp} win={result.win} />
              )}
            </div>
          </main>
        )}

        <footer className={cn("mt-12 space-y-1 border-t border-border pt-6 text-xs leading-relaxed text-muted", m === null && "mx-auto max-w-2xl text-center")}>
          <p>
            Trained on Masters-level Ranked matches up to {model.data.data_window[1].slice(0, 10)}
            {model.data.patches?.length ? <>, latest patch {model.data.patches.at(-1)!.date}</> : null}. Win chances assume good play
            from both sides, so they run high: trust the order more than the number.
          </p>
          <p>Not affiliated with Supercell. Game art © Supercell, via Brawlify.</p>
        </footer>
      </div>

      <MapSheet model={model} open={mapOpen} onClose={() => setMapOpen(false)} current={mp} onPick={(i) => commit({ ...EMPTY, map: i, weFirst: draft.weFirst })} />
      <PlayerSheet
        open={playerOpen}
        onClose={() => setPlayerOpen(false)}
        player={player}
        ready={ready}
        loading={playerLoading}
        connect={connect}
        disconnect={disconnect}
      />
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
          "pressable h-8 rounded-full px-3.5 text-[13px] disabled:opacity-40",
          on ? "bg-foreground font-bold text-background" : "font-semibold text-muted enabled:hover:text-foreground",
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
      className="flex h-10 items-center gap-0.5 rounded-full bg-subtle p-1"
    >
      <span className="ps-2.5 pe-1.5 text-[13px] text-muted">First pick</span>
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
      className="pressable flex h-10 items-center gap-2 rounded-full bg-subtle px-3 text-[13px] font-semibold text-muted enabled:hover:text-foreground disabled:opacity-40 sm:ps-3.5 sm:pe-4"
    >
      {children}
      <span className="hidden sm:inline">{label}</span>
    </button>
  );
}
