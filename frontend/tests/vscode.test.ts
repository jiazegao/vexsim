import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";

// The VS Code extension's helpers (vexsim/ui/vscode/panel.js, CommonJS)
const require = createRequire(import.meta.url);
const panel = require("../../vexsim/ui/vscode/panel.js") as {
  appUrl: (url: string, theme: string) => string;
  findUrl: (text: string) => { url: string; base: string; token: string } | null;
  panelHtml: (src: string, nonce: string) => string;
  runWith: (python: string, platform: string, exists: (file: string) => boolean) => string;
  themeOf: (kind: number) => string;
};

describe("the VS Code panel", () => {
  it("finds the app's address in what vexsim ui prints", () => {
    const said = "vexsim UI for C:\\robots\n  http://127.0.0.1:8642/?token=Ab_c-9\nKeep this window open";
    expect(panel.findUrl(said)).toEqual({ url: "http://127.0.0.1:8642/?token=Ab_c-9", base: "http://127.0.0.1:8642", token: "Ab_c-9" });
    expect(panel.findUrl("vexsim UI for /robots\n  http://127.0.0.1:86")).toBeNull(); // not all here yet
    expect(panel.appUrl("http://127.0.0.1:8642/?token=t", "dark")).toBe("http://127.0.0.1:8642/?token=t&embed=vscode&theme=dark");
  });

  it("follows VS Code's light and dark themes", () => {
    expect([1, 2, 3, 4].map(panel.themeOf)).toEqual(["light", "dark", "dark", "light"]);
  });

  it("runs vexsim with pythonw on Windows when there is one", () => {
    const there = (file: string) => file.endsWith("pythonw.exe");
    expect(panel.runWith("C:\\Py\\python.exe", "win32", there)).toBe("C:\\Py\\pythonw.exe");
    expect(panel.runWith("C:\\Py\\python.exe", "win32", () => false)).toBe("C:\\Py\\python.exe");
    expect(panel.runWith("/usr/bin/python3", "linux", there)).toBe("/usr/bin/python3");
  });

  it("frames only the app, and passes its messages on", () => {
    const html = panel.panelHtml("http://127.0.0.1:8642/?token=t&embed=vscode&theme=dark", "N0nce");
    expect(html).toContain("frame-src http://127.0.0.1:8642; style-src 'nonce-N0nce'; script-src 'nonce-N0nce';");
    expect(html).toContain('src="http://127.0.0.1:8642/?token=t&amp;embed=vscode&amp;theme=dark"');
    expect(html).toContain('const origin = "http://127.0.0.1:8642";');
    expect(html).toContain("vscode.postMessage(event.data)");
  });
});
