// Where a link in one of vexsim's documents goes, for the Guide page (phase 15.4): a heading of
// the same document, another of the documents (shown in the app), or somewhere else: a site, or
// a file of the repository that isn't a document (an example, a source file).

import type { GuideDocument } from "./protocol";

export type Target =
  | { kind: "here"; at: string } // a heading of this document
  | { kind: "doc"; doc: string; at: string | null } // another document, and a heading of it
  | { kind: "web"; url: string }; // a site, or a file's page in the repository

const BASE = "http://guide.invalid/";

/** What a link in the document at `from` (README.md, docs/cpp.md) names, read as a browser
 * reads a relative link: a path from the repository's top and a #part; null if it leaves it. */
export function pathOf(from: string, href: string): { path: string; hash: string } | null {
  let url: URL;
  try {
    url = new URL(href, BASE + from);
  } catch {
    return null;
  }
  if (!url.href.startsWith(BASE)) return null;
  try {
    return { path: decodeURIComponent(url.pathname.slice(1)), hash: decodeURIComponent(url.hash.slice(1)) };
  } catch {
    return null; // an escape that isn't one
  }
}

/** Where a link in the document at `from` goes. */
export function resolveLink(from: string, href: string, documents: GuideDocument[], repository: string): Target {
  if (href.startsWith("#")) return { kind: "here", at: decoded(href.slice(1)) };
  const named = pathOf(from, href);
  if (!named) return { kind: "web", url: href };
  const { path, hash } = named;
  if (path === from) return { kind: "here", at: hash };
  const document = documents.find((d) => d.path === path);
  if (document) return { kind: "doc", doc: document.id, at: hash || null };
  return { kind: "web", url: `${repository}/blob/main/${path}${hash ? `#${hash}` : ""}` };
}

/** The picture a document at `from` shows, as a path from the repository's top; null for one
 * that's somewhere else (its address is used as it is). */
export function resolvePicture(from: string, src: string): string | null {
  return pathOf(from, src)?.path ?? null;
}

function decoded(text: string): string {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}
