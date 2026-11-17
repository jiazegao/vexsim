// How the app's shell fits its window (phase 15.2). The Simulate page is built around the
// field, so on a laptop's short window the run bar folds to a line and the bottom panel to its
// tabs, and in a narrow one (beside an editor, or inside VS Code) the workspace list and the
// readout open over the page instead of beside it. Each panel can be opened or closed by
// hand; that choice is kept, for windows of that kind only.

import { useCallback, useEffect, useState } from "react";

/** A short window: a 1366 x 768 laptop's, with or without the browser's own bars. */
export const SHORT = "(max-height: 800px)";
/** A narrow window: half a screen, or a panel in an editor. */
export const NARROW = "(max-width: 1100px)";

export type Panel = "sidebar" | "readout" | "bottom" | "key";

const KEY = "vexsim.panel.";

/** Whether the window matches a media query, now and as it's resized. */
export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => (typeof matchMedia === "function" ? matchMedia(query).matches : false));
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const media = matchMedia(query);
    const changed = () => setMatches(media.matches);
    changed();
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, [query]);
  return matches;
}

/** Where a panel's choice is kept: one for small windows, one for large. */
export function panelKey(panel: Panel, small: boolean): string {
  return `${KEY}${panel}.${small ? "small" : "large"}`;
}

/** A panel's kept choice, if it has one. */
export function readPanel(panel: Panel, small: boolean): boolean | null {
  try {
    const kept = localStorage.getItem(panelKey(panel, small));
    return kept === "open" ? true : kept === "closed" ? false : null;
  } catch {
    return null; // no storage (private windows): nothing is kept
  }
}

export function keepPanel(panel: Panel, small: boolean, open: boolean): void {
  try {
    localStorage.setItem(panelKey(panel, small), open ? "open" : "closed");
  } catch {
    // nothing is kept
  }
}

/** Whether a panel is open: as chosen by hand for windows of this kind, else `fallback`
 * (open in a large window, closed in a small one, usually). */
export function usePanel(panel: Panel, small: boolean, fallback = !small): [boolean, (open: boolean) => void] {
  const [chosen, setChosen] = useState<boolean | null>(() => readPanel(panel, small));
  useEffect(() => setChosen(readPanel(panel, small)), [panel, small]); // the window changed kind
  const set = useCallback(
    (open: boolean) => {
      keepPanel(panel, small, open);
      setChosen(open);
    },
    [panel, small],
  );
  return [chosen ?? fallback, set];
}
