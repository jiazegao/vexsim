import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { NEW_URL, TOKEN } from "../playwright.config";

// Phase 15.5: an accessibility audit of every page (axe-core), in the light theme and the dark
// one: nothing serious or critical (text that's hard to read, a control with no name, a role
// used wrongly). And the keyboard's way to Run: two presses with the skip link, a dozen without.

const ROBOT = "examples/robots/full_omni_6m.yaml";
const FIELD = "examples/fields/practice_elements.yaml";
const ROUTE = "examples/pros_projects/1239e_2026-27/routes/left_start.yaml";
const AXE = readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), "utf-8");

interface Violation {
  id: string;
  impact: string | null;
  help: string;
  nodes: { html: string; target: string[]; any: { message: string }[]; all: { message: string }[]; none: { message: string }[] }[];
}

/** What's seriously wrong with the page as it is now, a line each (none, if all is well). */
async function findings(page: Page): Promise<string[]> {
  await page.evaluate(AXE); // defines window.axe (again, after a reload)
  const violations = (await page.evaluate(async () => {
    const axe = (window as unknown as { axe: { run: (context: Document, options: object) => Promise<{ violations: unknown[] }> } }).axe;
    return (await axe.run(document, { resultTypes: ["violations"] })).violations;
  })) as Violation[];
  return violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => {
      const node = v.nodes[0];
      const why = (node.any[0] ?? node.all[0] ?? node.none[0])?.message ?? "";
      return `${v.id} (${v.impact}, ${v.nodes.length}): ${v.help}. ${node.target.join(" ")}: ${node.html.replace(/\s+/g, " ").slice(0, 140)} ${why.slice(0, 200)}`;
    });
}

/** The page audited as it is, in the light theme and then the dark one. */
async function audit(page: Page, scene: string) {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.waitForTimeout(150); // the theme's colors, settled
    expect.soft(await findings(page), `${scene}, ${scheme}`).toEqual([]);
  }
  await page.emulateMedia({ colorScheme: "light" });
}

let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  page.on("pageerror", (error) => problems.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  await page.goto(`/?token=${TOKEN}`);
  await expect(page.getByTestId(`item-${ROBOT}`)).toBeAttached(); // (folded away, in a narrow window)
});

test.afterEach(async ({ page }) => {
  expect(problems).toEqual([]);
  for (const session of await (await page.request.get("/api/sessions")).json()) {
    if (session.state !== "stopped") await page.request.delete(`/api/sessions/${session.id}`);
  }
});

async function edit(page: Page, path: string) {
  await page.getByTestId(`item-${path}`).click({ button: "right" });
  await page.getByTestId(`edit-${path}`).click();
}

test("the Simulate page: set up, with a run on show, its plots, its dialogs", async ({ page }) => {
  await audit(page, "Simulate, nothing run");
  await page.getByTestId("config").selectOption("Tour (Python)");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Running", { timeout: 60_000 });
  await page.getByTestId("pause").click();
  await expect(page.getByTestId("status")).toHaveText("Paused");
  await audit(page, "Simulate, a run paused");
  await page.locator(".controls .speed select").selectOption("0");
  await page.getByTestId("pause").click();
  await expect(page.getByTestId("status")).toHaveText("Finished", { timeout: 60_000 });
  await expect(page.getByTestId("timeline")).toBeVisible();
  await page.getByTestId("key-toggle").click();
  await audit(page, "Simulate, a finished run, the key open");
  await page.getByTestId("plots-tab").click();
  await expect(page.getByTestId("plot-pose-error")).toBeVisible();
  await audit(page, "Simulate, plots");
  await page.getByTestId("tab-runs").click();
  await audit(page, "Simulate, the run history");
  await page.getByTestId("keys").click();
  await audit(page, "Keys");
  await page.keyboard.press("Escape");
  await page.getByTestId("tab-workspace").click();
  await page.getByTestId(`item-${ROBOT}`).click({ button: "right" });
  await audit(page, "an item's menu");
  await page.keyboard.press("Escape");
  await page.getByTestId("new-robot").click();
  await expect(page.getByTestId("new-robot-dialog")).toBeVisible();
  await audit(page, "New robot");
  await page.keyboard.press("Escape");
  await page.getByTestId("new-route").click();
  await expect(page.getByTestId("new-route-dialog")).toBeVisible();
  await audit(page, "New route");
  await page.keyboard.press("Escape");
});

test("the other pages", async ({ page }) => {
  for (const id of ["sweeps", "bench", "analyze", "build"]) {
    await page.getByTestId(`page-${id}`).click();
    await page.waitForTimeout(400);
    await audit(page, id);
  }
  await page.getByTestId("page-analyze").click();
  for (const tool of ["drift", "odometry"]) {
    await page.getByTestId(`tool-${tool}`).click();
    await page.waitForTimeout(300);
    await audit(page, `Analyze, ${tool}`);
  }
  await page.getByTestId("page-calibrate").click();
  for (const tab of ["session", "check", "quick"]) {
    await page.getByTestId(`calibrate-tab-${tab}`).click();
    await page.waitForTimeout(400);
    await audit(page, `Calibrate, ${tab}`);
  }
  await page.getByTestId("page-guide").click();
  await expect(page.getByTestId("guide-document").locator("h1").first()).toBeVisible();
  await audit(page, "Guide");
});

