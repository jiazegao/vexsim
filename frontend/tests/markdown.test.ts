import { describe, expect, it } from "vitest";
import { resolveLink, resolvePicture } from "../src/guide";
import type { Block, Inline } from "../src/markdown";
import { headings, inlinesOf, parse, plain, slug } from "../src/markdown";
import type { GuideDocument } from "../src/protocol";

const text = (value: string): Inline => ({ kind: "text", text: value });

describe("a line's marks", () => {
  it("reads code, bold, italics and their mixes", () => {
    expect(inlinesOf("Run `vexsim ui`, then **Run** or *Restart*.")).toEqual([
      text("Run "),
      { kind: "code", text: "vexsim ui" },
      text(", then "),
      { kind: "strong", children: [text("Run")] },
      text(" or "),
      { kind: "em", children: [text("Restart")] },
      text("."),
    ]);
    expect(inlinesOf("**The text:** a *YAML* editor")).toEqual([
      { kind: "strong", children: [text("The text:")] },
      text(" a "),
      { kind: "em", children: [text("YAML")] },
      text(" editor"),
    ]);
    expect(inlinesOf("**bold with *italics* in it**")).toEqual([
      { kind: "strong", children: [text("bold with "), { kind: "em", children: [text("italics")] }, text(" in it")] },
    ]);
  });

  it("leaves marks that aren't marks alone", () => {
    expect(plain(inlinesOf("est_x_in and m<p>_cmd_mv, 3 * 4 * 5, a_b"))).toBe("est_x_in and m<p>_cmd_mv, 3 * 4 * 5, a_b");
    expect(inlinesOf("snake_case_name")).toEqual([text("snake_case_name")]);
    expect(inlinesOf("an unclosed `tick and a lone * star")).toEqual([text("an unclosed `tick and a lone * star")]);
    expect(inlinesOf("escaped \\*stars\\* and a \\| bar")).toEqual([text("escaped *stars* and a | bar")]);
    expect(inlinesOf("`**not bold**` and ``a ` tick``")).toEqual([{ kind: "code", text: "**not bold**" }, text(" and "), { kind: "code", text: "a ` tick" }]);
    expect(inlinesOf("<script>alert(1)</script>")).toEqual([text("<script>alert(1)</script>")]); // text, never HTML
  });

  it("reads links: inline, by reference, bare and in angle brackets; and pictures", () => {
    expect(inlinesOf("see [section 9](#autonomous-routes) and [cpp.md](docs/cpp.md#the-build \"how\")")).toEqual([
      text("see "),
      { kind: "link", href: "#autonomous-routes", children: [text("section 9")] },
      text(" and "),
      { kind: "link", href: "docs/cpp.md#the-build", children: [text("cpp.md")] },
    ]);
    const references = new Map([["fit", "https://example.org/fit"]]);
    expect(inlinesOf("measured [here][fit], and [fit] again; [not one]", references)).toEqual([
      text("measured "),
      { kind: "link", href: "https://example.org/fit", children: [text("here")] },
      text(", and "),
      { kind: "link", href: "https://example.org/fit", children: [text("fit")] },
      text(" again; [not one]"),
    ]);
    expect(inlinesOf("install it from https://www.msys2.org (default folder). Or <https://brew.sh>.")).toEqual([
      text("install it from "),
      { kind: "link", href: "https://www.msys2.org", children: [text("https://www.msys2.org")] },
      text(" (default folder). Or "),
      { kind: "link", href: "https://brew.sh", children: [text("https://brew.sh")] },
      text("."),
    ]);
    expect(inlinesOf("![The app after a run](docs/img/ui_1239e.png)")).toEqual([{ kind: "image", src: "docs/img/ui_1239e.png", alt: "The app after a run" }]);
    expect(inlinesOf("[`code` in a link](a_(b).md)")).toEqual([{ kind: "link", href: "a_(b).md", children: [{ kind: "code", text: "code" }, text(" in a link")] }]);
  });

  it("joins a paragraph's lines, and breaks where two spaces say so", () => {
    expect(inlinesOf("one\ntwo  \nthree")).toEqual([text("one two"), { kind: "break" }, text("three")]);
  });
});

