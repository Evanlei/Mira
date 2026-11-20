"use client";

import { ChevronDown, RotateCcw, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Model, type ModelJson } from "@/engine/model";
import { Searcher, suggestBans, type BanSuggestion, type Option, type Result, type Step } from "@/engine/search";
import { EMPTY, apply, applyAll, banned, target, unavailableFor, type Draft } from "@/lib/draft";
import { displayMode, gainPts, pct } from "@/lib/names";

import { Board } from "./board";
import { Bans, Card, Line, Suggestions, Summary } from "./panels";
import { BrawlerSheet, MapSheet, type Ranked } from "./sheets";
import { Segmented, cn } from "./ui";

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
    <div className="mx-auto flex w-full max-w-[560px] flex-col gap-3 px-4 pt-6" aria-busy aria-label="Loading">
      {[96, 260, 180].map((h, i) => (
        <div key={i} className="surface rounded-[28px]" style={{ height: h }} />
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

  // Search for the current pick turn (fast: well under 100 ms in the browser).
  const result: Result | null = useMemo(() => {
    if (mp === null || t.kind === "ban") return null;
    return new Searcher(model, mp, bannedSet).run(draft.ours, draft.theirs, draft.weFirst);
  }, [model, mp, t.kind, bannedSet, draft.ours, draft.theirs, draft.weFirst]);

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

  return (
    <main className="mx-auto flex w-full max-w-[560px] flex-col gap-3 px-4 pt-5 pb-[max(24px,env(safe-area-inset-bottom))]">
      <header className="enter flex items-end justify-between gap-3 px-1">
        <div>
          <h1 className="text-[22px] leading-tight font-semibold tracking-tight">Mira</h1>
          <p className="text-[13px] text-muted">Brawl Stars Ranked draft coach</p>
        </div>
        <p className="tabular text-end text-[11px] leading-tight text-faint">
          {model.data.n_matches.toLocaleString()} Masters matches
          <br />
          to {model.data.data_window[1].slice(0, 10)}
        </p>
      </header>

      <Card title="Setup" className="enter enter-1">
        <button
          onClick={() => setMapOpen(true)}
          className="pressable flex min-h-14 w-full items-center justify-between gap-3 rounded-[12px] bg-surface-2 ps-3 pe-2.5 text-start"
        >
          <span className="flex min-w-0 flex-col">
            <span className="text-[12px] text-muted">{mp === null ? "Map" : displayMode(model.maps[mp].mode)}</span>
            <span className={cn("truncate text-[16px] font-medium", mp === null && "text-muted")}>
              {mp === null ? "Choose a map" : model.maps[mp].map}
            </span>
          </span>
          <ChevronDown size={18} strokeWidth={1.5} absoluteStrokeWidth className="shrink-0 text-muted" />
        </button>
        <div className="mt-2">
          <Segmented
            label="Who picks first"
            value={draft.weFirst ? "us" : "them"}
            onChange={(v) => commit({ ...EMPTY, map: draft.map, weFirst: v === "us" })}
            options={[
              { value: "us", label: "We pick first" },
              { value: "them", label: "They pick first" },
            ]}
          />
        </div>
      </Card>

      {mp === null ? (
        <p className="enter enter-2 px-1 py-6 text-center text-[14px] text-muted">Choose the map to start the draft.</p>
      ) : (
        <>
          <Card
            title={t.kind === "ban" ? "Bans" : t.kind === "done" ? "Draft" : t.side === "us" ? "Your turn" : "Their turn"}
            aside={
              <div className="flex gap-1">
                <IconButton label="Undo" onClick={undo} disabled={!history.length}>
                  <Undo2 size={16} strokeWidth={1.5} absoluteStrokeWidth />
                </IconButton>
                <IconButton label="Reset draft" onClick={reset} disabled={!draft.ours.length && !draft.theirs.length && !bannedSet.size && !draft.skipBans}>
                  <RotateCcw size={16} strokeWidth={1.5} absoluteStrokeWidth />
                </IconButton>
              </div>
            }
          >
            <Board model={model} draft={draft} target={t} onSlot={() => setPickerOpen(true)} />
            <div className="mt-3 flex gap-2">
              {t.kind !== "done" && (
                <button
                  onClick={() => setPickerOpen(true)}
                  className="pressable h-11 flex-1 rounded-[12px] bg-accent text-[15px] font-semibold text-white"
                >
                  {t.kind === "ban" ? `Add ${t.side === "us" ? "your" : "their"} ban` : t.side === "us" ? "Add your pick" : "Add their pick"}
                </button>
              )}
              {t.kind === "ban" && (
                <button
                  onClick={() => commit({ ...draft, skipBans: true })}
                  className="pressable h-11 rounded-[12px] bg-surface-2 px-4 text-[15px] font-medium"
                >
                  Skip bans
                </button>
              )}
            </div>
          </Card>

          {t.kind === "ban" && (
            <div>
              <Bans model={model} bans={bans} loading={bans === null} onApply={(b) => commit(apply(draft, b))} />
            </div>
          )}

          {result && result.side !== "done" && (
            <>
              <div>
                <Suggestions model={model} result={result} mp={mp} onApply={(picks) => commit(applyAll(draft, picks))} />
              </div>
              {line && (
                <Line
                  model={model}
                  line={line}
                  previewing={preview !== null}
                  onPreview={(step, option) => (step === 0 ? commit(applyAll(draft, option.picks)) : setPreview({ step, option }))}
                  onReset={() => setPreview(null)}
                />
              )}
            </>
          )}

          {result && result.side === "done" && (
            <Summary model={model} ours={draft.ours} theirs={draft.theirs} mp={mp} win={result.win} />
          )}
        </>
      )}

      <footer className="px-1 pt-4 text-[11px] leading-relaxed text-faint">
        Not affiliated with Supercell. Data from the official Brawl Stars API, all-Masters Ranked matches only.
        {model.data.patches?.length ? (
          <>
            {" "}Latest patch in the model: <span className="whitespace-nowrap">{model.data.patches.at(-1)!.date}</span>.
          </>
        ) : null}
      </footer>

      <MapSheet model={model} open={mapOpen} onClose={() => setMapOpen(false)} current={mp} onPick={(i) => commit({ ...draft, map: i })} />
      <BrawlerSheet
        model={model}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title={pickerTitle}
        isUnavailable={(b) => unavailableFor(draft, b, t)}
        ranked={ranked}
        rankedLabel={t.kind === "ban" ? "Suggested bans" : t.kind === "pick" && t.side === "us" ? "Suggested" : "Most likely"}
        onPick={(b) => commit(apply(draft, b))}
      />
    </main>
  );
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className="pressable grid size-10 place-items-center rounded-full text-muted disabled:opacity-35"
    >
      {children}
    </button>
  );
}
