import { describe, expect, it } from "vitest";
import { rovingKey, rovingTarget } from "../src/roving";

describe("the arrow keys in a group that's one stop for Tab", () => {
  it("move across a row of tabs with Left and Right, and stop at the ends", () => {
    expect(rovingTarget("ArrowRight", 0, 3)).toBe(1);
    expect(rovingTarget("ArrowRight", 2, 3)).toBe(2); // the last: it stays
    expect(rovingTarget("ArrowLeft", 2, 3)).toBe(1);
    expect(rovingTarget("ArrowLeft", 0, 3)).toBe(0);
    expect(rovingTarget("ArrowDown", 1, 3)).toBeNull(); // not this group's keys
    expect(rovingTarget("ArrowUp", 1, 3)).toBeNull();
  });

  it("move down a list with Up and Down, leaving Left and Right for what's beside a row", () => {
    expect(rovingTarget("ArrowDown", 1, 3, true)).toBe(2);
    expect(rovingTarget("ArrowDown", 2, 3, true)).toBe(2);
    expect(rovingTarget("ArrowUp", 1, 3, true)).toBe(0);
    expect(rovingTarget("ArrowUp", 0, 3, true)).toBe(0);
    expect(rovingTarget("ArrowRight", 1, 3, true)).toBeNull();
    expect(rovingTarget("ArrowLeft", 1, 3, true)).toBeNull();
  });

  it("go to the ends with Home and End", () => {
    expect(rovingTarget("Home", 2, 5)).toBe(0);
    expect(rovingTarget("End", 0, 5)).toBe(4);
    expect(rovingTarget("Home", 2, 5, true)).toBe(0);
    expect(rovingTarget("End", 0, 5, true)).toBe(4);
  });

  it("are the group's keys: Left, Right, Home and End, and in a list Up and Down too", () => {
    for (const key of ["ArrowLeft", "ArrowRight", "Home", "End"]) expect(rovingKey(key) && rovingKey(key, true)).toBe(true);
    for (const key of ["ArrowUp", "ArrowDown"]) {
      expect(rovingKey(key)).toBe(false); // across a row of tabs they stay the robot's
      expect(rovingKey(key, true)).toBe(true);
    }
    for (const key of ["Enter", " ", "w", "Tab", "Escape"]) expect(rovingKey(key) || rovingKey(key, true)).toBe(false);
  });

  it("leave every other key alone, and an empty group", () => {
    for (const key of ["Enter", " ", "a", "Tab", "Escape", "Delete"]) expect(rovingTarget(key, 1, 3)).toBeNull();
    expect(rovingTarget("ArrowRight", -1, 0)).toBeNull();
    expect(rovingTarget("ArrowRight", -1, 3)).toBe(0); // from none of them: the first
    expect(rovingTarget("ArrowLeft", -1, 3)).toBe(2);
    expect(rovingTarget("ArrowDown", -1, 3, true)).toBe(0);
  });
});
