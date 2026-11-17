// Markdown, read into blocks for the Guide page to draw (phase 15.4): what vexsim's own
// documents use, as GitHub shows it. Headings (with GitHub's ids, so the documents' own
// #links work), paragraphs, fenced code, lists (nested, numbered, with boxes to tick), tables,
// quotes and rules; and within a line, code, bold, italics, links (inline, by reference, bare
// addresses) and pictures. Nothing in a document is ever treated as HTML: it's all text.

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "em"; children: Inline[] }
  | { kind: "link"; href: string; children: Inline[] }
  | { kind: "image"; src: string; alt: string }
  | { kind: "break" };

export type Align = "left" | "center" | "right" | null;

export interface ListItem {
  checked: boolean | null; // a box to tick, ticked or not; null: an ordinary item
  blocks: Block[];
}

export type Block =
  | { kind: "heading"; level: number; id: string; text: string; children: Inline[] }
  | { kind: "paragraph"; children: Inline[] }
  | { kind: "code"; language: string; text: string }
  | { kind: "list"; ordered: boolean; start: number; tight: boolean; items: ListItem[] }
  | { kind: "table"; align: Align[]; head: Inline[][]; rows: Inline[][][] }
  | { kind: "quote"; blocks: Block[] }
  | { kind: "rule" };

type References = Map<string, string>;

const FENCE = /^( {0,3})(`{3,}|~{3,})\s*([^`\s]*)[^`]*$/;
const HEADING = /^ {0,3}(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$/;
const RULE = /^ {0,3}([-*_])(?: *\1){2,} *$/;
const ITEM = /^( *)([-*+]|\d{1,9}[.)])( +|$)(.*)$/;
const REFERENCE = /^ {0,3}\[([^\]]+)\]:\s*<?(\S+?)>?(?:\s+["'(].*["')])?\s*$/;
const DELIMITER = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/;
const BOX = /^\[([ xX])\](?: +|$)/;
// what ends a bare address: its last character isn't one of a sentence's
const BARE = /^https?:\/\/[^\s<>]*[^\s<>.,;:!?'")\]]/;

/** A document's blocks. */
export function parse(text: string): Block[] {
  const lines = text.replace(/\r\n?/g, "\n").replace(/\t/g, "    ").split("\n");
  const references: References = new Map();
  const kept: string[] = [];
  let fence: string | null = null;
  for (const line of lines) {
    const mark = FENCE.exec(line);
    if (fence === null && mark) fence = mark[2];
    else if (fence !== null && line.trim().startsWith(fence) && /^[`~\s]*$/.test(line)) fence = null;
    else if (fence === null) {
      const reference = REFERENCE.exec(line);
      if (reference) {
        references.set(label(reference[1]), reference[2]);
        continue; // a link's address, kept for the links that name it: not text
      }
    }
    kept.push(line);
  }
  const blocks = blocksOf(kept, references);
  number(blocks, new Map());
  return blocks;
}

/** GitHub's id for a heading: its text in lower case, punctuation gone, spaces as hyphens. */
export function slug(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\p{M} _-]/gu, "")
    .replace(/ /g, "-");
}

/** A line's text without its marks, as it reads. */
export function plain(inlines: Inline[]): string {
  return inlines
    .map((inline) => {
      if (inline.kind === "text" || inline.kind === "code") return inline.text;
      if (inline.kind === "image") return inline.alt;
      if (inline.kind === "break") return " ";
      return plain(inline.children);
    })
    .join("");
}

/** Every heading in the blocks, in order (those inside lists and quotes too). */
export function headings(blocks: Block[]): Extract<Block, { kind: "heading" }>[] {
  const found: Extract<Block, { kind: "heading" }>[] = [];
  for (const block of blocks) {
    if (block.kind === "heading") found.push(block);
    else if (block.kind === "quote") found.push(...headings(block.blocks));
    else if (block.kind === "list") for (const item of block.items) found.push(...headings(item.blocks));
  }
  return found;
}

/** Give each heading its id: its slug, with -1, -2 for a slug used before, as GitHub does. */
function number(blocks: Block[], used: Map<string, number>): void {
  for (const heading of headings(blocks)) {
    const base = slug(heading.text);
    const count = used.get(base) ?? 0;
    used.set(base, count + 1);
    heading.id = count ? `${base}-${count}` : base;
  }
}

