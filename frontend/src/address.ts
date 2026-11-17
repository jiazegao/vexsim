// Where you are in the app, kept in the page's address (phase 15.3): the page, the Calibrate
// page's tab and session, the config or route open in an editor, and the recorded run on show.
// So a reload comes back to the same place, and Back and Forward move between pages. It's the
// part after the # (the server never sees it):
//
//   #/simulate?run=20261117-154527-ab12
//   #/calibrate/check?session=calibration/2026-11-07
//   #/edit?file=examples/robots/1239e_2026-27.yaml
//   #/guide/calibration_guide?at=5-the-session
//
// The Simulate page with nothing on show has no # at all.

export const PAGE_NAMES = ["simulate", "sweeps", "bench", "calibrate", "analyze", "build", "guide"] as const;
export type PageName = (typeof PAGE_NAMES)[number];
export const CALIBRATE_TABS = ["session", "check", "quick"] as const;
export type CalibrateTabName = (typeof CALIBRATE_TABS)[number];

export interface Place {
  page: PageName | "edit";
  tab?: CalibrateTabName; // calibrate: its tab
  session?: string; // calibrate: the session's folder
  file?: string; // edit: the config's or the route's path
  run?: string; // simulate: the recorded run on show
  doc?: string; // guide: the document (none: the first)
  at?: string; // guide: the heading of it
}

export const HOME: Place = { page: "simulate" };

/** A value in the address: as it reads (its slashes stay), anything else that needs it escaped. */
function escaped(value: string): string {
  return encodeURIComponent(value).replace(/%2F/gi, "/");
}

/** The address's # part for a place ("" for the Simulate page with nothing on show). */
export function formatPlace(place: Place): string {
  if (place.page === "edit") return place.file ? `#/edit?file=${escaped(place.file)}` : "";
  if (place.page === "calibrate") {
    const tab = place.tab ?? "session";
    return `#/calibrate/${tab}${place.session ? `?session=${escaped(place.session)}` : ""}`;
  }
  if (place.page === "simulate") return place.run ? `#/simulate?run=${escaped(place.run)}` : "";
  if (place.page === "guide") return `#/guide${place.doc ? `/${escaped(place.doc)}` : ""}${place.at ? `?at=${escaped(place.at)}` : ""}`;
  return `#/${place.page}`;
}

/** The place an address's # part names; null if it names none (an old link, a typo). */
export function parsePlace(hash: string): Place | null {
  const text = hash.replace(/^#/, "").replace(/^\//, "");
  if (text === "") return HOME;
  const at = text.indexOf("?");
  const [name, tab] = (at < 0 ? text : text.slice(0, at)).split("/");
  let query: URLSearchParams;
  try {
    query = new URLSearchParams(at < 0 ? "" : text.slice(at + 1));
  } catch {
    return null;
  }
  if (name === "edit") {
    const file = query.get("file");
    return file ? { page: "edit", file } : null;
  }
  if (!(PAGE_NAMES as readonly string[]).includes(name)) return null;
  const page = name as PageName;
  if (page === "calibrate") {
    const session = query.get("session");
    const known = (CALIBRATE_TABS as readonly string[]).includes(tab ?? "") ? (tab as CalibrateTabName) : "session";
    return session ? { page, tab: known, session } : { page, tab: known };
  }
  if (page === "simulate") {
    const run = query.get("run");
    return run ? { page, run } : HOME;
  }
  if (page === "guide") {
    const at = query.get("at");
    let doc = "";
    try {
      doc = decodeURIComponent(tab ?? "");
    } catch {
      return null; // an escape that isn't one
    }
    return { page, ...(doc ? { doc } : {}), ...(at ? { at } : {}) };
  }
  return { page };
}

/** Whether going from one place to another is a step Back should undo: another page, another
 * file in the editor, another tab of Calibrate, another document or heading of the guide. A
 * different run or session on the same page isn't: the address just follows it. */
export function isStep(from: Place, to: Place): boolean {
  if (from.page !== to.page || from.file !== to.file) return true;
  if (to.page === "calibrate") return (from.tab ?? "session") !== (to.tab ?? "session");
  if (to.page === "guide") return from.doc !== to.doc || from.at !== to.at;
  return false;
}
