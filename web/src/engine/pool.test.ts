// The player's brawler pool (power-11s): our side drafts only from it, theirs from everything.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { Model, type ModelJson } from "./model";
import { Searcher, suggestBans } from "./search";

const model = new Model(JSON.parse(readFileSync(join(__dirname, "..", "..", "public", "model.json"), "utf8")) as ModelJson);
const mp = model.map("hard rock");
// A deliberately unusual pool: the 12 least-played brawlers, so it can't match the free search.
const counts = model.data.games!.brawler;
const pool = new Set([...counts.keys()].sort((a, b) => counts[a] - counts[b]).slice(0, 12));

describe("our brawler pool", () => {
  it("keeps every line of ours inside the pool, every turn", () => {
    const r = new Searcher(model, mp, new Set(), pool).run([], [], true);
    expect(r.suggestions.length).toBeGreaterThan(0);
    for (const o of r.suggestions) for (const b of o.picks) expect(pool.has(b)).toBe(true);
    for (const s of r.line.filter((s) => s.side === "us"))
      for (const o of [s.chosen, ...s.alternatives]) for (const b of o.picks) expect(pool.has(b)).toBe(true);
  });

  it("leaves their side unrestricted", () => {
    const r = new Searcher(model, mp, new Set(), pool).run([], [], true);
    const theirs = r.line.filter((s) => s.side === "them").flatMap((s) => s.chosen.picks);
    expect(theirs.some((b) => !pool.has(b))).toBe(true);
  });

  it("changes the prediction (a weak pool should not look as good as the free search)", () => {
    const free = new Searcher(model, mp, new Set()).run([], [], true).win;
    const restricted = new Searcher(model, mp, new Set(), pool).run([], [], true).win;
    expect(restricted).toBeLessThan(free);
  });

  it("falls back to every brawler when the pool can't fill the turn (teammates pick their own)", () => {
    const one = new Set([[...pool][0]]);
    // They pick first, so our first turn is a double pick: one brawler can't fill it.
    const r = new Searcher(model, mp, new Set(), one).run([], [], false);
    const ours = r.line.find((s) => s.side === "us")!;
    expect(ours.chosen.picks).toHaveLength(2);
    expect(ours.chosen.picks.some((b) => !one.has(b))).toBe(true);
  });

  it("judges bans against what we can field", () => {
    const free = suggestBans(model, mp, true, new Set(), 5, 10).map((x) => x.brawler);
    const restricted = suggestBans(model, mp, true, new Set(), 5, 10, pool).map((x) => x.brawler);
    expect(restricted).not.toEqual(free);
  });
});

describe("ban suggestions when we pick first", () => {
  it("never suggest banning our own top first pick", () => {
    const data = JSON.parse(readFileSync(join(__dirname, "..", "..", "public", "model.json"), "utf8")) as ModelJson;
    const m = new Model(data);
    for (const mp of [0, 1, 2]) {
      const first = new Searcher(m, mp, new Set()).run([], [], true).suggestions[0].picks[0];
      expect(suggestBans(m, mp, true, new Set(), 5).map((x) => x.brawler)).not.toContain(first);
    }
  });
});
