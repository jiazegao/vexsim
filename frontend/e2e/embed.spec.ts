import { mkdirSync, writeFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { createRequire } from "node:module";
import type { AddressInfo } from "node:net";
import { dirname, join, relative, resolve } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { PORT, TOKEN } from "../playwright.config";

// The app inside another app, as the VS Code panel shows it: in a frame on a page of another
// site, so it gets no cookie, and it tells that page what to open and save. That page is
// served from localhost, another site than 127.0.0.1 but on this computer too (a page from
// the internet may not frame one on this computer).
const ROBOT = "examples/robots/full_omni_6m.yaml";
const WORKSPACE = resolve(import.meta.dirname, "../.."); // what the test server opened
const APP = `http://127.0.0.1:${PORT}`;

// The panel's page: the app in a frame, a hello when it has loaded, and what the app says
// kept in `told` (for a saved file, its size and first bytes)
const HOST_PAGE = `<!doctype html><meta charset="utf-8">
<style>html, body { margin: 0; height: 100% } iframe { border: 0; width: 100%; height: 100% }</style>
<iframe id="app" src="${APP}/?token=${TOKEN}&embed=vscode&theme=dark"></iframe>
<script>
  window.told = [];
  const frame = document.getElementById("app");
  const say = (message) => frame.contentWindow.postMessage(message, "${APP}");
  frame.addEventListener("load", () => say({ type: "vexsim.host", theme: "dark" }));
  window.addEventListener("message", (event) => {
    if (event.source !== frame.contentWindow || event.origin !== "${APP}") return;
    const message = { ...event.data };
    if (message.data instanceof ArrayBuffer) {
      message.size = message.data.byteLength;
      message.data = Array.from(new Uint8Array(message.data.slice(0, 4)));
    }
    told.push(message);
  });
  window.setTheme = (theme) => say({ type: "vexsim.theme", theme });
</script>`;

type Told = { type: string; [key: string]: unknown };
const told = (page: Page) => page.evaluate(() => (window as unknown as { told: Told[] }).told);
const toldOf = async (page: Page, type: string) => (await told(page)).filter((message) => message.type === type);

let problems: string[] = []; // the app's errors, which fail the test

// The VS Code panel's own page (vexsim/ui/vscode/panel.js), with the app in it
const { panelHtml } = createRequire(import.meta.url)("../../vexsim/ui/vscode/panel.js") as {
  panelHtml: (src: string, nonce: string) => string;
};
const PANEL_PAGE = panelHtml(`${APP}/?token=${TOKEN}&embed=vscode&theme=dark`, "N0nce");

let host: Server; // the stand-ins for VS Code's panel

test.beforeAll(async () => {
  host = createServer((request, response) => {
    response.writeHead(200, { "content-type": "text/html" }).end(request.url === "/panel" ? PANEL_PAGE : HOST_PAGE);
  });
  await new Promise<void>((done) => host.listen(0, "127.0.0.1", done));
});

test.afterAll(() => {
  host.close();
});

test.beforeEach(async ({ page }) => {
  problems = [];
  page.on("pageerror", (error) => problems.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  await page.goto(`http://localhost:${(host.address() as AddressInfo).port}/`);
});

test.afterEach(async ({ page }) => {
  expect(problems).toEqual([]);
  const auth = { headers: { authorization: `Bearer ${TOKEN}` } };
  for (const session of await (await page.request.get(`${APP}/api/sessions`, auth)).json()) {
    if (session.state !== "stopped") await page.request.delete(`${APP}/api/sessions/${session.id}`, auth);
  }
});

test("works in another app's frame, which says what to open and save", async ({ page }, testInfo) => {
  const app = page.frameLocator("#app");
  // it loads and talks to the server with no cookie, and says it's ready
  await expect(app.getByTestId(`item-${ROBOT}`)).toBeVisible();
  await expect.poll(async () => (await toldOf(page, "vexsim.ready")).length).toBe(1);
  const info = await page.request.get(`${APP}/api/info`, { headers: { authorization: `Bearer ${TOKEN}` } });
  expect((await info.json()).pages).toBeGreaterThanOrEqual(1); // it holds the server open

  // its colors are the host's
  const html = app.locator("html");
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.evaluate(() => (window as unknown as { setTheme: (theme: string) => void }).setTheme("light"));
  await expect(html).toHaveAttribute("data-theme", "light");

  // the field's picture is saved through the host
  await app.getByRole("button", { name: "Save picture" }).click();
  await expect.poll(async () => (await toldOf(page, "vexsim.save")).length).toBe(1);
  const [picture] = await toldOf(page, "vexsim.save");
  expect(picture.name).toMatch(/^vexsim-.*\.png$/);
  expect(picture.data).toEqual([0x89, 0x50, 0x4e, 0x47]); // a PNG
  expect(picture.size as number).toBeGreaterThan(1000);

  // where a program failed opens in the host's editor, which needs no choosing
  await expect(app.getByText("Open files in")).toHaveCount(0);
  const program = testInfo.outputPath("fails.py"); // inside the workspace, cleaned each run
  mkdirSync(dirname(program), { recursive: true });
  writeFileSync(program, "def autonomous(bot):\n    yield\n    spin_the_wheels()\n");
  const path = relative(WORKSPACE, program).split("\\").join("/");
  await app.getByRole("button", { name: "Refresh" }).click();
  await app.getByTestId("robot").selectOption(ROBOT);
  await app.getByTestId("program").selectOption(path);
  await app.getByTestId("run").click();
  await expect(app.getByTestId("status")).toHaveText("Error");
  await app.getByTestId("problem-link").click();
  await expect.poll(async () => (await toldOf(page, "vexsim.open")).length).toBe(1);
  const [opened] = await toldOf(page, "vexsim.open");
  expect(resolve(opened.file as string)).toBe(resolve(join(WORKSPACE, path)));
  expect(opened.line).toBe(3);
});

test("the VS Code panel's page frames the app and passes on what it says", async ({ page }) => {
  // VS Code's side of the panel: what the page passes on is kept in `relayed`
  await page.addInitScript(() => {
    const relayed: unknown[] = [];
    Object.assign(window, { relayed, acquireVsCodeApi: () => ({ postMessage: (message: unknown) => relayed.push(message) }) });
  });
  await page.goto(`http://localhost:${(host.address() as AddressInfo).port}/panel`);
  const relayed = () => page.evaluate(() => (window as unknown as { relayed: Told[] }).relayed);
  const app = page.frameLocator("#app");
  await expect(app.getByTestId(`item-${ROBOT}`)).toBeVisible();
  await expect.poll(async () => (await relayed()).map((message) => message.type)).toEqual(["vexsim.ready"]);
  await expect(page.locator("#status")).toHaveCount(0); // "Starting vexsim…"
  // VS Code's theme changes: the app's colors follow
  await expect(app.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.evaluate(() => document.body.classList.add("vscode-light"));
  await expect(app.locator("html")).toHaveAttribute("data-theme", "light");
  // a place the app opens goes on to VS Code
  await app.getByRole("button", { name: "Save picture" }).click();
  await expect.poll(async () => (await relayed()).map((message) => message.type)).toEqual(["vexsim.ready", "vexsim.save"]);
});
