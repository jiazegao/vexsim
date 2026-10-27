// Colors for the canvas, read from the page's CSS tokens (styles.css), so the field
// follows the light and dark themes like the rest of the page.

export interface Palette {
  page: string;
  surface: string;
  ink: string;
  ink2: string;
  muted: string;
  grid: string;
  axis: string;
  truth: string; // the true path
  estimate: string; // where the robot code thinks it is
  target: string; // a motion's path and target
  beam: string; // distance sensor beams
  slip: string; // a wheel at its grip limit
  wheel: string; // a wheel well within it
  obstacle: string;
  piece: string;
  focus: string; // what's selected
  critical: string; // something with an error
  warning: string;
}

const TOKENS: Record<keyof Palette, string> = {
  page: "--page",
  surface: "--surface-1",
  ink: "--text-primary",
  ink2: "--text-secondary",
  muted: "--text-muted",
  grid: "--gridline",
  axis: "--axis",
  truth: "--series-3",
  estimate: "--series-1",
  target: "--series-2",
  beam: "--series-4",
  slip: "--series-8",
  wheel: "--wheel",
  obstacle: "--obstacle",
  piece: "--series-4",
  focus: "--focus",
  critical: "--critical",
  warning: "--warning",
};

export function readPalette(element: Element = document.documentElement): Palette {
  const style = getComputedStyle(element);
  const palette = {} as Palette;
  for (const [name, token] of Object.entries(TOKENS) as [keyof Palette, string][]) {
    palette[name] = style.getPropertyValue(token).trim() || "#888888";
  }
  return palette;
}

/** `#rrggbb` mixed toward `#rrggbb` by t (0-1). */
export function mix(a: string, b: string, t: number): string {
  const pa = parse(a);
  const pb = parse(b);
  if (!pa || !pb) return t < 0.5 ? a : b;
  const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * Math.min(1, Math.max(0, t))));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

/** `#rrggbb` at an opacity, for canvas fills. */
export function withAlpha(color: string, alpha: number): string {
  const p = parse(color);
  return p ? `rgba(${p[0]}, ${p[1]}, ${p[2]}, ${alpha})` : color;
}

function parse(color: string): [number, number, number] | null {
  const m = /^#([0-9a-f]{6})$/i.exec(color.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
