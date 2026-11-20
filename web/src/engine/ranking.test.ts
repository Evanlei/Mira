// Ranking our picks: the uncertainty penalty and pick-rate prior change which pick we take, never a win %.
import { describe, expect, it } from "vitest";

import { Model, type ModelJson } from "./model";
import { Searcher } from "./search";

// Brawler 1 has a slightly higher estimate than 2, but few games (wide sd) and a tiny pick rate.
function toy(ranking?: { kappa: number; gamma: number }): Model {
  const B = 8;
  const base = Array.from({ length: B }, (_, b) => [b === 1 ? -8 : -2]);
  const data = {
    format: 1,
    trained_at: "",
    data_window: ["", ""],
    n_matches: 0,
    brawlers: Array.from({ length: B }, (_, i) => ({ id: i, name: `B${i}` })),
    modes: ["m"],
    maps: [{ mode: "m", map: "x" }],
    win_model: {
      global: [0, 0.32, 0.3, 0, 0, 0, 0, 0],
      mode: Array.from({ length: B }, () => [0]),
      map: Array.from({ length: B }, () => [0]),
      synergy: [],
      synergy_mode: [],
      matchup: [],
      matchup_mode: [],
    },
    pick_model: { alpha: 1, beta: 1, log_base: base, ally_lift: [], enemy_lift: [] },
    ...(ranking && { ranking: { ...ranking, strength_sd: [Array.from({ length: B }, (_, b) => [b === 1 ? 0.2 : b === 0 ? 0.05 : 0.03])] } }),
  } as ModelJson;
  return new Model(data);
}

const run = (m: Model) => new Searcher(m, 0, new Set()).run([3, 4], [5, 6, 7], false);

describe("ranking our picks", () => {
  it("takes the higher estimate without a ranking block (older model.json)", () => {
    expect(run(toy()).suggestions[0].picks).toEqual([1]);
  });
  it("prefers the well-measured brawler under the uncertainty penalty", () => {
    expect(run(toy({ kappa: 1, gamma: 0 })).suggestions[0].picks).toEqual([2]);
  });
  it("prefers what players pick under the pick-rate prior", () => {
    expect(run(toy({ kappa: 0, gamma: 0.05 })).suggestions[0].picks).toEqual([2]);
  });
  it("reports the plain win chance of the pick it takes", () => {
    const m = toy({ kappa: 1, gamma: 0.05 });
    const r = run(m);
    expect(r.suggestions[0].win).toBeCloseTo(m.winProb([3, 4, 2], [5, 6, 7], 0), 12);
    expect(r.win).toBe(r.suggestions[0].win);
  });
});