const label = (text: string) => text.trim().replace(/\s+/g, " ").toLowerCase();
const indentOf = (line: string) => line.length - line.trimStart().length;
const blank = (line: string) => line.trim() === "";

/** Whether a line starts something other than a paragraph (so ends the one before it). */
function starts(line: string, next: string | undefined): boolean {
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || /^ {0,3}>/.test(line) || ITEM.test(line) || isTable(line, next);
}

function isTable(line: string, next: string | undefined): boolean {
  return line.includes("|") && next !== undefined && DELIMITER.test(next) && next.includes("-");
}

function blocksOf(lines: string[], references: References): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (blank(line)) {
      i += 1;
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const [, indent, mark, language] = fence;
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !(lines[i].trim().startsWith(mark) && /^[`~\s]*$/.test(lines[i]))) {
        body.push(lines[i].startsWith(indent) ? lines[i].slice(indent.length) : lines[i].trimStart());
        i += 1;
      }
      i += 1; // its closing fence
      blocks.push({ kind: "code", language, text: body.join("\n") });
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      const children = inlinesOf(heading[2] ?? "", references);
      blocks.push({ kind: "heading", level: heading[1].length, id: "", text: plain(children), children });
      i += 1;
      continue;
    }
    if (RULE.test(line)) {
      blocks.push({ kind: "rule" });
      i += 1;
      continue;
    }
    if (/^ {0,3}>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^ {0,3}>/.test(lines[i])) {
        body.push(lines[i].replace(/^ {0,3}> ?/, ""));
        i += 1;
      }
      blocks.push({ kind: "quote", blocks: blocksOf(body, references) });
      continue;
    }
    if (isTable(line, lines[i + 1])) {
      const align = cells(lines[i + 1]).map((cell): Align => {
        const left = cell.startsWith(":");
        const right = cell.endsWith(":");
        return left && right ? "center" : right ? "right" : left ? "left" : null;
      });
      const row = (text: string) => {
        const found = cells(text).map((cell) => inlinesOf(cell, references));
        while (found.length < align.length) found.push([]); // a short row has empty cells
        return found.slice(0, align.length);
      };
      const head = row(line);
      const rows: Inline[][][] = [];
      i += 2;
      while (i < lines.length && !blank(lines[i]) && lines[i].includes("|")) {
        rows.push(row(lines[i]));
        i += 1;
      }
      blocks.push({ kind: "table", align, head, rows });
      continue;
    }
    const item = ITEM.exec(line);
    if (item) {
      const [list, after] = listOf(lines, i, references);
      blocks.push(list);
      i = after;
      continue;
    }
    const body: string[] = [];
    while (i < lines.length && !blank(lines[i]) && !(body.length > 0 && starts(lines[i], lines[i + 1]))) {
      body.push(lines[i].trimStart());
      i += 1;
    }
    blocks.push({ kind: "paragraph", children: inlinesOf(body.join("\n"), references) });
  }
  return blocks;
}

/** A row's cells: split at its bars (not the ones escaped, or inside code), the outer ones dropped. */
function cells(line: string): string[] {
  const found: string[] = [];
  let cell = "";
  let ticks = 0; // the length of the code span's fence we're inside, if any
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === "\\" && line[i + 1] === "|") {
      cell += "|";
      i += 1;
    } else if (char === "`") {
      let run = 1;
      while (line[i + run] === "`") run += 1;
      if (ticks === 0) ticks = run;
      else if (ticks === run) ticks = 0;
      cell += "`".repeat(run);
      i += run - 1;
    } else if (char === "|" && ticks === 0) {
      found.push(cell);
      cell = "";
    } else cell += char;
  }
  found.push(cell);
  const trimmed = found.map((text) => text.trim());
  if (trimmed[0] === "") trimmed.shift();
  if (trimmed.at(-1) === "") trimmed.pop();
  return trimmed;
}

