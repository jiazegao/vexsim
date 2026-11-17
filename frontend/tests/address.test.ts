import { describe, expect, it } from "vitest";
import type { Place } from "../src/address";
import { formatPlace, HOME, isStep, parsePlace } from "../src/address";

describe("the address keeps your place", () => {
  const places: [Place, string][] = [
    [{ page: "simulate" }, ""],
    [{ page: "simulate", run: "20261117-154527-ab12" }, "#/simulate?run=20261117-154527-ab12"],
    [{ page: "sweeps" }, "#/sweeps"],
    [{ page: "bench" }, "#/bench"],
    [{ page: "analyze" }, "#/analyze"],
    [{ page: "build" }, "#/build"],
    [{ page: "calibrate", tab: "session" }, "#/calibrate/session"],
    [{ page: "calibrate", tab: "check", session: "calibration/2026-11-07" }, "#/calibrate/check?session=calibration/2026-11-07"],
    [{ page: "edit", file: "examples/robots/1239e_2026-27.yaml" }, "#/edit?file=examples/robots/1239e_2026-27.yaml"],
    [{ page: "guide" }, "#/guide"],
    [{ page: "guide", doc: "calibration_guide" }, "#/guide/calibration_guide"],
    [{ page: "guide", doc: "readme", at: "7-the-browser-app-vexsim-ui" }, "#/guide/readme?at=7-the-browser-app-vexsim-ui"],
  ];

  it("writes each place as it reads, and reads it back", () => {
    for (const [place, hash] of places) {
      expect(formatPlace(place)).toBe(hash);
      expect(parsePlace(hash)).toEqual(place);
    }
  });

  it("escapes what an address can't hold, but for the slashes", () => {
    const place: Place = { page: "edit", file: "my robots/a&b #1 + 50%.yaml" };
    const hash = formatPlace(place);
    expect(hash).toBe("#/edit?file=my%20robots/a%26b%20%231%20%2B%2050%25.yaml");
    expect(parsePlace(hash)).toEqual(place);
    const session: Place = { page: "calibrate", tab: "session", session: "sessions/été 2026" };
    expect(parsePlace(formatPlace(session))).toEqual(session);
  });

  it("reads no address, or just the page, as that page", () => {
    expect(parsePlace("")).toEqual(HOME);
    expect(parsePlace("#")).toEqual(HOME);
    expect(parsePlace("#/")).toEqual(HOME);
    expect(parsePlace("#/simulate")).toEqual(HOME);
    expect(parsePlace("#/calibrate")).toEqual({ page: "calibrate", tab: "session" });
    expect(parsePlace("#/calibrate/nowhere")).toEqual({ page: "calibrate", tab: "session" });
    expect(parsePlace("#sweeps")).toEqual({ page: "sweeps" }); // without its slash
  });

  it("reads an address that names nothing as nothing", () => {
    expect(parsePlace("#/settings")).toBeNull();
    expect(parsePlace("#/edit")).toBeNull(); // no file
    expect(parsePlace("#top")).toBeNull();
  });

  it("makes a step of a new page, file or Calibrate tab, and not of a new run or session", () => {
    expect(isStep({ page: "simulate" }, { page: "calibrate", tab: "session" })).toBe(true);
    expect(isStep({ page: "calibrate", tab: "session" }, { page: "calibrate", tab: "check" })).toBe(true);
    expect(isStep({ page: "calibrate" }, { page: "calibrate", tab: "session" })).toBe(false);
    expect(isStep({ page: "edit", file: "a.yaml" }, { page: "edit", file: "b.yaml" })).toBe(true);
    expect(isStep({ page: "simulate" }, { page: "simulate", run: "r1" })).toBe(false);
    expect(isStep({ page: "simulate", run: "r1" }, { page: "simulate", run: "r2" })).toBe(false);
    expect(isStep({ page: "calibrate", tab: "session" }, { page: "calibrate", tab: "session", session: "s" })).toBe(false);
    expect(isStep({ page: "guide", doc: "readme" }, { page: "guide", doc: "cpp" })).toBe(true); // another document
    expect(isStep({ page: "guide", doc: "readme" }, { page: "guide", doc: "readme", at: "setup" })).toBe(true); // a heading: Back returns to where you were reading
    expect(isStep({ page: "guide", doc: "readme", at: "setup" }, { page: "guide", doc: "readme", at: "setup" })).toBe(false);
  });
});
