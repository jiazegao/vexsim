// vexsim's own documents (the README, docs/*.md), read by the Guide page's Markdown reader:
// each one whole, with every link of theirs going somewhere. Runs in Node (it reads the files),
// so it's checked with the Node files (tsconfig.node.json), not the page's.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { resolveLink, resolvePicture } from "../src/guide";
import type { Block, Inline } from "../src/markdown";
import { headings, parse } from "../src/markdown";
import { GUIDE, SESSION_STEPS } from "../src/pages/calibrate/steps";
import type { GuideDocument } from "../src/protocol";

describe("vexsim's own documents", () => {
  const root = resolve(import.meta.dirname, "../..");
  const paths = ["README.md", ...readdirSync(resolve(root, "docs")).filter((name) => name.endsWith(".md")).map((name) => `docs/${name}`)];
  const documents: GuideDocument[] = paths.map((path) => ({ id: path, path, title: path, about: "" }));
  const parsed = new Map(paths.map((path) => [path, parse(readFileSync(resolve(root, path), "utf-8"))]));

  /** Every inline of the blocks, whatever it's inside. */
  function inlines(blocks: Block[]): Inline[] {
    const within = (list: Inline[]): Inline[] => list.flatMap((inline) => ("children" in inline ? [inline, ...within(inline.children)] : [inline]));
    return blocks.flatMap((block): Inline[] => {
      if (block.kind === "heading" || block.kind === "paragraph") return within(block.children);
      if (block.kind === "quote") return inlines(block.blocks);
      if (block.kind === "list") return block.items.flatMap((item) => inlines(item.blocks));
      if (block.kind === "table") return [...block.head, ...block.rows.flat()].flatMap(within);
      return [];
    });
  }

  it.each(paths)("%s reads with nothing of its marks left over", (path) => {
    const blocks = parsed.get(path)!;
    expect(blocks.length).toBeGreaterThan(10);
    expect(blocks[0]).toMatchObject({ kind: "heading", level: 1 });
    for (const inline of inlines(blocks)) {
      if (inline.kind !== "text") continue;
      expect(inline.text).not.toMatch(/\*\*|\]\(|```|^#{1,6} |\[[ x]\] /); // bold, a link, a fence, a heading, a box
    }
    for (const heading of headings(blocks)) expect(heading.id).not.toBe("");
  });

  it.each(paths)("%s: every link finds its heading, document or picture", (path) => {
    const ids = new Map([...parsed].map(([p, blocks]) => [p, new Set(headings(blocks).map((h) => h.id))]));
    const problems: string[] = [];
    for (const inline of inlines(parsed.get(path)!)) {
      if (inline.kind === "image") {
        const file = resolvePicture(path, inline.src);
        if (!file || !file.startsWith("docs/") || !existsSync(resolve(root, file))) problems.push(`picture ${inline.src}`);
      } else if (inline.kind === "link") {
        const target = resolveLink(path, inline.href, documents, "repo:");
        if (target.kind === "here" && !ids.get(path)!.has(target.at)) problems.push(`#${target.at}`);
        if (target.kind === "doc" && target.at && !ids.get(target.doc)!.has(target.at)) problems.push(`${target.doc}#${target.at}`);
        if (target.kind === "web" && target.url.startsWith("repo:")) {
          const file = target.url.slice("repo:/blob/main/".length).split("#")[0];
          if (!existsSync(resolve(root, file))) problems.push(`file ${file}`);
        }
      }
    }
    expect(problems).toEqual([]);
  });

  it("the calibration session's steps each link to a heading of the calibration guide", () => {
    const guide = parsed.get(`docs/${GUIDE}.md`)!;
    const ids = new Set(headings(guide).map((h) => h.id));
    for (const step of SESSION_STEPS) expect([step.key, ids.has(step.at)]).toEqual([step.key, true]);
  });
});
