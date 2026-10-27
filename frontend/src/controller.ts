// The virtual V5 controller: the keyboard, a gamepad and the on-screen controller, mapped
// as the pygame viewer maps them. Sticks run from -127 to 127, up and right positive.

export type Channel = "LEFT_X" | "LEFT_Y" | "RIGHT_X" | "RIGHT_Y";
export const CHANNELS: readonly Channel[] = ["LEFT_X", "LEFT_Y", "RIGHT_X", "RIGHT_Y"];
export const BUTTONS = ["L1", "L2", "R1", "R2", "UP", "DOWN", "LEFT", "RIGHT", "X", "B", "Y", "A"] as const;

export interface ControllerInput {
  analog: Record<Channel, number>;
  digital: string[]; // pressed buttons, in BUTTONS order
}

export const NEUTRAL: ControllerInput = Object.freeze({
  analog: Object.freeze({ LEFT_X: 0, LEFT_Y: 0, RIGHT_X: 0, RIGHT_Y: 0 }),
  digital: [],
}) as ControllerInput;

// Keys by position (KeyboardEvent.code), so they sit in the same place on any layout.
export const KEY_STICKS: Readonly<Record<string, [Channel, 1 | -1]>> = {
  KeyW: ["LEFT_Y", 1], // arcade throttle
  KeyS: ["LEFT_Y", -1],
  KeyD: ["RIGHT_X", 1], // arcade turn
  KeyA: ["RIGHT_X", -1],
  ArrowUp: ["RIGHT_Y", 1], // tank: the right stick's forward
  ArrowDown: ["RIGHT_Y", -1],
  ArrowRight: ["LEFT_X", 1], // strafe
  ArrowLeft: ["LEFT_X", -1],
};
export const KEY_BUTTONS: Readonly<Record<string, string>> = {
  KeyQ: "L1",
  KeyZ: "L2",
  KeyE: "R1",
  KeyC: "R2",
  KeyI: "X",
  KeyL: "A",
  KeyK: "B",
  KeyJ: "Y",
  KeyT: "UP",
  KeyG: "DOWN",
  KeyF: "LEFT",
  KeyH: "RIGHT",
};
const HALF = new Set(["ShiftLeft", "ShiftRight"]); // half stick, for fine control

export function isDrivingKey(code: string): boolean {
  return code in KEY_STICKS || code in KEY_BUTTONS || HALF.has(code);
}

/** The controller as the held keys (KeyboardEvent.code values) set it. */
export function fromKeys(held: ReadonlySet<string>): ControllerInput {
  const scale = [...HALF].some((code) => held.has(code)) ? 63 : 127;
  const analog = { ...NEUTRAL.analog };
  const pressed = new Set<string>();
  for (const code of held) {
    const stick = KEY_STICKS[code];
    if (stick) analog[stick[0]] += stick[1] * scale;
    const button = KEY_BUTTONS[code];
    if (button) pressed.add(button);
  }
  return { analog, digital: BUTTONS.filter((b) => pressed.has(b)) };
}

/** What the controller code reads from a gamepad (the browser's Gamepad, or anything
 * shaped like one). The face buttons map to the V5's by position: Xbox Y (top) is the
 * V5's X, B (right) is A, A (bottom) is B, X (left) is Y; bumpers are L1 and R1,
 * triggers L2 and R2. */
export interface GamepadLike {
  axes: readonly number[];
  buttons: readonly { pressed: boolean; value: number }[];
}

const DEADZONE = 0.08;
// The W3C standard mapping's button indexes.
const PAD_BUTTONS: [number, string][] = [
  [0, "B"],
  [1, "A"],
  [2, "Y"],
  [3, "X"],
  [4, "L1"],
  [5, "R1"],
  [12, "UP"],
  [13, "DOWN"],
  [14, "LEFT"],
  [15, "RIGHT"],
];
const PAD_TRIGGERS: [number, string][] = [
  [6, "L2"],
  [7, "R2"],
];

export function fromGamepad(pad: GamepadLike | null | undefined): ControllerInput {
  if (!pad) return NEUTRAL;
  const axis = (i: number, sign = 1) => {
    const value = pad.axes[i] ?? 0;
    return Math.abs(value) < DEADZONE ? 0 : Math.round(sign * value * 127);
  };
  const pressed = new Set<string>();
  for (const [index, button] of PAD_BUTTONS) if (pad.buttons[index]?.pressed) pressed.add(button);
  for (const [index, button] of PAD_TRIGGERS) if ((pad.buttons[index]?.value ?? 0) > 0.5) pressed.add(button);
  return {
    analog: { LEFT_X: axis(0), LEFT_Y: axis(1, -1), RIGHT_X: axis(2), RIGHT_Y: axis(3, -1) },
    digital: BUTTONS.filter((b) => pressed.has(b)),
  };
}

/** Several sources at once: each stick channel from whichever pushes it furthest, and
 * every button any of them presses. */
export function combine(...inputs: ControllerInput[]): ControllerInput {
  const analog = { ...NEUTRAL.analog };
  const pressed = new Set<string>();
  for (const input of inputs) {
    for (const channel of CHANNELS) {
      const value = Math.max(-127, Math.min(127, input.analog[channel]));
      if (Math.abs(value) > Math.abs(analog[channel])) analog[channel] = value;
    }
    for (const button of input.digital) pressed.add(button);
  }
  return { analog, digital: BUTTONS.filter((b) => pressed.has(b)) };
}

export function sameInput(a: ControllerInput, b: ControllerInput): boolean {
  return (
    CHANNELS.every((channel) => a.analog[channel] === b.analog[channel]) &&
    a.digital.length === b.digital.length &&
    a.digital.every((button, i) => button === b.digital[i])
  );
}

/** The first connected gamepad the browser knows of, if any. */
export function firstGamepad(): Gamepad | null {
  if (typeof navigator === "undefined" || !navigator.getGamepads) return null;
  for (const pad of navigator.getGamepads()) if (pad && pad.connected) return pad;
  return null;
}
