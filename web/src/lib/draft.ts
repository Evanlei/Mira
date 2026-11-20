import { turnsRemaining, type Side } from "@/engine/search";

export type Draft = {
  map: number | null;
  weFirst: boolean;
  ours: number[];        // in pick order
  theirs: number[];
  bansUs: number[];      // up to 3 each; both teams may ban the same brawler
  bansThem: number[];
  skipBans: boolean;
};

export const EMPTY: Draft = { map: null, weFirst: true, ours: [], theirs: [], bansUs: [], bansThem: [], skipBans: false };

export type Target = { kind: "ban"; side: Side } | { kind: "pick"; side: Side; size: number } | { kind: "done" };

export const banned = (d: Draft) => new Set([...d.bansUs, ...d.bansThem]);
export const taken = (d: Draft) => new Set([...d.ours, ...d.theirs, ...d.bansUs, ...d.bansThem]);

export function inBanPhase(d: Draft): boolean {
  return !d.skipBans && d.ours.length + d.theirs.length === 0 && d.bansUs.length + d.bansThem.length < 6;
}

/** What the next tap fills: a ban slot (ours first, then theirs) or the next pick in 1-2-2-1 order. */
export function target(d: Draft): Target {
  if (inBanPhase(d)) return { kind: "ban", side: d.bansUs.length < 3 ? "us" : "them" };
  const turns = turnsRemaining(d.weFirst, d.ours.length, d.theirs.length);
  if (!turns.length) return { kind: "done" };
  return { kind: "pick", side: turns[0][0], size: turns[0][1] };
}

/** Is brawler b unavailable for this target? (A brawler banned by one team can still be banned by the other.) */
export function unavailableFor(d: Draft, b: number, t: Target): boolean {
  if (t.kind === "ban") return (t.side === "us" ? d.bansUs : d.bansThem).includes(b) || d.ours.includes(b) || d.theirs.includes(b);
  return taken(d).has(b);
}

export function apply(d: Draft, b: number): Draft {
  const t = target(d);
  if (t.kind === "done" || unavailableFor(d, b, t)) return d;
  if (t.kind === "ban") return t.side === "us" ? { ...d, bansUs: [...d.bansUs, b] } : { ...d, bansThem: [...d.bansThem, b] };
  return t.side === "us" ? { ...d, ours: [...d.ours, b] } : { ...d, theirs: [...d.theirs, b] };
}

export function applyAll(d: Draft, picks: number[]): Draft {
  return picks.reduce(apply, d);
}

/** Order of pick slots for display: slot i (0..5) belongs to side, and is the n-th pick of that side. */
export function pickSlots(weFirst: boolean): { side: Side; index: number; order: number }[] {
  const counts = { us: 0, them: 0 };
  return ["F", "S", "S", "F", "F", "S"].map((s, i) => {
    const side: Side = (s === "F") === weFirst ? "us" : "them";
    return { side, index: counts[side]++, order: i + 1 };
  });
}
