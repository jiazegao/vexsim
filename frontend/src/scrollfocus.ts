// A box that scrolls can be scrolled from the keyboard (phase 15.5): Tab stops at it while
// what's in it doesn't fit, and the arrow keys scroll it. A box that fits, or one with a link
// or a button in it (Tab reaches those, and the box scrolls to them), takes no stop of its own.

import type { RefObject } from "react";
import { useEffect, useRef } from "react";

let observer: ResizeObserver | null = null;

/** Whether the box is one Tab should stop at: it scrolls, and nothing in it takes the keyboard. */
export function needsStop(scrolls: boolean, hasControls: boolean): boolean {
  return scrolls && !hasControls;
}

function fit(box: HTMLElement): void {
  const scrolls = box.scrollWidth > box.clientWidth + 1 || box.scrollHeight > box.clientHeight + 1;
  const stop = needsStop(scrolls, scrolls && box.querySelector('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])') !== null);
  if (stop === box.hasAttribute("tabindex")) return; // as it is: nothing written
  if (stop) box.tabIndex = 0;
  else box.removeAttribute("tabindex");
}

/** A ref for a box that may scroll: it's given a Tab stop while it does. */
export function useScrollFocus<T extends HTMLElement>(): RefObject<T | null> {
  const ref = useRef<T | null>(null);
  // what's in it may have changed with any render of the component that draws it
  useEffect(() => {
    if (ref.current) fit(ref.current);
  });
  // and its own size, with the window's
  useEffect(() => {
    const box = ref.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    observer ??= new ResizeObserver((entries) => {
      for (const entry of entries) fit(entry.target as HTMLElement);
    });
    observer.observe(box);
    return () => observer?.unobserve(box);
  }, []);
  return ref;
}
