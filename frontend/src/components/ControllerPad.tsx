import type { PointerEvent as ReactPointerEvent } from "react";
import type { Channel, ControllerInput } from "../controller";
import { BUTTONS } from "../controller";
import type { ControllerState } from "../protocol";

const STICKS: [string, Channel, Channel][] = [
  ["Left stick", "LEFT_X", "LEFT_Y"],
  ["Right stick", "RIGHT_X", "RIGHT_Y"],
];
const ROWS: { label: string; buttons: readonly string[] }[] = [
  { label: "Shoulders", buttons: ["L1", "L2", "R1", "R2"] },
  { label: "Arrows", buttons: ["UP", "DOWN", "LEFT", "RIGHT"] },
  { label: "Buttons", buttons: ["X", "A", "B", "Y"] },
];
const SHOWN: Record<string, string> = { UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→" };

/** The V5 controller as the robot reads it, which you can also press and push with the
 * pointer (a stick springs back when you let go). */
export function ControllerPad(props: {
  state: ControllerState;
  onScreen: ControllerInput;
  onInput: (input: ControllerInput) => void;
  enabled: boolean;
}) {
  const { state, onScreen, onInput, enabled } = props;
  const pressed = new Set(state.digital);

  const press = (button: string, down: boolean) => {
    const buttons = new Set(onScreen.digital);
    if (down) buttons.add(button);
    else buttons.delete(button);
    onInput({ ...onScreen, digital: BUTTONS.filter((b) => buttons.has(b)) });
  };
  const push = (event: ReactPointerEvent<HTMLDivElement>, x: Channel, y: Channel) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const clamp = (v: number) => Math.round(Math.max(-1, Math.min(1, v)) * 127);
    const u = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    const v = 1 - ((event.clientY - rect.top) / rect.height) * 2;
    onInput({ ...onScreen, analog: { ...onScreen.analog, [x]: clamp(u), [y]: clamp(v) } });
  };
  const center = (x: Channel, y: Channel) => onInput({ ...onScreen, analog: { ...onScreen.analog, [x]: 0, [y]: 0 } });

  return (
    <div className={`pad${enabled ? "" : " off"}`} data-testid="controller">
      <div className="sticks">
        {STICKS.map(([label, x, y]) => {
          const ax = state.analog[x] ?? 0;
          const ay = state.analog[y] ?? 0;
          return (
            <div
              key={label}
              className="stick"
              role="slider"
              aria-label={`${label}: ${ax}, ${ay}`}
              aria-valuenow={ay}
              title={`${label}: ${x} ${ax}, ${y} ${ay}`}
              onPointerDown={(event) => {
                if (!enabled) return;
                event.currentTarget.setPointerCapture(event.pointerId);
                push(event, x, y);
              }}
              onPointerMove={(event) => {
                if (enabled && event.currentTarget.hasPointerCapture(event.pointerId)) push(event, x, y);
              }}
              onPointerUp={() => center(x, y)}
              onPointerCancel={() => center(x, y)}
            >
              <i style={{ left: `${50 + (ax / 127) * 42}%`, top: `${50 - (ay / 127) * 42}%` }} />
            </div>
          );
        })}
      </div>
      {ROWS.map((row) => (
        <div key={row.label} className="buttons" role="group" aria-label={row.label}>
          {row.buttons.map((button) => (
            <button
              key={button}
              type="button"
              className={pressed.has(button) ? "down" : undefined}
              aria-pressed={pressed.has(button)}
              aria-label={button}
              disabled={!enabled}
              onPointerDown={(event) => {
                event.currentTarget.setPointerCapture(event.pointerId);
                press(button, true);
              }}
              onPointerUp={() => press(button, false)}
              onPointerCancel={() => press(button, false)}
            >
              {SHOWN[button] ?? button}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