test("the editors: a robot's YAML and its Design view, a route in the maker", async ({ page }) => {
  await edit(page, ROBOT);
  await expect(page.getByTestId("config-state")).toContainText("no problems");
  await audit(page, "a robot's YAML");
  await page.getByTestId("view-design").click();
  await page.waitForTimeout(300);
  await audit(page, "a robot's Design view");
  await edit(page, FIELD);
  await expect(page.locator('[data-testid="config-editor"]:not([hidden])')).toHaveAttribute("data-path", FIELD);
  await page.waitForTimeout(500);
  await audit(page, "a field's editor");
  await edit(page, ROUTE);
  await expect(page.getByTestId("route-state")).toBeVisible();
  await page.getByTestId("step-2").click();
  await page.waitForTimeout(500);
  await audit(page, "the autonomous maker");
});

/** What has the keyboard: its test id, or else what it is. */
const focused = (page: Page) =>
  page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    return el?.dataset.testid ?? el?.getAttribute("aria-label") ?? el?.tagName.toLowerCase() ?? "";
  });
/** Whether the keyboard is somewhere in the list at the side. */
const inSidebar = (page: Page) => page.evaluate(() => !!document.activeElement?.closest("#sidebar"));

test("the keyboard's way to Run: two presses with the skip link, a dozen without", async ({ page }) => {
  await page.keyboard.press("Tab");
  expect(await focused(page)).toBe("skip-to-run");
  await expect(page.getByTestId("skip-to-run")).toBeInViewport(); // on the page once it has the keyboard
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("run")).toBeFocused();

  // from another page too: to the Simulate page's Run
  await page.getByTestId("page-build").click();
  await page.getByTestId("skip-to-run").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("run")).toBeFocused();
  await expect(page.getByTestId("page-simulate")).toHaveAttribute("aria-selected", "true");

  // without it, each row of tabs, each toolbar and the list is one stop on the way
  await page.reload();
  await expect(page.getByTestId(`item-${ROBOT}`)).toBeVisible();
  const stops: string[] = [];
  while (stops.at(-1) !== "run" && stops.length < 40) {
    await page.keyboard.press("Tab");
    stops.push(await focused(page));
  }
  expect(stops.map((stop) => (stop.startsWith("item-") ? "an item" : stop))).toEqual([
    "skip-to-run",
    "sidebar-toggle",
    "page-simulate", // the pages' tabs
    "keys", // Keys and the theme
    "tab-workspace", // the list's tabs and Refresh
    "an item", // the list: the robot that's picked
    "config",
    "robot",
    "field-select",
    "program",
    "mode",
    "run",
  ]);
});

/** Press Tab until the keyboard is on a control (by its test id): how a group is reached. */
async function tabTo(page: Page, testid: string | RegExp) {
  for (let i = 0; i < 60; i++) {
    await page.keyboard.press("Tab");
    const at = await focused(page);
    if (typeof testid === "string" ? at === testid : testid.test(at)) return;
  }
  throw new Error(`Tab never reached ${testid}`);
}