/** The list that starts at line `at`, and the line after it. */
function listOf(lines: string[], at: number, references: References): [Block, number] {
  const first = ITEM.exec(lines[at])!;
  const base = first[1].length;
  const ordered = /\d/.test(first[2]);
  const items: ListItem[] = [];
  let loose = false;
  let i = at;
  while (i < lines.length) {
    const item = ITEM.exec(lines[i]);
    if (!item || item[1].length !== base || /\d/.test(item[2]) !== ordered) break;
    // what's under this item is whatever is indented to its text (or past its marker)
    const inner = base + item[2].length + Math.min(item[3].length || 1, 4);
    const body: string[] = [item[4]];
    i += 1;
    while (i < lines.length) {
      if (blank(lines[i])) {
        // a gap: the item goes on if what follows is still indented under it
        let after = i;
        while (after < lines.length && blank(lines[after])) after += 1;
        if (after < lines.length && indentOf(lines[after]) > base) {
          for (; i < after; i++) body.push("");
          continue;
        }
        break;
      }
      const indent = indentOf(lines[i]);
      if (indent <= base) {
        // back at the list's own level: a new item, the end of the list, or a paragraph's
        // next line written without its indent
        if (ITEM.test(lines[i]) || indent < base || starts(lines[i], lines[i + 1]) || body.at(-1) === "") break;
        body.push(lines[i].trimStart());
      } else body.push(lines[i].slice(Math.min(indent, inner)));
      i += 1;
    }
    while (body.at(-1) === "") body.pop();
    if (body.includes("")) loose = true;
    const box = BOX.exec(body[0] ?? "");
    if (box) body[0] = body[0].slice(box[0].length);
    items.push({ checked: box ? box[1] !== " " : null, blocks: blocksOf(body, references) });
    // a gap between items makes the list a loose one, but isn't its end
    let next = i;
    while (next < lines.length && blank(lines[next])) next += 1;
    const more = next < lines.length ? ITEM.exec(lines[next]) : null;
    if (next > i && more && more[1].length === base && /\d/.test(more[2]) === ordered) {
      loose = true;
      i = next;
    }
  }
  const start = ordered ? Number.parseInt(first[2], 10) : 1;
  return [{ kind: "list", ordered, start, tight: !loose, items }, i];
}

// --- within a line ---------------------------------------------------------------------------

const PUNCTUATION = /[!-/:-@[-`{-~]/;

/** A line's (or a paragraph's) text as its parts. */
export function inlinesOf(text: string, references: References = new Map()): Inline[] {
  const out: Inline[] = [];
  let buffer = "";
  const flush = () => {
    if (buffer) out.push({ kind: "text", text: buffer });
    buffer = "";
  };
  let i = 0;
  while (i < text.length) {
    const char = text[i];
    if (char === "\\" && i + 1 < text.length) {
      if (text[i + 1] === "\n") {
        flush();
        out.push({ kind: "break" });
        i += 2;
        continue;
      }
      if (PUNCTUATION.test(text[i + 1])) {
        buffer += text[i + 1];
        i += 2;
        continue;
      }
    }
    if (char === "\n") {
      // a line's end is a space, or a break after two spaces
      const hard = buffer.endsWith("  ");
      buffer = buffer.replace(/ +$/, "");
      if (hard) {
        flush();
        out.push({ kind: "break" });
      } else buffer += " ";
      i += 1;
      continue;
    }
    if (char === "`") {
      let run = 1;
      while (text[i + run] === "`") run += 1;
      const close = closingTicks(text, i + run, run);
      if (close >= 0) {
        let code = text.slice(i + run, close).replace(/\n/g, " ");
        if (code.length > 2 && code.startsWith(" ") && code.endsWith(" ") && code.trim() !== "") code = code.slice(1, -1);
        flush();
        out.push({ kind: "code", text: code });
        i = close + run;
        continue;
      }
      buffer += "`".repeat(run);
      i += run;
      continue;
    }
    if (char === "!" && text[i + 1] === "[") {
      const link = linkAt(text, i + 1, references);
      if (link) {
        flush();
        out.push({ kind: "image", src: link.href, alt: plain(inlinesOf(link.text, references)) });
        i = link.end;
        continue;
      }
    }
    if (char === "[") {
      const link = linkAt(text, i, references);
      if (link) {
        flush();
        out.push({ kind: "link", href: link.href, children: inlinesOf(link.text, references) });
        i = link.end;
        continue;
      }
    }
    if (char === "<") {
      const auto = /^<(https?:\/\/[^\s<>]+)>/.exec(text.slice(i));
      if (auto) {
        flush();
        out.push({ kind: "link", href: auto[1], children: [{ kind: "text", text: auto[1] }] });
        i += auto[0].length;
        continue;
      }
    }
    if (char === "h" && (i === 0 || !/[\p{L}\p{N}/]/u.test(text[i - 1]))) {
      const bare = BARE.exec(text.slice(i));
      if (bare) {
        flush();
        out.push({ kind: "link", href: bare[0], children: [{ kind: "text", text: bare[0] }] });
        i += bare[0].length;
        continue;
      }
    }
    if (char === "*" || char === "_") {
      const emphasis = emphasisAt(text, i);
      if (emphasis) {
        flush();
        const children = inlinesOf(text.slice(i + emphasis.width, emphasis.close), references);
        out.push(emphasis.width === 2 ? { kind: "strong", children } : { kind: "em", children });
        i = emphasis.close + emphasis.width;
        continue;
      }
    }
    buffer += char;
    i += 1;
  }
  flush();
  return out;
}

