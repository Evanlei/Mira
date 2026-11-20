// The TS engine must reproduce the Python reference engine (src/mira/engine) on the same model.json.
// Regenerate fixtures after retraining:
//   uv run python scripts/engine_fixtures.py web/public/model.json web/src/engine/parity.fixtures.json
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { Model, type ModelJson } from "./model";
import { Searcher, suggestBans, turnsRemaining } from "./search";

const root = join(__dirname, "..", "..");
const data = JSON.parse(readFileSync(join(root, "public", "model.json"), "utf8")) as ModelJson;
const model = new Model(data);
const fixtures = JSON.parse(readFileSync(join(__dirname, "parity.fixtures.json"), "utf8"));
// Cases marked "ranking" use the fixtures' test ranking block (uncertainty penalty + pick-rate prior).
const ranked = new Model({ ...data, ranking: fixtures.ranking });

type Opt = { picks: number[]; prob: number | null; win: number };
const sameOpts = (got: Opt[], want: Opt[]) => {
  expect(got.map((o) => o.picks)).toEqual(want.map((o) => o.picks));
  got.forEach((o, i) => {
    expect(o.win).toBeCloseTo(want[i].win, 9);
    if (want[i].prob === null) expect(o.prob).toBeNull();
    else expect(o.prob!).toBeCloseTo(want[i].prob!, 9);
  });
};

describe("parity with the Python engine", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cases: [number, any][] = fixtures.cases.map((c: unknown, i: number) => [i, c]);
  it.each(cases)("case %i", (_i, c) => {
    const pool = c.allowed ? new Set<number>(c.allowed) : null;
    const r = new Searcher((c.ranking ? ranked : model).withTier(c.tier ?? model.tier), c.map, new Set(c.bans), pool).run(c.ours, c.theirs, c.we_first);
    expect(r.side).toBe(c.side);
    expect(r.turnSize).toBe(c.turn_size);
    expect(r.win).toBeCloseTo(c.win, 9);
    sameOpts(r.suggestions, c.suggestions);
    expect(r.line.length).toBe(c.line.length);
    r.line.forEach((s, i) => {
      expect(s.side).toBe(c.line[i].side);
      sameOpts([s.chosen], [c.line[i].chosen]);
      sameOpts(s.alternatives, c.line[i].alternatives);
    });
  });

  it("ban suggestions", () => {
    const b = fixtures.bans;
    const got = suggestBans(model, b.map, b.we_first, new Set(), 5);
    expect(got.map((x) => x.brawler)).toEqual(b.result.map((x: { brawler: number }) => x.brawler));
    got.forEach((x, i) => expect(x.gain).toBeCloseTo(b.result[i].gain, 9));
  });

  it("ban suggestions with the ranking adjustment", () => {
    const b = fixtures.bans;
    const got = suggestBans(ranked, b.map, b.we_first, new Set(), 5);
    expect(got.map((x) => x.brawler)).toEqual(b.result_ranked.map((x: { brawler: number }) => x.brawler));
    got.forEach((x, i) => expect(x.gain).toBeCloseTo(b.result_ranked[i].gain, 9));
  });
});

describe("turn order", () => {
  it("follows 1-2-2-1", () => {
    expect(turnsRemaining(true, 0, 0)).toEqual([["us", 1], ["them", 2], ["us", 2], ["them", 1]]);
    expect(turnsRemaining(false, 1, 1)).toEqual([["us", 1], ["them", 2], ["us", 1]]);
    expect(() => turnsRemaining(true, 2, 1)).toThrow();
  });
});

describe("model", () => {
  it("is symmetric", () => {
    expect(model.winProb([0, 1, 2], [3, 4, 5], 0) + model.winProb([3, 4, 5], [0, 1, 2], 0)).toBeCloseTo(1, 12);
  });
  it("finds names", () => {
    expect(model.names[model.brawler("mr p")]).toBe("MR. P");
    expect(model.maps[model.map("hard rock")].map).toBe("Hard Rock Mine");
  });
});
