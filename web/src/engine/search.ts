// Port of src/mira/engine/search.py: expectimax over the rest of a 1-2-2-1 draft.
// Our turns take the best option; their turns weigh a typical Masters player's likely picks.

import type { Model } from "./model";

export const ORDER = ["F", "S", "S", "F", "F", "S"] as const;

export type Side = "us" | "them";

export type Settings = {
  ourK: number;
  ourPairs: number;
  theirN: number;
  theirPairs: number;
  pairPool: number;
};

export const DEFAULT_SETTINGS: Settings = { ourK: 8, ourPairs: 12, theirN: 5, theirPairs: 8, pairPool: 8 };
export const BAN_SETTINGS: Settings = { ourK: 6, ourPairs: 8, theirN: 4, theirPairs: 6, pairPool: 6 };

export type Option = { picks: number[]; prob: number | null; win: number };
export type Step = { side: Side; chosen: Option; alternatives: Option[] };
export type Result = {
  win: number;
  suggestions: Option[];
  line: Step[];
  turnSize: number;
  side: Side | "done";
};

export function turnsRemaining(weFirst: boolean, nOurs: number, nTheirs: number): [Side, number][] {
  const sides: Side[] = ORDER.map((s) => ((s === "F") === weFirst ? "us" : "them"));
  const prefix = sides.slice(0, nOurs + nTheirs);
  if (prefix.filter((s) => s === "us").length !== nOurs || prefix.filter((s) => s === "them").length !== nTheirs) {
    throw new Error(
      `${nOurs} of our picks and ${nTheirs} of theirs don't fit the 1-2-2-1 order with ${weFirst ? "us" : "them"} picking first`,
    );
  }
  const need = { us: nOurs, them: nTheirs };
  const seen = { us: 0, them: 0 };
  const out: [Side, number][] = [];
  for (const side of sides) {
    if (seen[side] < need[side]) {
      seen[side]++;
      continue;
    }
    const last = out.at(-1);
    if (last && last[0] === side) last[1]++;
    else out.push([side, 1]);
  }
  return out;
}

const key = (ours: readonly number[], theirs: readonly number[]) =>
  [...ours].sort((a, b) => a - b).join(",") + "|" + [...theirs].sort((a, b) => a - b).join(",");

function* combinations<T>(xs: readonly T[]): Generator<[T, T]> {
  for (let i = 0; i < xs.length; i++) for (let j = i + 1; j < xs.length; j++) yield [xs[i], xs[j]];
}

export class Searcher {
  private memo = new Map<string, { v: number; options: Option[] }>();

  constructor(
    private m: Model,
    private mp: number,
    private banned: ReadonlySet<number>,
    private allowed: ReadonlySet<number> | null = null,
    private s: Settings = DEFAULT_SETTINGS,
  ) {}

  private ours(ours: number[], theirs: number[], size: number): number[][] {
    const taken = new Set([...ours, ...theirs, ...this.banned]);
    let pool: number[] = [];
    for (let b = 0; b < this.m.B; b++) if (!taken.has(b) && (!this.allowed || this.allowed.has(b))) pool.push(b);
    if (pool.length < size) {
      // The player's pool is used up: fall back to every available brawler (teammates can pick them).
      pool = [];
      for (let b = 0; b < this.m.B; b++) if (!taken.has(b)) pool.push(b);
    }
    const gain = new Map(pool.map((b) => [b, this.m.gain(b, ours, theirs, this.mp)]));
    pool.sort((a, b) => gain.get(b)! - gain.get(a)!);
    const top = pool.slice(0, this.s.ourK);
    if (size === 1) return top.map((b) => [b]);
    const pairs = [...combinations(top)];
    const score = (p: [number, number]) => gain.get(p[0])! + gain.get(p[1])! + this.m.synergy(p[0], p[1], this.mp);
    const scores = new Map(pairs.map((p) => [p, score(p)]));
    pairs.sort((a, b) => scores.get(b)! - scores.get(a)!);
    return pairs.slice(0, this.s.ourPairs);
  }

