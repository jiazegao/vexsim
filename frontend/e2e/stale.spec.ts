import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import type { Page, TestInfo } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

// Phase 15.3: nothing stale. Restart runs the code as it is now; a run says when its files
// have changed, and runs again on a save if asked to; the workspace list follows the disk; and
// the address keeps your place over a reload, with Back and Forward stepping between pages.

const ROBOT = "examples/robots/full_omni_6m.yaml";
const WORKSPACE = resolve(import.meta.dirname, "../.."); // what the test server opened

/** A program that says which edition of itself it is, then waits. */
const edition = (word: string) => `from vexsim.api import delay\n\n\ndef autonomous(bot):\n    print("edition ${word}")\n    while True:\n        yield delay(100)\n`;

/** A file of the test's own, inside the workspace (cleaned each run): where it is, and its
 * workspace path. */
function ownFile(testInfo: TestInfo, name: string): [string, string] {
  const file = testInfo.outputPath(name);
  mkdirSync(dirname(file), { recursive: true });
  return [file, relative(WORKSPACE, file).split("\\").join("/")];
}

/** The window gets the focus back (from an editor, say). */
const focus = (page: Page) => page.evaluate(() => void window.dispatchEvent(new Event("focus")));
const hash = (page: Page) => new URL(page.url()).hash;

let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  page.on("pageerror", (error) => problems.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
});

test.afterEach(async ({ page }) => {
  expect(problems).toEqual([]);
  for (const session of await (await page.request.get("/api/sessions")).json()) {
    if (session.state !== "stopped") await page.request.delete(`/api/sessions/${session.id}`);
  }
});

/** Run the test's program on the example robot. */
async function runIt(page: Page, path: string) {
  await page.goto(`/?token=${TOKEN}`);
  await page.getByTestId("robot").selectOption(ROBOT);
  await page.getByTestId("field-select").selectOption("");
  await page.getByTestId("program").selectOption(path);
  await page.getByTestId("run").click();
}

test("Restart runs the program as it is now, and the run says when its code has changed", async ({ page }, testInfo) => {
  const [file, path] = ownFile(testInfo, "edited.py");
  writeFileSync(file, edition("one"));
  await runIt(page, path);
  const output = page.getByTestId("console");
  const changed = page.getByTestId("code-changed");
  await expect(output).toContainText("edition one");
  await expect(page.getByTestId("status")).toHaveText("Running");

  // nothing changed: the same run starts again at once
  await expect.poll(async () => Number(await page.getByTestId("sim-time").getAttribute("data-t"))).toBeGreaterThan(1);
  await page.getByTestId("restart").click();
  await expect.poll(async () => Number(await page.getByTestId("sim-time").getAttribute("data-t"))).toBeLessThan(1);
  await expect(output).toContainText("edition one");
  await expect(changed).toHaveCount(0);

  // the program edited: the run says so, and what's on the field is still the old code
  writeFileSync(file, edition("two"));
  await expect(changed).toBeVisible();
  expect(await changed.getAttribute("title")).toContain(`${path} changed since this run started`);
  await expect(output).not.toContainText("edition two");
  await page.getByTestId("restart").click();
  await expect(output).toContainText("edition two");
  await expect(changed).toHaveCount(0);
  await expect(page.getByTestId("status")).toHaveText("Running");

  // a stopped run starts again too (R, with the field's keys), and "code changed" is a way to
  writeFileSync(file, edition("three"));
  await expect(changed).toBeVisible();
  await page.getByTestId("stop").click();
  await expect(page.getByTestId("status")).toHaveText("Stopped");
  await changed.click();
  await expect(output).toContainText("edition three");
});

test("with Run on save, a save runs it again; one that breaks it is mended by the next", async ({ page }, testInfo) => {
  const [file, path] = ownFile(testInfo, "saved.py");
  writeFileSync(file, edition("one"));
  await runIt(page, path);
  const output = page.getByTestId("console");
  await expect(output).toContainText("edition one");
  await page.getByTestId("run-on-save").check();

  writeFileSync(file, edition("two"));
  await expect(output).toContainText("edition two", { timeout: 6000 }); // "within about 5 s"
  await expect(page.getByTestId("code-changed")).toHaveCount(0);

  writeFileSync(file, "def autonomous(bot)\n    yield\n"); // no colon
  await expect(page.getByTestId("status")).toHaveText("Error", { timeout: 6000 });
  await expect(page.getByTestId("problems")).toContainText("SyntaxError");
  writeFileSync(file, edition("three"));
  await expect(output).toContainText("edition three", { timeout: 6000 });
  await expect(page.getByTestId("status")).toHaveText("Running");

  // the switch is kept; off, a save only says so
  await page.reload();
  await expect(page.getByTestId("run-on-save")).toBeChecked();
  await expect(page.getByTestId("status")).toHaveText("Running"); // the run it came back to
  await page.getByTestId("run-on-save").uncheck();
  writeFileSync(file, edition("four"));
  await expect(page.getByTestId("code-changed")).toBeVisible();
  await expect(page.getByTestId("console")).not.toContainText("edition four");
});

