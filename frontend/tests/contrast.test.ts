// The stylesheet's colors, checked for contrast (phase 15.5): every color that text wears, on
// every surface text sits on, in the light theme and the dark one, reads at 4.5:1 or better
// (WCAG AA), and so does the text on each fill. Runs in Node (it reads the stylesheet), so it's
// checked with the Node files (tsconfig.node.json).

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(import.meta.dirname, "../src/styles.css"), "utf-8");

/** The custom properties a rule sets, by the text its selector starts with. */
function tokens(selector: string): Record<string, string> {
  const at = css.indexOf(selector);
  expect(at, selector).toBeGreaterThanOrEqual(0);
  const body = css.slice(css.indexOf("{", at) + 1, css.indexOf("}", at));
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2].trim()]));
}

type Rgb = [number, number, number];

function rgb(color: string): Rgb {
  const hex = /^#([0-9a-f]{6})$/i.exec(color);
  expect(hex, color).not.toBeNull();
  return [0, 2, 4].map((i) => Number.parseInt(hex![1].slice(i, i + 2), 16) / 255) as Rgb;
}

/** A translucent color (rgba(...)) as it shows over a surface. */
function over(color: string, base: Rgb): Rgb {
  const parts = /^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/.exec(color);
  expect(parts, color).not.toBeNull();
  const alpha = Number(parts![4]);
  return [1, 2, 3].map((i, k) => (alpha * Number(parts![i])) / 255 + (1 - alpha) * base[k]) as Rgb;
}

function luminance(color: Rgb): number {
  const [r, g, b] = color.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG's contrast ratio of two colors: 1 (the same) to 21 (black on white). */
function contrast(a: Rgb, b: Rgb): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const LIGHT = tokens(":root {");
const THEMES: [string, Record<string, string>][] = [
  ["light", LIGHT],
  ["dark, as the system asks", { ...LIGHT, ...tokens(':root:where(:not([data-theme="light"])) {') }],
  ["dark, as picked", { ...LIGHT, ...tokens(':root[data-theme="dark"] {') }],
];
const TEXT = ["--text-primary", "--text-secondary", "--text-muted", "--link", "--bad-text", "--good-text", "--warning-text", "--syntax-key", "--syntax-string", "--syntax-comment"];
const FILLS: [string, string][] = [
  ["--primary", "#ffffff"],
  ["--good-fill", "#ffffff"],
  ["--chip-fill", "#ffffff"],
  ["--critical", "#ffffff"],
  ["--warning", "#0b0b0b"],
];
const AA = 4.5;

describe.each(THEMES)("the %s theme", (_name, theme) => {
  const surfaces: [string, Rgb][] = ["--page", "--surface-1", "--surface-2", "--surface-3"].map((name) => [name, rgb(theme[name])]);
  // what's selected or switched on sits on the accent's wash, over a surface
  for (const name of ["--page", "--surface-1", "--surface-2"]) surfaces.push([`the wash on ${name}`, over(theme["--accent-wash"], rgb(theme[name]))]);

  it("has text that reads on every surface", () => {
    const low: string[] = [];
    for (const text of TEXT) {
      for (const [surface, color] of surfaces) {
        const ratio = contrast(rgb(theme[text]), color);
        if (ratio < AA) low.push(`${text} (${theme[text]}) on ${surface}: ${ratio.toFixed(2)}`);
      }
    }
    expect(low).toEqual([]);
  });

  it("has fills their text reads on", () => {
    for (const [fill, text] of FILLS) expect([fill, contrast(rgb(text), rgb(theme[fill])) >= AA]).toEqual([fill, true]);
  });
});

describe("the stylesheet", () => {
  it("has one dark theme, however it's asked for", () => {
    expect(tokens(':root[data-theme="dark"] {')).toEqual(tokens(':root:where(:not([data-theme="light"])) {'));
  });

  it("colors text with the text colors, not the marks'", () => {
    // the series colors, and the status colors, are for lines, dots and fills: as text they're too faint
    const worn = [...css.matchAll(/^\s*color:\s*var\(--(series-\d|critical|good|warning)\)/gm)].map((m) => m[0].trim());
    expect(worn).toEqual([]);
  });
});
