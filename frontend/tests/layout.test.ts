import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { keepPanel, NARROW, panelKey, readPanel, SHORT } from "../src/layout";

describe("the shell's panels (phase 15.2)", () => {
  const kept = new Map<string, string>();
  beforeEach(() => {
    kept.clear();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => kept.get(key) ?? null,
      setItem: (key: string, value: string) => void kept.set(key, value),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("keeps a panel's choice for windows of one kind only", () => {
    expect(readPanel("sidebar", false)).toBeNull(); // nothing chosen: as the window asks
    keepPanel("sidebar", false, false); // folded away in a large window
    expect(readPanel("sidebar", false)).toBe(false);
    expect(readPanel("sidebar", true)).toBeNull(); // a small window still decides for itself
    keepPanel("sidebar", true, true);
    expect([readPanel("sidebar", true), readPanel("sidebar", false)]).toEqual([true, false]);
    expect(panelKey("key", false)).toBe("vexsim.panel.key.large");
    expect(readPanel("readout", true)).toBeNull(); // each panel has its own
  });

  it("works without storage, keeping nothing", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("no storage here");
      },
      setItem: () => {
        throw new Error("no storage here");
      },
    });
    keepPanel("bottom", true, true);
    expect(readPanel("bottom", true)).toBeNull();
  });

  it("calls a laptop's window short, and half a screen narrow", () => {
    expect(SHORT).toBe("(max-height: 800px)"); // 768 and under, with or without the browser's bars
    expect(NARROW).toBe("(max-width: 1100px)");
  });
});