/** Where the run of `count` backticks that closes a code span is, from `from`; -1 if none. */
function closingTicks(text: string, from: number, count: number): number {
  let i = from;
  while (i < text.length) {
    if (text[i] !== "`") {
      i += 1;
      continue;
    }
    let run = 1;
    while (text[i + run] === "`") run += 1;
    if (run === count) return i;
    i += run;
  }
  return -1;
}

/** The bracket that closes the one at `open`, past any nested ones and code. */
function closingBracket(text: string, open: number): number {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    const char = text[i];
    if (char === "\\") i += 1;
    else if (char === "`") {
      let run = 1;
      while (text[i + run] === "`") run += 1;
      const close = closingTicks(text, i + run, run);
      i = close >= 0 ? close + run - 1 : i + run - 1;
    } else if (char === "[") depth += 1;
    else if (char === "]") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/** A link whose text's bracket opens at `open`: [text](address), [text][name], [name]. */
function linkAt(text: string, open: number, references: References): { text: string; href: string; end: number } | null {
  const close = closingBracket(text, open);
  if (close < 0) return null;
  const inner = text.slice(open + 1, close);
  if (text[close + 1] === "(") {
    // its address runs to the bracket that closes it (addresses with brackets of their own balance)
    let depth = 0;
    for (let i = close + 1; i < text.length; i++) {
      if (text[i] === "\\") i += 1;
      else if (text[i] === "(") depth += 1;
      else if (text[i] === ")") {
        depth -= 1;
        if (depth === 0) {
          const target = /^<?(\S*?)>?(?:\s+["'(].*["')])?$/.exec(text.slice(close + 2, i).trim());
          return target ? { text: inner, href: target[1], end: i + 1 } : null;
        }
      } else if (text[i] === "\n") break;
    }
    return null;
  }
  if (text[close + 1] === "[") {
    const end = text.indexOf("]", close + 2);
    if (end >= 0) {
      const href = references.get(label(text.slice(close + 2, end) || inner));
      if (href !== undefined) return { text: inner, href, end: end + 1 };
    }
  }
  const href = references.get(label(inner));
  return href === undefined ? null : { text: inner, href, end: close + 1 };
}

/** Emphasis that opens at `at`: its marks' width (2: bold, 1: italics) and where it closes. */
function emphasisAt(text: string, at: number): { width: number; close: number } | null {
  const mark = text[at];
  const before = at > 0 ? text[at - 1] : " ";
  for (const width of [2, 1]) {
    if (text.slice(at, at + width) !== mark.repeat(width)) continue;
    const next = text[at + width];
    if (next === undefined || /\s/.test(next) || next === mark) continue;
    // an underscore inside a word (snake_case) isn't emphasis
    if (mark === "_" && /[\p{L}\p{N}]/u.test(before)) continue;
    let i = at + width;
    while (i < text.length) {
      const char = text[i];
      if (char === "\\") {
        i += 2;
        continue;
      }
      if (char === "`") {
        let run = 1;
        while (text[i + run] === "`") run += 1;
        const close = closingTicks(text, i + run, run);
        i = close >= 0 ? close + run : i + run;
        continue;
      }
      if (text.slice(i, i + width) === mark.repeat(width) && !/\s/.test(text[i - 1])) {
        const after = text[i + width];
        const longer = after === mark && width === 1; // the first of a ** pair: not this one's end
        const inWord = mark === "_" && after !== undefined && /[\p{L}\p{N}]/u.test(after);
        if (!longer && !inWord) return { width, close: i };
        if (longer) {
          i += 2;
          continue;
        }
      }
      i += 1;
    }
  }
  return null;
}
