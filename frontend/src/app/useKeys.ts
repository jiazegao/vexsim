// The app's keys (App.tsx), as in the pygame viewer: Space pause, . step, R restart, +/- speed;
// 1-5 what the field shows; ? the list of keys. Driving keys are useController's. A recorded
// run: Space play, arrows (Shift: farther), Home/End and , . move through it.

import type { Dispatch, SetStateAction } from "react";
import { useEffect } from "react";
import { SPEEDS } from "../components/Controls";
import type { Layers } from "../draw";
import type { Playhead } from "../playhead";
import type { SessionState } from "../protocol";
import type { SessionStore } from "../session";
import { isLive } from "../session";
import { SEEK_S } from "./shared";

export function useKeys(deps: {
  help: boolean; // the list of keys is open
  setHelp: Dispatch<SetStateAction<boolean>>;
  narrow: boolean;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  page: string;
  speed: number;
  changeSpeed: (value: number) => void;
  store: SessionStore | null;
  state: SessionState | null;
  scrubbing: boolean; // a recorded run (or a log alone) is on the timeline
  driving: boolean;
  playhead: Playhead;
  restart: () => Promise<void>;
  setLayers: Dispatch<SetStateAction<Layers>>;
}): void {
  const { help, setHelp, narrow, sidebarOpen, setSidebarOpen, page, speed, changeSpeed, store, state, scrubbing, driving, playhead, restart, setLayers } = deps;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      const typing = target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(tag);
      const pressingButton = tag === "BUTTON" && (event.key === " " || event.key === "Enter");
      if (event.key === "Escape" && help) setHelp(false);
      else if (event.key === "Escape" && narrow && sidebarOpen) setSidebarOpen(false); // the list, over the page
      // (a key already taken: an arrow that moved through a row of tabs or the list, roving.ts)
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || typing || pressingButton) return;
      if (page !== "simulate" && event.key !== "?") return; // an editor's diagram has its own keys
      const index = SPEEDS.indexOf(speed);
      const toggle = (key: keyof Layers) => setLayers((l) => ({ ...l, [key]: !l[key] }));
      const seekBy = (seconds: number) => {
        event.preventDefault();
        playhead.seek(playhead.t + seconds);
      };
      switch (event.key) {
        case " ":
          if (store && state && isLive(state)) {
            event.preventDefault();
            store.send({ cmd: state === "paused" ? "resume" : "pause" });
          } else if (scrubbing) {
            event.preventDefault();
            playhead.toggle();
          }
          break;
        case ".":
          if (state === "paused") store?.send({ cmd: "step", ms: 10 });
          else if (scrubbing) seekBy(0.05);
          break;
        case ",":
          if (scrubbing) seekBy(-0.05);
          break;
        case "ArrowLeft":
        case "ArrowRight":
          if (scrubbing && !driving) seekBy((event.key === "ArrowLeft" ? -1 : 1) * SEEK_S * (event.shiftKey ? 10 : 1));
          break;
        case "Home":
          if (scrubbing) seekBy(-Infinity);
          break;
        case "End":
          if (scrubbing) seekBy(Infinity);
          break;
        case "r":
        case "R":
          void restart();
          break;
        case "+":
        case "=":
          if (index >= 0 && index < SPEEDS.length - 1) changeSpeed(SPEEDS[index + 1]);
          break;
        case "-":
        case "_":
          if (index > 0) changeSpeed(SPEEDS[index - 1]);
          break;
        case "1":
          toggle("trails");
          break;
        case "2":
          toggle("estimate");
          break;
        case "3":
          toggle("beams");
          break;
        case "4":
          toggle("forces");
          break;
        case "5":
          toggle("drawings");
          break;
        case "?":
          setHelp((open) => !open);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [changeSpeed, driving, help, narrow, page, playhead, restart, scrubbing, setSidebarOpen, sidebarOpen, speed, state, store, setHelp, setLayers]);
}
