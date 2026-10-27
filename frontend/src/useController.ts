// Driving the run's robot: the keyboard, a gamepad and the on-screen controller, sent to
// the run whenever what they say changes.

import { useEffect, useRef, useState } from "react";
import type { ControllerInput } from "./controller";
import { combine, firstGamepad, fromGamepad, fromKeys, isDrivingKey, NEUTRAL, sameInput } from "./controller";
import type { SessionStore } from "./session";

function typing(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return !!element && (element.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(element.tagName));
}

/** While `enabled`, the robot of `store`'s run reads the keyboard (unless you're typing
 * in a form), the first gamepad, and `onScreen`. Returns the gamepad's name, if any. */
export function useController(store: SessionStore | null, enabled: boolean, onScreen: ControllerInput): string | null {
  const held = useRef(new Set<string>());
  const sent = useRef<ControllerInput>(NEUTRAL);
  const live = useRef({ store, enabled, onScreen });
  live.current = { store, enabled, onScreen };
  const [gamepad, setGamepad] = useState<string | null>(null);

  useEffect(() => {
    sent.current = NEUTRAL; // a new run's controller starts at rest
  }, [store]);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (!isDrivingKey(event.code) || event.ctrlKey || event.metaKey || event.altKey) return;
      if (typing(event.target)) return;
      // Held keys count from when they go down (a key held as the run starts drives it),
      // but only a live run's keys are the robot's alone.
      held.current.add(event.code);
      if (live.current.enabled) event.preventDefault(); // the arrows mustn't scroll the page
    };
    const up = (event: KeyboardEvent) => {
      held.current.delete(event.code);
    };
    const release = () => held.current.clear();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", release);
    document.addEventListener("visibilitychange", release);

    let frame = 0;
    let padName: string | null = null;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const pad = firstGamepad();
      const name = pad ? pad.id : null;
      if (name !== padName) {
        padName = name;
        setGamepad(name);
      }
      const { store, enabled, onScreen } = live.current;
      const input = enabled ? combine(fromKeys(held.current), fromGamepad(pad), onScreen) : NEUTRAL;
      if (store && !sameInput(input, sent.current)) {
        store.send({ cmd: "input", analog: input.analog, digital: input.digital });
        sent.current = input;
      }
    };
    tick();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", release);
      document.removeEventListener("visibilitychange", release);
    };
  }, []);
  return gamepad;
}
