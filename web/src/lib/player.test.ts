import { describe, expect, it } from "vitest";

import { normalizeTag } from "./player";

describe("normalizeTag", () => {
  it("strips the hash, spaces and case", () => {
    expect(normalizeTag("#2pp")).toBe("2PP");
    expect(normalizeTag("  #9 lq ") ).toBe("9LQ");
  });
  it("reads a typed O as a zero", () => {
    expect(normalizeTag("#8GOL")).toBe("8G0L");
  });
  it("rejects characters tags never use", () => {
    expect(normalizeTag("#ABC")).toBeNull();
    expect(normalizeTag("")).toBeNull();
    expect(normalizeTag("#2P")).toBeNull();
  });
});