test("each row of tabs and each list is one stop: the arrow keys move within it", async ({ page }) => {
  // the pages' tabs: Left and Right move, Enter picks
  const tab = (id: string) => page.getByTestId(`page-${id}`);
  await tabTo(page, "page-simulate");
  await page.keyboard.press("ArrowRight");
  await expect(tab("sweeps")).toBeFocused();
  await expect(tab("simulate")).toHaveAttribute("aria-selected", "true"); // moving isn't picking
  await page.keyboard.press("End");
  await expect(tab("guide")).toBeFocused();
  await page.keyboard.press("Home");
  await expect(tab("simulate")).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(tab("sweeps")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight"); // on to the next, and away without picking it
  await expect(tab("bench")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("keys")).toBeFocused();
  await page.keyboard.press("Shift+Tab"); // back: to the page that's on show
  await expect(tab("sweeps")).toBeFocused();
  await page.keyboard.press("Home");
  await page.keyboard.press("Enter");
  await expect(tab("simulate")).toHaveAttribute("aria-selected", "true");

  // the workspace's list: Up and Down between its items, Right to an item's menu button
  await tabTo(page, /^item-/);
  const picked = await focused(page); // the robot that's picked
  await page.keyboard.press("ArrowDown");
  const next = await focused(page);
  expect(next).toMatch(/^item-/);
  expect(next).not.toBe(picked);
  await page.keyboard.press("ArrowUp");
  expect(await focused(page)).toBe(picked);
  const path = picked.slice("item-".length);
  const item = page.getByTestId(picked);
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId(`menu-${path}`)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId(`edit-${path}`)).toBeFocused(); // the menu: its first action
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("item-menu")).toHaveCount(0);
  await expect(page.getByTestId(`menu-${path}`)).toBeFocused(); // the keyboard is back where it was
  await page.keyboard.press("ArrowLeft");
  await expect(item).toBeFocused();
  await page.keyboard.press("Shift+F10"); // the Menu key, by its other name
  await expect(page.getByTestId(`edit-${path}`)).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByTestId(`duplicate-${path}`)).toBeFocused();
  await page.keyboard.press("Tab"); // out of the menu: it closes
  await expect(page.getByTestId("item-menu")).toHaveCount(0);
  await expect(item).toBeFocused();
  await page.keyboard.press("Home");
  await expect(page.getByTestId("new-robot")).toBeFocused();
  await page.keyboard.press("Tab"); // and Tab passes the rest of the list by
  expect(await inSidebar(page)).toBe(false);

  // the runs: Left and Right along one run's actions
  await page.getByTestId("config").selectOption("Tour (Python)");
  await page.locator(".controls .speed select").selectOption("0");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Finished", { timeout: 60_000 });
  await page.getByTestId("tab-runs").click();
  const run = page.getByTestId("open-run").first();
  await expect(run).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(run).toBeFocused();
  await page.keyboard.press("ArrowRight");
  expect(await page.evaluate(() => !!document.activeElement?.closest(".run-actions"))).toBe(true);
  await page.keyboard.press("ArrowLeft");
  await expect(run).toBeFocused();
  await page.keyboard.press("Tab"); // one stop, however many runs there are
  expect(await inSidebar(page)).toBe(false);
});

test("after a click, the arrow keys are still the run's: they move through it, and drive", async ({ page }) => {
  await page.getByTestId("config").selectOption("Tour (Python)");
  await page.locator(".controls .speed select").selectOption("0");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Finished", { timeout: 60_000 });
  await expect(page.getByTestId("timeline")).toBeVisible(); // its recording, loaded
  const time = page.getByTestId("playhead-time");
  await page.keyboard.press("Home");
  await expect(time).toHaveAttribute("data-t", "0.000");

  // a tab clicked: Right moves the recorded run on half a second, not the keyboard to the next tab
  await page.getByTestId("plots-tab").click();
  await page.keyboard.press("ArrowRight");
  await expect(time).toHaveAttribute("data-t", "0.500");
  await expect(page.getByTestId("plots-tab")).toBeFocused();
  await page.getByTestId(`item-${ROBOT}`).click({ button: "right" }); // the same in the list
  await page.keyboard.press("Escape");
  await page.keyboard.press("End");
  await expect(time).not.toHaveAttribute("data-t", "0.500"); // its end

  // the same tabs reached with Tab: the arrows are theirs, and the run stays where it is
  await page.keyboard.press("Home");
  await expect(time).toHaveAttribute("data-t", "0.000");
  await tabTo(page, "plots-tab");
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("problems-tab")).toBeFocused();
  await page.keyboard.press("Home"); // the first tab, not the run's start: but neither moves the run
  await page.keyboard.press("ArrowRight");
  await expect(time).toHaveAttribute("data-t", "0.000");

  // a live run: after a click on a tab, Right is still the robot's left stick
  await page.getByTestId("config").selectOption("Drive: full omni");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("phase")).toContainText("opcontrol"); // driver control
  const stick = page.locator(".stick").first();
  await page.getByTestId("problems-tab").click();
  await page.keyboard.down("ArrowRight");
  await expect(stick).toHaveAttribute("title", /LEFT_X 127,/);
  await page.keyboard.up("ArrowRight");
  await expect(stick).toHaveAttribute("title", /LEFT_X 0,/);
  await expect(page.getByTestId("problems-tab")).toBeFocused();
  // reached with Tab, the same key moves along the tabs, and the stick stays at rest
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("problems-tab")).toBeFocused();
  await page.keyboard.down("ArrowRight");
  await expect(page.getByTestId("plots-tab")).toBeFocused();
  await page.waitForTimeout(250);
  await expect(stick).toHaveAttribute("title", /LEFT_X 0,/);
  await page.keyboard.up("ArrowRight");
});

test("a folder with nothing in it: where to start", async ({ page }) => {
  await page.goto(`${NEW_URL}/?token=${TOKEN}`); // (start.spec.ts fills it, after this file's tests)
  await expect(page.getByTestId("field")).toBeVisible();
  await expect(page.getByTestId("first-run")).toBeVisible();
  await audit(page, "an empty folder");
});

test.describe("in a narrow window", () => {
  test.use({ viewport: { width: 1024, height: 700 } });
  test("the list over the page", async ({ page }) => {
    await page.getByTestId("sidebar-toggle").click();
    await expect(page.getByTestId("workspace")).toBeVisible();
    await audit(page, "narrow, the workspace list open");
  });
});
