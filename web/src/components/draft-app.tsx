"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Model, type ModelJson } from "@/engine/model";
import { Searcher, suggestBans, type BanSuggestion, type Option, type Result, type Step } from "@/engine/search";
import { EMPTY, apply, applyAll, banned, target, unavailableFor, type Draft } from "@/lib/draft";
import { gainPts, pct } from "@/lib/names";

import { Composer } from "./composer";
import { MapFigure, TeamPanel, TeamStrip, TopBar } from "./draft-screen";
import { Line, Summary } from "./panels";
import { MapPanel } from "./map-panel";
import { BrawlerSheet, MapSheet, type Ranked } from "./sheets";
import { Fan, MapGrid, featuredBrawlers, featuredLabel } from "./start";
import { SlashTabs, cn } from "./ui";

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
  const [preview, setPreview] = useState<{ step: number; option: Option } | null>(null);
  const [tab, setTab] = useState<"picks" | "line" | "map">("picks");

  const commit = useCallback((next: Draft) => {
    setDraft((cur) => {
      if (next === cur) return cur;
      setHistory((h) => [...h, cur]);
      return next;
    });
    setPreview(null);
  }, []);
  const undo = () => {
    setHistory((h) => {
      if (!h.length) return h;
      setDraft(h[h.length - 1]);
      return h.slice(0, -1);
    });
    setPreview(null);
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

  // Previewed line: follow the main line to the chosen step, swap in the alternative, search on from there.
  const line: Step[] | null = useMemo(() => {
    if (!result || !preview || mp === null) return result?.line ?? null;
    let d = draft;
    for (let i = 0; i < preview.step; i++) d = applyAll(d, result.line[i].chosen.picks);
    d = applyAll(d, preview.option.picks);
    const rest = new Searcher(model, mp, bannedSet).run(d.ours, d.theirs, d.weFirst);
    const step = result.line[preview.step];
    const others = [step.chosen, ...step.alternatives].filter((o) => o !== preview.option);
    return [...result.line.slice(0, preview.step), { side: step.side, chosen: preview.option, alternatives: others }, ...rest.line];
  }, [result, preview, draft, model, mp, bannedSet]);

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
  const featured = useMemo(() => featuredBrawlers(model, 5), [model]);
  const firstPick = (
    <SlashTabs
      label="Who picks first"
      value={draft.weFirst ? "us" : "them"}
      onChange={(v) => commit({ ...EMPTY, map: draft.map, weFirst: v === "us" })}
      options={[
        { value: "us", label: "We pick first" },
        { value: "them", label: "They pick first" },
      ]}
      disabled={started}
      hint={started ? "reset the draft to change" : undefined}
    />
  );
  const sheets = (
    <>
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
    </>
  );
  const footer = (
    <footer className="space-y-1 text-xs leading-relaxed text-muted">
      <p>
        Trained on Masters-level Ranked matches up to {model.data.data_window[1].slice(0, 10)}
        {model.data.patches?.length ? <>, latest patch {model.data.patches.at(-1)!.date}</> : null}. Win chances assume good play
        from both sides, so they run high: trust the order more than the number.
      </p>
      <p>Not affiliated with Supercell. Game art © Supercell, via Brawlify.</p>
    </footer>
  );

  if (mp === null)
    return (
      <div className="mx-auto w-full max-w-3xl px-5 pt-10 pb-[max(32px,env(safe-area-inset-bottom))] sm:px-6 sm:pt-20">
        <header className="enter flex flex-col-reverse gap-8 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-4">
            <h1 className="text-4xl leading-tight tracking-tight sm:text-5xl">
              <span className="font-extrabold">Mira</span> <span className="text-muted">(draft coach)</span>
            </h1>
            <p className="max-w-xl text-[17px] leading-relaxed text-foreground/90 sm:text-xl">
              Pick a map and I’ll suggest your best Brawl Stars Ranked picks and bans, learned from{" "}
              <strong className="tabular">{games.toLocaleString()} Masters games</strong>.
            </p>
          </div>
          <div className="shrink-0 ps-2 pt-2 sm:pb-2" title={`Most played: ${featuredLabel(model, featured)}`}>
            <Fan model={model} picks={featured} size={60} />
          </div>
        </header>
        <main className="mt-10">
          <section className="card enter enter-1 rounded-[22px] p-4 sm:p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <h2 className="text-lg font-bold tracking-tight">Choose your map</h2>
              {firstPick}
            </div>
            <MapGrid model={model} onPick={(i) => commit({ ...EMPTY, map: i, weFirst: draft.weFirst })} />
          </section>
        </main>
        <div className="mt-12 border-t border-border pt-6">{footer}</div>
        {sheets}
      </div>
    );

  // Their likely next pick, for the empty slot in their column.
  const likely =
    t.kind === "pick" && t.side === "them" ? (result?.suggestions[0] ?? null) : (line?.find((s) => s.side === "them")?.chosen ?? null);
  const finalWin = line?.length ? line[line.length - 1].chosen.win : result?.win;

  const action =
    t.kind !== "done" ? (
      <Composer
        className="flex-1"
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
    );

  const outlook =
    line && result && result.side !== "done" ? (
      <>
        <Line
          className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
          model={model}
          line={line}
          previewing={preview !== null}
          onPreview={(step, option) => (step === 0 ? commit(applyAll(draft, option.picks)) : setPreview({ step, option }))}
          onReset={() => setPreview(null)}
        />
        {finalWin !== undefined && (
          <div className="card flex items-baseline justify-between rounded-[22px] px-5 py-4">
            <span className="text-sm text-muted">Predicted final</span>
            <span className="tabular text-[28px] font-extrabold tracking-tight">{pct(finalWin)}</span>
          </div>
        )}
      </>
    ) : (
      <p className="card rounded-[22px] p-5 text-sm text-muted">The rest of the draft plays out here once the picks start.</p>
    );

  const tabs = [
    { id: "picks", label: t.kind === "ban" ? "Bans" : "Picks" },
    { id: "line", label: "Plays out" },
    { id: "map", label: "Map" },
  ] as const;

  return (
    <div className="flex min-h-dvh flex-col">
      <TopBar
        model={model}
        mp={mp}
        onHome={() => commit({ ...EMPTY, weFirst: draft.weFirst })}
        onChangeMap={() => setMapOpen(true)}
        firstPick={
          <span title={started ? "Reset the draft to change who picks first" : undefined}>
            <SlashTabs
              label="Who picks first"
              value={draft.weFirst ? "us" : "them"}
              onChange={(v) => commit({ ...EMPTY, map: draft.map, weFirst: v === "us" })}
              options={[
                { value: "us", label: "We pick first" },
                { value: "them", label: "They pick first" },
              ]}
              disabled={started}
            />
          </span>
        }
        onUndo={undo}
        canUndo={history.length > 0}
        onReset={reset}
        canReset={started || draft.skipBans}
      />

      <main className="flex flex-1 flex-col gap-3 px-4 pt-3 pb-24 sm:px-6 lg:grid lg:h-[calc(100dvh-65px)] lg:min-h-[640px] lg:flex-none lg:grid-cols-[320px_minmax(0,1fr)_320px] lg:gap-6 lg:px-8 lg:pt-5 lg:pb-7">
        <div className="enter space-y-3 lg:hidden">
          <TeamStrip model={model} draft={draft} target={t} />
          {!started && <div className="px-1">{firstPick}</div>}
        </div>

        <div className="enter hidden min-h-0 flex-col gap-4 lg:flex">
          <TeamPanel model={model} draft={draft} target={t} side="us" />
          <MapFigure model={model} mp={mp} className="flex-1" />
        </div>

        <div className={cn("enter enter-1 min-h-0 flex-col", tab === "picks" ? "flex" : "hidden lg:flex")}>{action}</div>

        <div className="enter enter-2 hidden min-h-0 flex-col gap-4 lg:flex">
          <TeamPanel model={model} draft={draft} target={t} side="them" likely={likely} />
          {outlook}
        </div>

        {tab === "line" && <div className="flex flex-col gap-3 lg:hidden">{outlook}</div>}
        {tab === "map" && (
          <div className="lg:hidden">
            <MapPanel model={model} mp={mp} onChange={() => setMapOpen(true)} initialOpen />
          </div>
        )}
      </main>

      <div className="px-4 pb-28 sm:px-6 lg:px-8 lg:pb-8">{footer}</div>

      <nav
        aria-label="Draft views"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/90 px-4 pt-2 pb-[max(12px,env(safe-area-inset-bottom))] backdrop-blur-md lg:hidden"
      >
        <div className="mx-auto grid max-w-md grid-cols-3 gap-1 rounded-2xl bg-surface p-1">
          {tabs.map((x) => (
            <button
              key={x.id}
              onClick={() => setTab(x.id)}
              aria-pressed={tab === x.id}
              className={cn("pressable h-11 rounded-xl text-sm font-semibold", tab === x.id ? "bg-subtle text-foreground" : "text-muted")}
            >
              {x.label}
            </button>
          ))}
        </div>
      </nav>
      {sheets}
    </div>
  );
}
