import { describe, expect, it } from "vitest";

import { EMPTY, apply, applyAll, pickSlots, target, unavailableFor } from "./draft";

describe("draft state", () => {
  const d0 = { ...EMPTY, map: 0 };
  it("fills our bans, then theirs, then picks in 1-2-2-1 order", () => {
    let d = applyAll(d0, [1, 2, 3]);
    expect(d.bansUs).toEqual([1, 2, 3]);
    expect(target(d)).toEqual({ kind: "ban", side: "them" });
    d = applyAll(d, [1, 4, 5]); // both teams may ban the same brawler
    expect(d.bansThem).toEqual([1, 4, 5]);
    expect(target(d)).toEqual({ kind: "pick", side: "us", size: 1 });
    d = applyAll(d, [10, 11, 12, 13]);
    expect(d.ours).toEqual([10, 13]); // order: us, them, them, us, us, them
    expect(d.theirs).toEqual([11, 12]);
    expect(target(d)).toEqual({ kind: "pick", side: "us", size: 1 }); // second of our double pick
  });
  it("skipping bans goes straight to picks; banned and picked brawlers are unavailable", () => {
    let d = { ...apply(d0, 7), skipBans: true };
    expect(target(d).kind).toBe("pick");
    expect(unavailableFor(d, 7, target(d))).toBe(true);
    d = apply(d, 7);
    expect(d.ours).toEqual([]); // ignored
    d = apply(d, 8);
    expect(apply(d, 8)).toBe(d); // can't pick twice
  });
  it("ends after six picks", () => {
    const d = applyAll({ ...d0, skipBans: true }, [1, 2, 3, 4, 5, 6]);
    expect(target(d)).toEqual({ kind: "done" });
  });
  it("labels slots", () => {
    expect(pickSlots(false).map((s) => s.side)).toEqual(["them", "us", "us", "them", "them", "us"]);
  });
});
