import { describe, expect, it } from "vitest";
import { fixed, formatTime, lemlibTheta, poseError, wrapDegrees } from "../src/pose";

describe("poses", () => {
  it("converts a vexsim heading to LemLib's theta", () => {
    expect(lemlibTheta(0)).toBe(90); // facing +x
    expect(lemlibTheta(90)).toBe(0); // facing +y
    expect(lemlibTheta(180)).toBe(270);
    expect(lemlibTheta(-90)).toBe(180);
    expect(Object.is(lemlibTheta(450), 0)).toBe(true); // never -0
  });

  it("wraps headings into (-180, 180]", () => {
    expect(wrapDegrees(190)).toBe(-170);
    expect(wrapDegrees(-180)).toBe(180);
    expect(wrapDegrees(540)).toBe(180);
    expect(wrapDegrees(-725)).toBe(-5);
  });

  it("measures position and heading error the short way round", () => {
    const [distance, heading] = poseError([3, 4, 179], [0, 0, -179]);
    expect(distance).toBeCloseTo(5);
    expect(heading).toBeCloseTo(2);
  });

  it("formats numbers and times for people", () => {
    expect(fixed(-0.04)).toBe("0.0");
    expect(fixed(2.345, 2)).toBe("2.35");
    expect(fixed(null)).toBe("—");
    expect(fixed(Number.NaN)).toBe("—");
    expect(formatTime(12.3456)).toBe("12.35 s");
    expect(formatTime(75.5)).toBe("1:15.50");
    expect(formatTime(Number.POSITIVE_INFINITY)).toBe("—");
  });
});
