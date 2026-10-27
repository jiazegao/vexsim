// Problems: compiler diagnostics and Python tracebacks, found in a run's output, as
// file:line places that open in your editor (VS Code's vscode://file/... links).

export type Severity = "error" | "warning";

export interface Place {
  file: string; // as the output gave it: absolute, or relative to the workspace
  line: number;
  column: number | null;
}

export interface Problem extends Place {
  severity: Severity;
  message: string;
}

// g++: "path:line:col: error: message" (and "fatal error", "warning"; notes are left in
// the log). The linker: "path:line:(.text+0x1c): undefined reference to ...". A path
// must end in a file extension, so times like 12:30:45 aren't taken for one.
const DIAGNOSTIC =
  /^(?<file>(?:[A-Za-z]:)?[^:\n]*\.[A-Za-z][A-Za-z0-9_+-]*):(?<line>\d+):(?:(?<column>\d+):)?\s*(?:(?<severity>fatal error|error|warning|note):\s*)?(?<message>.*)$/;
const LINKER = /undefined reference|multiple definition/;
const FRAME = /^\s*File "(?<file>[^"]+)", line (?<line>\d+)/;

/** The errors and warnings in a compiler's output, each once. */
export function compilerProblems(text: string): Problem[] {
  const problems: Problem[] = [];
  const seen = new Set<string>();
  for (const raw of text.split("\n")) {
    const match = DIAGNOSTIC.exec(raw.trimEnd());
    const groups = match?.groups;
    if (!groups) continue;
    let severity: Severity | null = null;
    if (groups.severity === "warning") severity = "warning";
    else if (groups.severity === "error" || groups.severity === "fatal error") severity = "error";
    else if (!groups.severity && LINKER.test(groups.message)) severity = "error";
    if (!severity) continue; // a note, or context like "In function ..."
    const problem: Problem = {
      severity,
      file: groups.file.trim(),
      line: Number(groups.line),
      column: groups.column ? Number(groups.column) : null,
      message: groups.message.replace(/^\(\.\w+\+0x[0-9a-f]+\):\s*/i, ""),
    };
    const key = `${problem.file}:${problem.line}:${problem.column}:${problem.message}`;
    if (!seen.has(key)) {
      seen.add(key);
      problems.push(problem);
    }
  }
  return problems;
}

/** Where a Python traceback went wrong: its innermost frame in the workspace (or its
 * innermost frame), with the exception's message. */
export function tracebackProblem(traceback: string, root?: string): Problem | null {
  const lines = traceback.trimEnd().split("\n");
  const frames: Place[] = [];
  for (const line of lines) {
    const groups = FRAME.exec(line)?.groups;
    if (groups && !groups.file.startsWith("<")) frames.push({ file: groups.file, line: Number(groups.line), column: null });
  }
  if (frames.length === 0) return null;
  const mine = root ? frames.filter((f) => inside(root, f.file)) : [];
  const place = (mine.length ? mine : frames).at(-1)!;
  const message = lines.at(-1)?.trim() || "error";
  return { ...place, severity: "error", message };
}

export type Segment = string | (Place & { text: string });

// Places inside a line of text: "path/file.ext:12:5" (a path with a / or \), or a
// traceback's 'File "path", line 12'.
const PLACES =
  /(?<file>(?:[A-Za-z]:)?[^\s:"'()]*[\\/][^\s:"'()]*\.[A-Za-z][A-Za-z0-9_+-]*):(?<line>\d+)(?::(?<column>\d+))?|File "(?<pfile>[^"]+)", line (?<pline>\d+)/g;

/** A line of output split into plain text and places to link. */
export function linkSegments(text: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(PLACES)) {
    const groups = match.groups!;
    const file = groups.file ?? groups.pfile;
    if (file.startsWith("<")) continue;
    if (match.index > last) segments.push(text.slice(last, match.index));
    segments.push({
      text: match[0],
      file,
      line: Number(groups.line ?? groups.pline),
      column: groups.column ? Number(groups.column) : null,
    });
    last = match.index + match[0].length;
  }
  if (last < text.length) segments.push(text.slice(last));
  return segments;
}

export const EDITORS = {
  vscode: "VS Code",
  "vscode-insiders": "VS Code Insiders",
  cursor: "Cursor",
  none: "No editor (copy the place)",
} as const;
export type Editor = keyof typeof EDITORS;

/** A link that opens the place in the editor, or null for none. */
export function editorUrl(editor: Editor, root: string, place: Place): string | null {
  if (editor === "none") return null;
  let path = absolute(root, place.file).replace(/\\/g, "/");
  if (!path.startsWith("/")) path = `/${path}`; // C:/x -> /C:/x
  const at = `:${place.line}${place.column ? `:${place.column}` : ""}`;
  return `${editor}://file${encodeURI(path)}${at}`;
}

/** A file's path as people read it: relative to the workspace when it's inside. */
export function shortPath(root: string, file: string): string {
  if (!inside(root, file)) return file;
  return normal(file).slice(normal(root).replace(/\/$/, "").length + 1);
}

function absolute(root: string, file: string): string {
  if (/^([A-Za-z]:)?[\\/]/.test(file)) return file;
  const separator = root.includes("\\") && !root.includes("/") ? "\\" : "/";
  return `${root.replace(/[\\/]$/, "")}${separator}${file}`;
}

function normal(path: string): string {
  const forward = path.replace(/\\/g, "/");
  return /^[A-Za-z]:/.test(forward) ? forward.toLowerCase() : forward; // Windows ignores case
}

function inside(root: string, file: string): boolean {
  const base = normal(root).replace(/\/$/, "");
  return normal(file).startsWith(`${base}/`);
}
