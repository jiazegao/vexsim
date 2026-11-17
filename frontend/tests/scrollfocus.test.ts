import { describe, expect, it } from "vitest";
import { needsStop } from "../src/scrollfocus";

describe("a box that scrolls", () => {
  it("takes a stop for Tab while what's in it doesn't fit", () => {
    expect(needsStop(true, false)).toBe(true);
    expect(needsStop(false, false)).toBe(false); // it fits: nothing to scroll
  });

  it("takes none when something in it takes the keyboard: the box scrolls to that", () => {
    expect(needsStop(true, true)).toBe(false);
    expect(needsStop(false, true)).toBe(false);
  });
});
