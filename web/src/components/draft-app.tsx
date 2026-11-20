"use client";

import { RotateCcw, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Model, type ModelJson } from "@/engine/model";
import { Searcher, suggestBans, type BanSuggestion, type Option, type Result, type Step } from "@/engine/search";
import { EMPTY, apply, applyAll, banned, pickSlots, target, unavailableFor, type Draft } from "@/lib/draft";
import { gainPts, pct } from "@/lib/names";

import { Board, DraftScreen } from "./board";
import { Composer } from "./composer";
import { Line, Section, Summary } from "./panels";
import { MapPanel } from "./map-panel";
import { BrawlerSheet, MapSheet, type Ranked } from "./sheets";
import { Cluster, SlashTabs, cn } from "./ui";

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
  const turnLabel =
    t.kind === "ban" ? (t.side === "us" ? "Your ban" : "Their ban") : t.kind === "pick" ? (t.side === "us" ? "Your pick" : "Their pick") : "Draft complete";
  const featured = useMemo(() => {
    // Three most-played brawlers, for the inline cluster in the intro.
    const counts = model.data.games?.brawler ?? [];
    return [...counts.keys()].sort((a, b) => counts[b] - counts[a]).slice(0, 3);
  }, [model]);

  return (
    <div className="mx-auto w-full max-w-2xl px-5 pt-12 pb-[max(32px,env(safe-area-inset-bottom))] sm:px-6 sm:pt-16 lg:max-w-7xl lg:px-10 lg:pt-10">
      <header className="enter space-y-4 sm:space-y-5 lg:space-y-3">
        <h1 className="text-3xl leading-snug tracking-tight sm:text-4xl">
          <strong>Mira</strong> <span className="text-muted">(draft coach)</span>
        </h1>
        <p className="max-w-3xl text-[17px] leading-relaxed text-foreground/90 sm:text-xl lg:text-lg">
          Pick a map and I’ll suggest your best Brawl Stars Ranked picks and bans, learned from{" "}
          <Cluster model={model} picks={featured} size={28} /> <strong className="tabular">{games.toLocaleString()} Masters games</strong>.
        </p>
        <hr className="border-border" />
      </header>

      <main className="mt-8 space-y-4 lg:mt-6">
        <div className={cn("enter enter-1 space-y-3", mp !== null && "lg:hidden")}>
          <MapPanel model={model} mp={mp} onChange={() => setMapOpen(true)} />
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
        </div>

        {mp !== null && (
          <>
            <Section
              className="enter enter-2"
              title={turnLabel}
              toolbar={
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
              }
              aside={
                <span className="flex gap-0.5">
                  <IconButton label="Undo" onClick={undo} disabled={!history.length}>
                    <Undo2 size={16} strokeWidth={1.5} absoluteStrokeWidth />
                  </IconButton>
                  <IconButton label="Reset draft" onClick={reset} disabled={!started && !draft.skipBans}>
                    <RotateCcw size={16} strokeWidth={1.5} absoluteStrokeWidth />
                  </IconButton>
                </span>
              }
            >
              <Progress draft={draft} />
              <div className="lg:hidden">
                <Board model={model} draft={draft} target={t} />
              </div>
              <div className="hidden lg:block">
                <DraftScreen model={model} draft={draft} target={t} mp={mp} onChangeMap={() => setMapOpen(true)} />
              </div>
            </Section>

            <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
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

            {line && result && result.side !== "done" && (
              <Line
                model={model}
                line={line}
                previewing={preview !== null}
                onPreview={(step, option) => (step === 0 ? commit(applyAll(draft, option.picks)) : setPreview({ step, option }))}
                onReset={() => setPreview(null)}
              />
            )}
            </div>
          </>
        )}
      </main>

      <footer className="mt-12 space-y-1 border-t border-border pt-6 text-xs leading-relaxed text-muted">
        <p>
          Trained on all-Masters Ranked matches up to {model.data.data_window[1].slice(0, 10)}
          {model.data.patches?.length ? <>, latest patch {model.data.patches.at(-1)!.date}</> : null}. Win chances assume your
          best play and typical Masters picks from them, so they run high: trust the order more than the number.
        </p>
        <p>Not affiliated with Supercell. Game art © Supercell, via Brawlify.</p>
      </footer>

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

/** Where we are in the draft: bans, then the six picks in order, colored by team. */
function Progress({ draft }: { draft: Draft }) {
  const slots = pickSlots(draft.weFirst);
  const bansDone = draft.skipBans || (draft.bansUs.length === 3 && draft.bansThem.length === 3);
  const picked = { us: draft.ours.length, them: draft.theirs.length };
  const next = slots.find((s) => s.index >= picked[s.side]);
  return (
    <div className="mb-5 flex items-center gap-1" aria-hidden>
      <span className={cn("h-1 flex-[1.5] rounded-full", bansDone ? "bg-foreground/25" : "bg-accent")} />
      <span className="w-1" />
      {slots.map((s) => {
        const done = s.index < picked[s.side];
        const isNext = bansDone && next && (s === next || ((next.order === 2 || next.order === 4) && s.order === next.order + 1 && s.side === next.side));
        return (
          <span
            key={s.order}
            className={cn("h-1 flex-1 rounded-full", done ? (s.side === "us" ? "bg-us" : "bg-them") : isNext ? "bg-accent/50" : "bg-foreground/10")}
          />
        );
      })}
    </div>
  );
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className="pressable grid size-9 place-items-center rounded-full text-muted hover:text-foreground disabled:opacity-30"
    >
      {children}
    </button>
  );
}