describe("a document's blocks", () => {
  it("reads headings with GitHub's ids", () => {
    const blocks = parse("# vexsim\n\n## 7. The browser app: `vexsim ui`\n\ntext\n\n### A robot that isn't a rectangle: `shape`\n\n## Setup\n\n## Setup\n");
    expect(headings(blocks).map((h) => [h.level, h.id, h.text])).toEqual([
      [1, "vexsim", "vexsim"],
      [2, "7-the-browser-app-vexsim-ui", "7. The browser app: vexsim ui"],
      [3, "a-robot-that-isnt-a-rectangle-shape", "A robot that isn't a rectangle: shape"],
      [2, "setup", "Setup"],
      [2, "setup-1", "Setup"], // the same heading again
    ]);
    expect(slug("3.1 Weigh it")).toBe("31-weigh-it");
    expect(slug("Drawing on the field (`bot.draw`)")).toBe("drawing-on-the-field-botdraw");
  });

  it("reads fenced code as it is, whatever is in it", () => {
    const blocks = parse("```python\ndef autonomous(bot):\n    yield  # **not bold**\n\n| not | a table |\n```\nafter\n");
    expect(blocks).toEqual([
      { kind: "code", language: "python", text: "def autonomous(bot):\n    yield  # **not bold**\n\n| not | a table |" },
      { kind: "paragraph", children: [text("after")] },
    ]);
  });

  it("reads lists: nested, numbered, with boxes, and with more than a line to an item", () => {
    const blocks = parse(
      ["- one", "- two", "  - under two", "  - also", "- three", "", "1. first", "2. second", "", "   ```", "   code in second", "   ```", "3. third", "", "- [ ] to do", "- [x] done"].join("\n"),
    );
    expect(blocks.map((b) => b.kind)).toEqual(["list", "list", "list"]);
    const [bullets, numbers, boxes] = blocks as Extract<Block, { kind: "list" }>[];
    expect([bullets.ordered, bullets.tight, bullets.items.length]).toEqual([false, true, 3]);
    expect(bullets.items[1].blocks.map((b) => b.kind)).toEqual(["paragraph", "list"]);
    expect((bullets.items[1].blocks[1] as Extract<Block, { kind: "list" }>).items.length).toBe(2);
    expect([numbers.ordered, numbers.start, numbers.items.length]).toEqual([true, 1, 3]);
    expect(numbers.items[1].blocks).toEqual([
      { kind: "paragraph", children: [text("second")] },
      { kind: "code", language: "", text: "code in second" },
    ]);
    expect(boxes.items.map((item) => item.checked)).toEqual([false, true]);
    expect(plain((boxes.items[1].blocks[0] as Extract<Block, { kind: "paragraph" }>).children)).toBe("done");
  });

  it("ends a list at text that isn't under it", () => {
    const blocks = parse("- an item\n\nA paragraph of its own.\n\n8. eight\n9. nine\n");
    expect(blocks.map((b) => b.kind)).toEqual(["list", "paragraph", "list"]);
    expect((blocks[2] as Extract<Block, { kind: "list" }>).start).toBe(8);
  });

  it("reads tables: their alignment, bars in code and escaped bars", () => {
    const blocks = parse("| Key | Action |\n|---|:-:|\n| `a | b` | either \\| or |\n| short |\n\ntext\n");
    expect(blocks[0]).toEqual({
      kind: "table",
      align: [null, "center"],
      head: [[text("Key")], [text("Action")]],
      rows: [
        [[{ kind: "code", text: "a | b" }], [text("either | or")]],
        [[text("short")], []],
      ],
    });
    expect(blocks[1]).toEqual({ kind: "paragraph", children: [text("text")] });
  });

  it("reads quotes, rules and links' addresses kept apart", () => {
    const blocks = parse("> a note\n> on two lines\n\n---\n\nThe motor's [curve][fit].\n\n[fit]: https://example.org/fit\n");
    expect(blocks).toEqual([
      { kind: "quote", blocks: [{ kind: "paragraph", children: [text("a note on two lines")] }] },
      { kind: "rule" },
      { kind: "paragraph", children: [text("The motor's "), { kind: "link", href: "https://example.org/fit", children: [text("curve")] }, text(".")] },
    ]);
  });
});

describe("where a document's links go", () => {
  const documents: GuideDocument[] = [
    { id: "readme", path: "README.md", title: "vexsim", about: "" },
    { id: "cpp", path: "docs/cpp.md", title: "C++", about: "" },
    { id: "calibration", path: "docs/calibration.md", title: "Calibration", about: "" },
  ];
  const repository = "https://example.org/vexsim";
  const go = (from: string, href: string) => resolveLink(from, href, documents, repository);

  it("finds headings, other documents, and what isn't a document", () => {
    expect(go("README.md", "#autonomous-routes")).toEqual({ kind: "here", at: "autonomous-routes" });
    expect(go("README.md", "docs/cpp.md")).toEqual({ kind: "doc", doc: "cpp", at: null });
    expect(go("README.md", "docs/cpp.md#the-build")).toEqual({ kind: "doc", doc: "cpp", at: "the-build" });
    expect(go("docs/cpp.md", "calibration.md#logs")).toEqual({ kind: "doc", doc: "calibration", at: "logs" });
    expect(go("docs/cpp.md", "../README.md#9-pros-projects")).toEqual({ kind: "doc", doc: "readme", at: "9-pros-projects" });
    expect(go("docs/cpp.md", "cpp.md#the-build")).toEqual({ kind: "here", at: "the-build" });
    expect(go("docs/cpp.md", "../examples/pros_projects/minimal_pros4/src/main.cpp")).toEqual({
      kind: "web",
      url: "https://example.org/vexsim/blob/main/examples/pros_projects/minimal_pros4/src/main.cpp",
    });
    expect(go("README.md", "PLAN.md#17-faster")).toEqual({ kind: "web", url: "https://example.org/vexsim/blob/main/PLAN.md#17-faster" });
    expect(go("README.md", "https://www.msys2.org")).toEqual({ kind: "web", url: "https://www.msys2.org" });
  });

  it("finds a document's pictures from where the document is", () => {
    expect(resolvePicture("README.md", "docs/img/ui_1239e.png")).toBe("docs/img/ui_1239e.png");
    expect(resolvePicture("docs/calibration_guide.md", "img/ui_design.png")).toBe("docs/img/ui_design.png");
    expect(resolvePicture("README.md", "https://example.org/a.png")).toBeNull();
  });
});
