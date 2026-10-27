import { describe, expect, it } from "vitest";
import type { GamepadLike } from "../src/controller";
import { combine, fromGamepad, fromKeys, isDrivingKey, NEUTRAL, sameInput } from "../src/controller";

function pad(axes: number[], pressed: number[] = [], values: Record<number, number> = {}): GamepadLike {
  const buttons = Array.from({ length: 17 }, (_, i) => ({ pressed: pressed.includes(i), value: values[i] ?? (pressed.includes(i) ? 1 : 0) }));
  return { axes, buttons };
}

describe("the keyboard", () => {
  it("drives like the pygame viewer: W/S throttle, A/D turn, arrows tank and strafe", () => {
    const input = fromKeys(new Set(["KeyW", "KeyD", "ArrowLeft"]));
    expect(input.analog).toEqual({ LEFT_X: -127, LEFT_Y: 127, RIGHT_X: 127, RIGHT_Y: 0 });
    expect(fromKeys(new Set(["KeyW", "KeyS"])).analog.LEFT_Y).toBe(0); // both: they cancel
  });

  it("gives half a stick with Shift", () => {
    expect(fromKeys(new Set(["KeyW", "ShiftLeft"])).analog.LEFT_Y).toBe(63);
  });

  it("presses buttons, listed in the controller's order", () => {
    const input = fromKeys(new Set(["KeyJ", "KeyQ", "KeyT", "KeyL"]));
    expect(input.digital).toEqual(["L1", "UP", "Y", "A"]);
    expect(isDrivingKey("KeyR")).toBe(false); // restart, not a button
    expect(isDrivingKey("ShiftRight") && isDrivingKey("KeyH")).toBe(true);
  });
});

describe("a gamepad", () => {
  it("maps its sticks with up positive, and ignores a little drift", () => {
    const input = fromGamepad(pad([0.5, -1, 0.05, 1]));
    expect(input.analog).toEqual({ LEFT_X: 64, LEFT_Y: 127, RIGHT_X: 0, RIGHT_Y: -127 });
  });

  it("maps face buttons by position, and triggers pressed past halfway", () => {
    const input = fromGamepad(pad([0, 0, 0, 0], [0, 3, 4, 12], { 6: 0.3, 7: 0.9 }));
    expect(input.digital).toEqual(["L1", "R2", "UP", "X", "B"]);
  });

  it("is neutral when there's none", () => {
    expect(fromGamepad(null)).toBe(NEUTRAL);
  });
});

describe("several at once", () => {
  it("take each stick from whichever pushes it furthest, and every button", () => {
    const keys = fromKeys(new Set(["KeyW", "KeyQ"]));
    const gamepad = fromGamepad(pad([0, 0.5, -0.9, 0], [1]));
    const both = combine(keys, gamepad);
    expect(both.analog).toEqual({ LEFT_X: 0, LEFT_Y: 127, RIGHT_X: -114, RIGHT_Y: 0 });
    expect(both.digital).toEqual(["L1", "A"]);
    expect(sameInput(both, combine(gamepad, keys))).toBe(true);
    expect(sameInput(both, NEUTRAL)).toBe(false);
  });
});
