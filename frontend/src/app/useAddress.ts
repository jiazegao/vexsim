// The address keeps your place (App.tsx, address.ts): the app moved, and the address follows;
// the address moved (Back, Forward, or typed), and the app follows.

import type { Dispatch, SetStateAction } from "react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { Place } from "../address";
import { formatPlace, HOME, isStep, parsePlace } from "../address";
import type { RunConfiguration, WorkspaceInfo, WorkspaceItem } from "../protocol";
import { openRun } from "../recording";
import type { RunForm } from "../runform";
import { sameRun, specToForm } from "../runform";
import type { Calibration, PageId } from "./shared";
import { EDITED, PAGE_IDS } from "./shared";
import type { Runs } from "./useRuns";

export function useAddress(deps: {
  page: string;
  setPage: (page: string) => void;
  calibration: Calibration;
  setCalibration: Dispatch<SetStateAction<Calibration>>;
  guide: { doc: string; at: string | null };
  setGuide: (guide: { doc: string; at: string | null }) => void;
  workspace: WorkspaceInfo | null;
  configurations: RunConfiguration[];
  setForm: Dispatch<SetStateAction<RunForm>>;
  runs: Runs;
  openConfig: (path: string) => void;
  openRoute: (path: string) => void;
}) {
  const { page, setPage, calibration, setCalibration, guide, setGuide, workspace, configurations, setForm, runs, openConfig, openRoute } = deps;
  const { recording, busy, leaveSession, loadRuns, show } = runs;
  const [arrived, setArrived] = useState(false); // it's been gone to: the address follows the app from here
  const [restoring, setRestoring] = useState(false); // the run the address names is being fetched

  /** The address named what isn't there (a file since deleted, a run since pruned, a typo): put
   * where the app is in its place, without a step for Back to return to. */
  const correctAddress = () => {
    try {
      history.replaceState(history.state, "", location.pathname + location.search + formatPlace(placeRef.current));
    } catch {
      // an address that can't be written (a page inside another app's frame): it stays
    }
  };
  /** The recorded run the address names, on the field again: beside the session that made it,
   * if that's still there (`own`: its console is on screen already), else as it opens from the
   * run history, its setup in the form. Not while a run is `going`: the field is its. Whether
   * it's there to show. */
  const restoreRun = async (id: string, own: boolean, going: boolean): Promise<boolean> => {
    if (going) return true;
    setRestoring(true);
    try {
      const next = await openRun(id, own);
      const record = next.run;
      if (!own && record) {
        if (await leaveSession()) loadRuns();
        const saved = configurations.find((c) => c.name === record.name && sameRun(specToForm(record.spec), c));
        setForm(specToForm(record.spec, saved?.name ?? ""));
      }
      show(next);
      return true;
    } catch {
      correctAddress(); // gone from the history: the address says what's on show instead
      return false;
    } finally {
      setRestoring(false);
    }
  };
  /** Go where an address says (on arrival, and on Back and Forward); false if it names a file
   * that isn't there. `items`: the workspace's, if they were only just listed. */
  const go = (next: Place, items: WorkspaceItem[] | null): boolean => {
    if (next.page === "edit") {
      const item = (items ?? workspace?.items ?? []).find((i) => i.path === next.file);
      if (item?.kind === "route") openRoute(item.path);
      else if (item && EDITED.includes(item.kind)) openConfig(item.path);
      else {
        correctAddress(); // not there any more: the address says where the app is instead
        return false;
      }
      return true;
    }
    setPage(next.page);
    if (next.page === "calibrate") setCalibration((c) => ({ ...c, tab: next.tab ?? c.tab, session: next.session ?? c.session }));
    if (next.page === "guide") setGuide({ doc: next.doc ?? "", at: next.at ?? null });
    if (next.page === "simulate" && next.run && next.run !== recording?.run?.id) void restoreRun(next.run, false, busy);
    return true;
  };
  const goRef = useRef(go);
  goRef.current = go;
  const restoreRef = useRef(restoreRun);
  restoreRef.current = restoreRun;

  const shownRun = recording?.run?.id ?? null;
  const place: Place = useMemo(() => {
    if (!PAGE_IDS.includes(page)) return { page: "edit", file: page };
    if (page === "calibrate") return calibration.session ? { page, tab: calibration.tab, session: calibration.session } : { page, tab: calibration.tab };
    if (page === "simulate" && shownRun) return { page, run: shownRun };
    if (page === "guide") return { page, ...(guide.doc ? { doc: guide.doc } : {}), ...(guide.at ? { at: guide.at } : {}) };
    return { page: page as PageId };
  }, [page, calibration.tab, calibration.session, shownRun, guide]);
  const placeRef = useRef(place);
  placeRef.current = place;
  // The app moved: the address follows. From where the address is now, a new page, editor or
  // Calibrate tab is a step Back undoes; a run or a session on the same page just changes the
  // address where it is. Nothing is written when the address is there already: it moved first
  // (Back, Forward), and the app followed. (Written as the page is, not a moment after: by then
  // Back may have moved the address, and writing where the app was would undo it.)
  useLayoutEffect(() => {
    if (!arrived || restoring) return;
    const hash = formatPlace(place);
    if (hash === location.hash) return;
    const step = isStep(parsePlace(location.hash) ?? HOME, place);
    try {
      history[step ? "pushState" : "replaceState"](history.state, "", location.pathname + location.search + hash);
    } catch {
      // an address that can't be written (a page inside another app's frame): it stays
    }
  }, [arrived, restoring, place]);
  // The address moved (Back, Forward, or typed): the app follows.
  useEffect(() => {
    let last: string | null = null;
    let at = 0;
    const follow = (event: Event) => {
      // where this move went: a hashchange says so itself (the address may have moved on since)
      const hash = "newURL" in event ? new URL((event as HashChangeEvent).newURL).hash : location.hash;
      const now = performance.now();
      if (hash === last && now - at < 500) return; // popstate and hashchange, for one move
      last = hash;
      at = now;
      const next = parsePlace(hash) ?? HOME;
      if (formatPlace(next) !== formatPlace(placeRef.current)) goRef.current(next, null);
      else if (formatPlace(next) !== location.hash) correctAddress(); // it named nothing, or the same place another way
    };
    window.addEventListener("popstate", follow);
    window.addEventListener("hashchange", follow);
    return () => {
      window.removeEventListener("popstate", follow);
      window.removeEventListener("hashchange", follow);
    };
  }, []);

  return { setArrived, goRef, restoreRef };
}
