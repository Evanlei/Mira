import type { Model } from "@/engine/model";
import { displayName } from "@/lib/names";

export type Term = { label: string; value: number; kind: "strength" | "synergy" | "matchup" };

/** The win model's terms for a finished draft, from our side, biggest effects first. */
export function explain(m: Model, ours: number[], theirs: number[], mp: number): Term[] {
  const n = (b: number) => displayName(m.names[b]);
  const terms: Term[] = [];
  for (const b of ours) terms.push({ label: `${n(b)} on this map`, value: m.strength(b, mp), kind: "strength" });
  for (const b of theirs) terms.push({ label: `Their ${n(b)} on this map`, value: -m.strength(b, mp), kind: "strength" });
  const pairs = (team: number[], sign: number, prefix: string) => {
    for (let i = 0; i < team.length; i++)
      for (let j = i + 1; j < team.length; j++)
        terms.push({ label: `${prefix}${n(team[i])} + ${n(team[j])}`, value: sign * m.synergy(team[i], team[j], mp), kind: "synergy" });
  };
  pairs(ours, 1, "");
  pairs(theirs, -1, "Their ");
  for (const a of ours) for (const b of theirs) terms.push({ label: `${n(a)} vs ${n(b)}`, value: m.matchup(a, b, mp), kind: "matchup" });
  return terms.filter((t) => Math.abs(t.value) > 0.005).sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
}