  private theirs(ours: number[], theirs: number[], size: number): [number[], number][] {
    const taken = new Set([...ours, ...theirs, ...this.banned]);
    const p1 = this.m.pickProbs(theirs, ours, taken, this.mp);
    const ranked = [...p1.entries()].sort((a, b) => b[1] - a[1]);
    if (size === 1) {
      const top = ranked.slice(0, this.s.theirN);
      const z = top.reduce((acc, [, p]) => acc + p, 0);
      return top.map(([b, p]) => [[b], p / z]);
    }
    const singles = ranked.slice(0, this.s.pairPool).map(([b]) => b);
    const scored: [number[], number][] = [];
    for (const [a, b] of combinations(singles)) {
      const pab = this.m.pickProbs([...theirs, a], ours, new Set([...taken, a]), this.mp).get(b) ?? 0;
      const pba = this.m.pickProbs([...theirs, b], ours, new Set([...taken, b]), this.mp).get(a) ?? 0;
      scored.push([[a, b], p1.get(a)! * pab + p1.get(b)! * pba]);
    }
    scored.sort((x, y) => y[1] - x[1]);
    const top = scored.slice(0, this.s.theirPairs);
    const z = top.reduce((acc, [, p]) => acc + p, 0);
    return top.map(([picks, p]) => [picks, p / z]);
  }

  value(ours: number[], theirs: number[], turns: [Side, number][]): number {
    const k = key(ours, theirs);
    const hit = this.memo.get(k);
    if (hit) return hit.v;
    if (!turns.length) {
      const v = this.m.winProb(ours, theirs, this.mp);
      this.memo.set(k, { v, options: [] });
      return v;
    }
    const options = this.expand(ours, theirs, turns);
    const v =
      turns[0][0] === "us"
        ? Math.max(...options.map((o) => o.win))
        : options.reduce((acc, o) => acc + (o.prob ?? 0) * o.win, 0);
    this.memo.set(k, { v, options });
    return v;
  }

  private expand(ours: number[], theirs: number[], turns: [Side, number][]): Option[] {
    const [side, size] = turns[0];
    const rest = turns.slice(1);
    if (side === "us") {
      const opts = this.ours(ours, theirs, size).map((p) => ({ picks: p, prob: null, win: this.value([...ours, ...p], theirs, rest) }));
      return opts.sort((a, b) => b.win - a.win);
    }
    const opts = this.theirs(ours, theirs, size).map(([p, prob]) => ({
      picks: p,
      prob,
      win: this.value(ours, [...theirs, ...p], rest),
    }));
    return opts.sort((a, b) => b.prob! - a.prob!);
  }

  run(ours: number[], theirs: number[], weFirst: boolean, alternatives = 3): Result {
    const turns = turnsRemaining(weFirst, ours.length, theirs.length);
    if (!turns.length) return { win: this.m.winProb(ours, theirs, this.mp), suggestions: [], line: [], turnSize: 0, side: "done" };
    const win = this.value(ours, theirs, turns);
    const suggestions = this.memo.get(key(ours, theirs))!.options;
    const line: Step[] = [];
    let o = ours, t = theirs, rest = turns;
    while (rest.length) {
      const options = this.memo.get(key(o, t))!.options;
      const side = rest[0][0];
      const chosen = options[0];
      line.push({ side, chosen, alternatives: options.slice(1, 1 + alternatives) });
      if (side === "us") o = [...o, ...chosen.picks];
      else t = [...t, ...chosen.picks];
      rest = rest.slice(1);
      this.value(o, t, rest);
    }
    return { win, suggestions, line, turnSize: turns[0][1], side: turns[0][0] };
  }
}

export type BanSuggestion = { brawler: number; win: number; gain: number };

export function suggestBans(
  m: Model,
  mp: number,
  weFirst: boolean,
  alreadyBanned: ReadonlySet<number>,
  n = 5,
  candidates = 15,
  allowed: ReadonlySet<number> | null = null,
): BanSuggestion[] {
  const base = new Searcher(m, mp, new Set(alreadyBanned), allowed, BAN_SETTINGS).run([], [], weFirst).win;
  const p = m.pickProbs([], [], alreadyBanned, mp);
  const threat = (b: number) => p.get(b)! * (1 + Math.max(0, m.strength(b, mp)));
  const pool = [...p.keys()].sort((a, b) => threat(b) - threat(a)).slice(0, candidates);
  const out = pool.map((b) => {
    const win = new Searcher(m, mp, new Set([...alreadyBanned, b]), allowed, BAN_SETTINGS).run([], [], weFirst).win;
    return { brawler: b, win, gain: win - base };
  });
  return out.sort((a, b) => b.gain - a.gain).slice(0, n);
}
