// Finding a step to add in the autonomous maker: the motions, the pauses and the team's
// functions as options, and how well what's typed matches each one.

import type { RouteFunctionInfo } from "./protocol";
import { MOTION_INFO, MOTIONS } from "./route";

export interface StepOption {
  id: string; // what it adds: a motion's or a pause's kind, or call:name
  kind: string;
  title: string;
  detail: string; // the call it makes, or the function's declaration
  group: string; // where it's from: LemLib, vexsim, a pause, or the function's header
  fn?: RouteFunctionInfo;
  header?: string; // a function in a header the route doesn't list yet: picking it lists the header too
  words: readonly string[]; // what a search looks in
}

const PAUSES = [
  ["wait", "Wait (ms)", "pros::delay(ms)"],
  ["wait_until", "Wait until the motion is this far along", "chassis.waitUntil(distance)"],
  ["wait_until_done", "Wait until the motion is done", "chassis.waitUntilDone()"],
] as const;

/** `move_to_point` as C++ names it: `moveToPoint`. */
function camel(kind: string): string {
  return kind.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
}

function fileOf(header: string): string {
  return header.split("/").at(-1) ?? header;
}

/** Every step there is to add: LemLib's motions, vexsim's, the pauses, the functions of the
 * route's headers (`listed`), then those of the project's other headers (`more`), which add
 * their header to the route when picked. */
export function stepOptions(listed: readonly RouteFunctionInfo[], more: readonly RouteFunctionInfo[] = []): StepOption[] {
  const options: StepOption[] = MOTIONS.map((kind) => {
    const info = MOTION_INFO[kind];
    const call = `${info.own ? "motions" : "chassis"}.${camel(kind)}`;
    const group = info.own ? "vexsim" : "LemLib";
    return { id: kind, kind, title: info.title, detail: call, group, words: [info.title, kind, call, group] };
  });
  for (const [kind, title, call] of PAUSES) options.push({ id: kind, kind, title, detail: call, group: "pause", words: [title, kind, call] });
  const named = new Set(listed.map((fn) => fn.name));
  const functions = [...listed.map((fn) => [fn, undefined] as const), ...more.filter((fn) => !named.has(fn.name)).map((fn) => [fn, fn.header] as const)];
  for (const [fn, header] of functions) {
    options.push({ id: `call:${fn.name}`, kind: "call", title: `${fn.name}()`, detail: fn.declaration, group: fileOf(fn.header), fn, header, words: [fn.name, fileOf(fn.header)] });
  }
  return options;
}

const squash = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, "");

/** A text's words: split at spaces, underscores, punctuation and camelCase humps. */
export function wordsOf(text: string): string[] {
  return text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

/** How well `query` matches `text`, best first: 0 it starts the text, 1 it starts one of its
 * words (or runs on over the words after), 2 it's inside it (or each word of it is), 3 its
 * letters are in the text in order, for a name (no spaces: in a sentence, most letters are);
 * null if none of these. Case and punctuation don't count: `move to point` matches
 * `move_to_point`. */
export function matchRank(query: string, text: string): number | null {
  const wanted = squash(query);
  if (!wanted) return 0;
  const target = squash(text);
  if (target.startsWith(wanted)) return 0;
  const words = wordsOf(text);
  if (words.some((_, i) => words.slice(i).join("").startsWith(wanted))) return 1;
  if (target.includes(wanted)) return 2;
  const parts = wordsOf(query);
  if (parts.length > 1 && parts.every((part) => target.includes(part))) return 2;
  if (/\s/.test(text.trim())) return null;
  let at = 0;
  for (const c of target) if (c === wanted[at]) at++;
  return at === wanted.length ? 3 : null;
}

/** The options `query` matches, best first (ties keep their order); all of them, as they are,
 * when it's empty. */
export function searchSteps(options: readonly StepOption[], query: string): StepOption[] {
  const ranked: [number, number, StepOption][] = [];
  options.forEach((option, i) => {
    const ranks = option.words.map((word) => matchRank(query, word)).filter((rank): rank is number => rank !== null);
    if (ranks.length) ranked.push([Math.min(...ranks), i, option]);
  });
  return ranked.sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, , option]) => option);
}

/** `title` cut where `query` is in it, to mark: before, the match, after (no match: all before). */
export function marked(title: string, query: string): [string, string, string] {
  const wanted = query.trim().toLowerCase();
  const at = wanted ? title.toLowerCase().indexOf(wanted) : -1;
  return at < 0 ? [title, "", ""] : [title.slice(0, at), title.slice(at, at + wanted.length), title.slice(at + wanted.length)];
}
