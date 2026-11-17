// A group of controls that is one stop for Tab (phase 15.5): a tab list, a toolbar, the
// workspace's list. Tab comes to one of them and the arrow keys move among the rest; Home and
// End go to the ends. So reaching the far side of the page takes a few presses of Tab, not one
// for every control on it.
//
// Which one Tab comes to: the tab that's selected; else the one last used; else one that's
// picked (pressed, current); else the first.
//
// A group that runs across the page (tabs, a toolbar) moves with Left and Right. A list runs
// down it: Up and Down move between its rows, and Left and Right reach what's beside a row's
// own control (its menu button, its actions).
//
// The arrow keys are a group's only while the keyboard was brought to it with Tab. After a
// click on one of its controls they stay what they are everywhere else on the page: the
// robot's (they drive it) and a recorded run's (they move through it).

import type { FocusEvent, KeyboardEvent, RefObject } from "react";
import { useCallback, useRef } from "react";

export interface RovingOptions {
  /** A list, down the page: Up and Down move in it (else Left and Right do). */
  down?: boolean;
  /** A list's rows, and the controls beside a row's own: Left and Right move among the
   * controls of one row, and Tab passes the ones beside by. */
  row?: string;
  beside?: string;
}

const SELECTED = '[aria-selected="true"]';
const PICKED = '[aria-current="page"], [aria-pressed="true"], [aria-checked="true"]';
// what changes which control is the stop (not tabindex: the hook writes that itself)
const WATCHED = { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled", "hidden", "aria-selected", "aria-current", "aria-pressed", "aria-checked"] };

// whether the keyboard was last moved by Tab (not by a click)
let byTab = false;
if (typeof window !== "undefined") {
  window.addEventListener("keydown", (event) => event.key === "Tab" && (byTab = true), true);
  window.addEventListener("pointerdown", () => (byTab = false), true);
}

const enabled = (el: HTMLElement) => !(el as HTMLButtonElement).disabled;
const shown = (el: HTMLElement) => el.getClientRects().length > 0;

/** Whether a key is one a group takes: the arrows that move in it (in a list, all four),
 * Home and End. */
export function rovingKey(key: string, down = false): boolean {
  return key === "Home" || key === "End" || key === "ArrowLeft" || key === "ArrowRight" || (down && (key === "ArrowUp" || key === "ArrowDown"));
}

/** Where an arrow key (or Home, End) goes from the `at`th of `count`: it stops at the ends.
 * Null for any other key. `down`: the group is a list, so Up and Down move in it. */
export function rovingTarget(key: string, at: number, count: number, down = false): number | null {
  if (count === 0) return null;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  if (key === (down ? "ArrowDown" : "ArrowRight")) return at < 0 ? 0 : Math.min(at + 1, count - 1);
  if (key === (down ? "ArrowUp" : "ArrowLeft")) return at < 0 ? count - 1 : Math.max(at - 1, 0);
  return null;
}

/** Give the group its one stop for Tab. */
function apply(group: HTMLElement, selector: string, options: RovingOptions): void {
  const all = [...group.querySelectorAll<HTMLElement>(selector)];
  const usable = all.filter(enabled);
  const visible = usable.filter(shown);
  const pool = visible.length ? visible : usable; // a group that's hidden for now still gets one
  const stop =
    pool.find((el) => el === document.activeElement) ??
    pool.find((el) => el.matches(SELECTED)) ??
    pool.find((el) => el.dataset.rovingStop === "1") ??
    pool.find((el) => el.matches(PICKED)) ??
    pool[0];
  for (const el of all) el.tabIndex = el === stop ? 0 : -1;
  if (options.beside) for (const el of group.querySelectorAll<HTMLElement>(options.beside)) el.tabIndex = -1;
}

/** Make an element a group with one stop for Tab: its controls are its descendants that match
 * `selector`. Spread `props` onto the element; `group` is the element, to read. */
export function useRoving<T extends HTMLElement>(
  selector: string,
  options: RovingOptions = {},
): {
  group: RefObject<T | null>;
  props: { ref: (element: T | null) => void; onKeyDown: (event: KeyboardEvent) => void; onFocus: (event: FocusEvent) => void; onBlur: (event: FocusEvent) => void };
} {
  const group = useRef<T | null>(null);
  const observer = useRef<MutationObserver | null>(null);
  const { down, row, beside } = options;

  // the element comes (or goes): its controls are watched, as they come, go and are picked
  const ref = useCallback(
    (element: T | null) => {
      observer.current?.disconnect();
      observer.current = null;
      group.current = element;
      if (!element) return;
      const set = () => apply(element, selector, { beside });
      set();
      if (typeof MutationObserver === "undefined") return;
      observer.current = new MutationObserver(set);
      observer.current.observe(element, WATCHED);
    },
    [selector, beside],
  );

  /** The group's own control a control stands for: itself, or (one beside it) its row's. */
  const memberOf = (target: HTMLElement): HTMLElement | null => {
    if (target.matches(selector)) return target;
    if (!row || !beside || !target.matches(beside)) return null;
    return target.closest(row)?.querySelector<HTMLElement>(selector) ?? null;
  };

  return {
    group,
    props: {
      ref,
      onFocus: (event) => {
        const element = group.current;
        const member = element && memberOf(event.target as HTMLElement);
        if (!element || !member) return;
        for (const el of element.querySelectorAll<HTMLElement>("[data-roving-stop]")) delete el.dataset.rovingStop;
        member.dataset.rovingStop = "1"; // Tab comes back to where it left
        apply(element, selector, { beside });
      },
      onBlur: (event) => {
        const element = group.current;
        if (element && !element.contains(event.relatedTarget as Node | null)) apply(element, selector, { beside }); // left: the stop is the picked one again
      },
      onKeyDown: (event) => {
        const element = group.current;
        if (!element || !byTab || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
        const target = event.target as HTMLElement;
        const member = memberOf(target);
        if (!member || !rovingKey(event.key, down)) return; // a key typed in a field inside the group; a key that isn't the group's
        event.preventDefault(); // the group's key, whether or not there's anywhere to go: not the robot's, nor the page's to scroll with
        const usable = (el: HTMLElement) => enabled(el) && shown(el);
        if (down && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
          // along the row: its own control, and what's beside it
          const line = row && beside ? [...(target.closest(row)?.querySelectorAll<HTMLElement>(`${selector}, ${beside}`) ?? [])].filter(usable) : [];
          if (line.includes(target)) line[line.indexOf(target) + (event.key === "ArrowRight" ? 1 : -1)]?.focus();
          return;
        }
        const all = [...element.querySelectorAll<HTMLElement>(selector)].filter(usable);
        const next = rovingTarget(event.key, all.indexOf(member), all.length, down);
        if (next !== null) all[next].focus();
      },
    },
  };
}
