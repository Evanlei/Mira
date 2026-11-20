import { describe, expect, it } from "vitest";

import { displayMode, displayName, gainPts, initials } from "./names";

describe("names", () => {
  it("formats API names", () => {
    expect(displayName("EL PRIMO")).toBe("El Primo");
    expect(displayName("MR. P")).toBe("Mr. P");
    expect(displayName("8-BIT")).toBe("8-Bit");
    expect(displayName("R-T")).toBe("R-T");
    expect(initials("EL PRIMO")).toBe("EP");
    expect(initials("SHELLY")).toBe("SH");
    expect(displayMode("brawlBall")).toBe("Brawl Ball");
  });
  it("formats gains", () => {
    expect(gainPts(0.012)).toBe("+1.2");
    expect(gainPts(-0.004)).toBe("−0.4");
    expect(gainPts(-0.0001)).toBe("≈0");
  });
});