test("the workspace list follows the disk when the window gets the focus back", async ({ page }, testInfo) => {
  const [file, path] = ownFile(testInfo, "made_elsewhere.py");
  await page.goto(`/?token=${TOKEN}`);
  await expect(page.getByTestId("workspace")).toBeVisible();
  const item = page.getByTestId(`item-${path}`);
  await expect(page.getByTestId(`item-${ROBOT}`)).toBeVisible();
  await expect(item).toHaveCount(0);

  writeFileSync(file, edition("one")); // made in an editor
  await focus(page);
  await expect(item).toBeVisible(); // no Refresh
  await expect(page.getByTestId("program").locator(`option[value="${path}"]`)).toHaveCount(1); // and to pick in the run bar

  // a folder that's as it was isn't read again: the server says so from its stamp
  const asked = async () => {
    const [response] = await Promise.all([page.waitForResponse((r) => r.url().includes("/api/workspace")), focus(page)]);
    return (await response.json()) as { unchanged?: boolean; stamp: string; items?: unknown[] };
  };
  await page.waitForTimeout(2500); // the new file's stamp stands for it now
  const listed = await asked();
  expect(listed.items?.length).toBeGreaterThan(10);
  expect(listed.stamp).not.toBe("");
  await page.waitForTimeout(1100); // a look a second, at most
  expect(await asked()).toEqual({ unchanged: true, stamp: listed.stamp });

  rmSync(file);
  await page.waitForTimeout(1100);
  await focus(page);
  await expect(item).toHaveCount(0);
});

test("the address keeps your place: over a reload, and Back and Forward", async ({ page }) => {
  const selected = (testid: string) => expect(page.getByTestId(testid)).toHaveAttribute("aria-selected", "true");
  const current = (testid: string) => expect(page.getByTestId(testid)).toHaveAttribute("aria-current", "page"); // an open file's button
  await page.goto(`/?token=${TOKEN}`);
  await expect(page.getByTestId("field")).toBeVisible();
  await expect.poll(() => page.url()).not.toContain("token"); // the key isn't left in the address
  expect(hash(page)).toBe(""); // the Simulate page: no # at all

  await page.getByTestId("page-calibrate").click();
  await expect.poll(() => hash(page)).toBe("#/calibrate/session");
  await page.getByTestId("calibrate-tab-check").click();
  await expect.poll(() => hash(page)).toBe("#/calibrate/check");
  await page.reload();
  await selected("page-calibrate");
  await selected("calibrate-tab-check");
  expect(hash(page)).toBe("#/calibrate/check");

  // Back and Forward step between the pages (and Calibrate's tabs)
  await page.goBack();
  await selected("calibrate-tab-session");
  await page.goBack();
  await selected("page-simulate");
  await expect(page.getByTestId("field")).toBeVisible();
  await page.goForward();
  await selected("page-calibrate");
  await selected("calibrate-tab-session");

  // a config open in its editor
  await page.getByTestId(`item-${ROBOT}`).click({ button: "right" });
  await page.getByTestId(`edit-${ROBOT}`).click();
  await expect.poll(() => hash(page)).toBe(`#/edit?file=${ROBOT}`);
  await page.reload();
  await expect(page.locator('[data-testid="config-editor"]:not([hidden])')).toHaveAttribute("data-path", ROBOT);
  await current(`page-${ROBOT}`);
  await page.goBack();
  await selected("page-calibrate");
  await page.goForward();
  await current(`page-${ROBOT}`);

  // an address typed, or from a bookmark; one that names nothing is the Simulate page
  await page.goto("/#/build");
  await expect(page.getByTestId("build-page")).toBeVisible();
  await selected("page-build");
  await page.goto("/#/nowhere");
  await selected("page-simulate");
  await expect.poll(() => hash(page)).toBe("");
  await page.goto("/#/edit?file=examples/robots/gone.yaml"); // a file that isn't there
  await expect.poll(() => hash(page)).toBe("");
  await selected("page-simulate");
});

test("a reload comes back to the run on show", async ({ page }) => {
  await page.goto(`/?token=${TOKEN}`);
  await page.getByTestId("config").selectOption("Tour (Python)");
  await page.locator(".controls .speed select").selectOption("0");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Finished", { timeout: 60_000 });
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expect.poll(() => hash(page)).toMatch(/^#\/simulate\?run=[\w-]+$/);
  const run = hash(page);

  await page.reload();
  await expect(page.getByTestId("timeline")).toBeVisible(); // its recording, to scrub
  await expect(page.getByTestId("shown-run")).toContainText("Tour (Python)");
  await expect(page.getByTestId("config")).toHaveValue("Tour (Python)"); // and the run form as it was left
  await expect(page.getByTestId("status")).toHaveText("Finished"); // and its session, to restart
  await expect(page.getByTestId("console")).toContainText("autonomous done");
  expect(hash(page)).toBe(run);
  await page.getByTestId("scrubber").fill("3");
  await expect(page.getByTestId("playhead-time")).toHaveAttribute("data-t", "3.000");

  // another page and back: the run is still the address's; put away, it's out of it
  await page.getByTestId("page-sweeps").click();
  await expect.poll(() => hash(page)).toBe("#/sweeps");
  await page.goBack();
  await expect(page.getByTestId("timeline")).toBeVisible();
  expect(hash(page)).toBe(run);
  await page.getByTestId("close-run").click();
  await expect.poll(() => hash(page)).toBe("");
});
