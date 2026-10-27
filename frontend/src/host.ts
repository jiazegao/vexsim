// The app inside another app: the VS Code panel shows it in a frame, its link saying so
// (?embed=vscode&theme=dark). There, file:line links open in VS Code, files are saved
// through VS Code's save dialog, pages open in the system's browser, and the colors follow
// VS Code's theme. The frame's parent says hello once the app has loaded, which gives its
// origin; the app answers that it's ready, and sends it everything else from then on.

export type HostTheme = "light" | "dark";

export const HOSTS: Record<string, string> = { vscode: "VS Code" };
const KEY = "vexsim.embed";

function keepEmbed(): string | null {
  const fromUrl = new URL(location.href).searchParams.get("embed");
  try {
    if (fromUrl) sessionStorage.setItem(KEY, fromUrl);
    else return sessionStorage.getItem(KEY);
  } catch {
    // storage off: as the link says
  }
  return fromUrl;
}

const asTheme = (value: unknown): HostTheme | null => (value === "light" || value === "dark" ? value : null);

const framed = typeof window !== "undefined" && window.parent !== window; // not in unit tests

/** The app this page is inside ("vscode"), or null in a tab or window of its own. */
export const embedded: string | null = framed ? keepEmbed() : null;

let hostOrigin: string | null = null;
let theme = framed ? asTheme(new URL(location.href).searchParams.get("theme")) : null;
const themeListeners = new Set<(theme: HostTheme) => void>();

if (embedded) {
  window.addEventListener("message", (event: MessageEvent) => {
    if (event.source !== window.parent || typeof event.data !== "object" || event.data === null) return;
    const data = event.data as { type?: unknown; theme?: unknown };
    if (data.type === "vexsim.host") {
      hostOrigin = event.origin;
      tell({ type: "vexsim.ready" });
    } else if (data.type !== "vexsim.theme" || event.origin !== hostOrigin) {
      return;
    }
    const next = asTheme(data.theme);
    if (next && next !== theme) {
      theme = next;
      themeListeners.forEach((listener) => listener(next));
    }
  });
}

function tell(message: Record<string, unknown>, transfer: Transferable[] = []): boolean {
  if (!hostOrigin) return false;
  window.parent.postMessage(message, hostOrigin, transfer);
  return true;
}

/** The host's theme: what its link or its last word said; null outside one. */
export function hostTheme(): HostTheme | null {
  return embedded ? theme : null;
}

/** Call `listener` when the host's theme changes. */
export function onHostTheme(listener: (theme: HostTheme) => void): () => void {
  themeListeners.add(listener);
  return () => {
    themeListeners.delete(listener);
  };
}

/** Open `file` (absolute) at a line in the host's editor; false if there's no host to. */
export function openInHost(file: string, line: number, column: number | null): boolean {
  return tell({ type: "vexsim.open", file, line, column });
}

/** Open one of the server's pages (a report) in the system's browser, from inside the host. */
export function openInBrowser(url: string): boolean {
  return tell({ type: "vexsim.browse", url: new URL(url, location.href).href });
}

/** Save `blob` as `filename`: a download, or inside the host, through its save dialog. */
export function saveFile(blob: Blob, filename: string): void {
  const name = filename.replace(/[^A-Za-z0-9._ -]+/g, "_");
  if (embedded) {
    void blob.arrayBuffer().then((data) => tell({ type: "vexsim.save", name, data }, [data]));
    return;
  }
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 10_000);
}

/** Fetch one of the server's files (`url` has the token) and save it as `saveFile` does. */
export async function saveServerFile(url: string, filename: string): Promise<void> {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`${filename}: ${response.status} ${response.statusText}`);
  const named = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1];
  saveFile(await response.blob(), named ?? filename);
}
