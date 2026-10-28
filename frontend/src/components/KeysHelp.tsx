import { useEffect, useRef } from "react";

const GROUPS: { title: string; keys: [string, string][] }[] = [
  {
    title: "The run",
    keys: [
      ["Space", "pause or resume"],
      [".", "one 10 ms step while paused"],
      ["R", "restart from the start, same seed"],
      ["+ / −", "faster / slower (0.1× to 8×, then max)"],
      ["1 2 3 4 5", "show or hide the paths, the estimate, the beams, the wheel forces, what the robot code draws"],
      ["?", "this list"],
    ],
  },
  {
    title: "A recorded run (once it ends, or opened from Runs)",
    keys: [
      ["Space", "play or pause"],
      ["← / →", "half a second back / on (Shift: 5 s)"],
      [", / .", "one 50 ms frame back / on"],
      ["Home / End", "its start / end"],
      ["Click a plot", "that moment"],
    ],
  },
  {
    title: "Driving (while a run is live)",
    keys: [
      ["W / S", "left stick up / down (arcade throttle)"],
      ["A / D", "right stick left / right (arcade turn)"],
      ["↑ / ↓", "right stick up / down (tank)"],
      ["← / →", "left stick left / right (strafe)"],
      ["Shift", "half stick, for fine moves"],
      ["Q / Z, E / C", "L1 / L2, R1 / R2"],
      ["I L K J", "X A B Y"],
      ["T F G H", "the arrows: up, left, down, right"],
    ],
  },
  {
    title: "A gamepad",
    keys: [
      ["Sticks", "the V5's sticks"],
      ["Face buttons", "by position: top is X, right A, bottom B, left Y"],
      ["Bumpers, triggers", "L1 / R1, L2 / R2"],
      ["D-pad", "the arrows"],
    ],
  },
  {
    title: "Robot and field editors",
    keys: [
      ["Drag a part", "move it (to 1/8 in on a robot, 1/2 in on a field)"],
      ["Drag its handle", "turn it, to 15°"],
      ["Shift while dragging", "finer: 0.01 in (0.1 in), 1°"],
      ["Arrows, [ ]", "move, turn the selected part"],
      ["Ctrl+C / Ctrl+V", "copy the selected wheel, sensor or part of a robot's shape / paste a copy, into this robot or another"],
      ["Ctrl+Z / Ctrl+Shift+Z", "undo / redo, in the text or the diagram"],
      ["Ctrl+S", "save"],
    ],
  },
  {
    title: "The field",
    keys: [
      ["Drag the robot", "where it starts (before a run), to half inches"],
      ["Drag its handle", "which way it faces, to 15°"],
      ["Shift while dragging", "finer: 0.1 in, 1°"],
      ["Wheel / drag", "zoom / pan"],
      ["Double-click", "the whole field"],
    ],
  },
];

/** Every key, as a dialog. */
export function KeysHelp(props: { onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => close.current?.focus(), []);
  return (
    <div className="overlay" role="presentation" onClick={props.onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="keys-title" onClick={(e) => e.stopPropagation()} data-testid="keys-help">
        <header>
          <h2 id="keys-title">Keys</h2>
          <button ref={close} type="button" className="ghost small" onClick={props.onClose}>
            Close
          </button>
        </header>
        <div className="keygroups">
          {GROUPS.map((group) => (
            <section key={group.title}>
              <h3>{group.title}</h3>
              <dl>
                {group.keys.map(([key, what]) => [
                  <dt key={`k${key}`}>
                    <kbd>{key}</kbd>
                  </dt>,
                  <dd key={`w${key}`}>{what}</dd>,
                ])}
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
