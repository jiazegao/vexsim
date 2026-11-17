import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

// Phase 15.2: the Simulate page is built around the field, so the field gets the window: on a
// laptop's short one the run bar folds to a line and the bottom panel to its tabs, and in a
// narrow one the workspace list and the readout open over the page. And an idle page draws
// nothing.

const RUN = "Tour (Python)";
type Box = { x: number; y: number; width: number; height: number };

const box = async (page: Page, testid: string): Promise<Box> => (await page.getByTestId(testid).first().boundingBox())!;
const draws = async (page: Page) => Number(await page.getByTestId("field").getAttribute("data-draws"));
const apart = (a: Box, b: Box) => a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;
/** How far the page's content runs past the window: nothing may. */
const spill = (page: Page) => page.evaluate(() => [document.documentElement.scrollWidth - innerWidth, document.documentElement.scrollHeight - innerHeight]);

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

/** Run the tour as fast as it goes, to its end. */
async function runToTheEnd(page: Page) {
  await page.getByTestId("config").selectOption(RUN);
  await page.locator(".controls .speed select").selectOption("0");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Finished", { timeout: 60_000 });
  await expect(page.getByTestId("timeline")).toBeVisible();
}

test.describe("on a laptop (1366 x 768)", () => {
  test.use({ viewport: { width: 1366, height: 768 } });

  test("the field gets the window: the run bar folds to a line, the bottom panel to its tabs", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);
    await expect(page.getByTestId("field")).toBeVisible();
    // nothing on show yet: the run bar is whole, to set a run up with
    await expect(page.getByTestId("config")).toBeVisible();
    await expect(page.getByTestId("runbar-folded")).toHaveCount(0);

    await runToTheEnd(page);
    await expect(page.getByTestId("runbar-folded")).toContainText(RUN);
    await expect(page.getByTestId("config")).toHaveCount(0);
    await expect(page.getByTestId("bottom-panel").locator(".lines")).toHaveCount(0); // folded to its tabs
    const field = await box(page, "field");
    expect(field.height).toBeGreaterThanOrEqual(450); // after a run, its timeline below (250 before)
    expect(field.width).toBeGreaterThanOrEqual(500);
    expect(await spill(page)).toEqual([0, 0]);
    const timeline = await box(page, "timeline");
    expect(timeline.height).toBeLessThan(60); // one row
    expect(timeline.y + timeline.height).toBeLessThanOrEqual(768);

    // Edit unfolds the bar; Run folds it again
    await page.getByTestId("runbar-edit").click();
    await expect(page.getByTestId("config")).toHaveValue(RUN);
    await page.getByTestId("runbar-fold").click();
    await expect(page.getByTestId("runbar-folded")).toBeVisible();
    await page.getByTestId("runbar-edit").click();
    await page.getByTestId("run").click();
    await expect(page.getByTestId("runbar-folded")).toBeVisible();
    await expect(page.getByTestId("status")).toHaveText("Finished", { timeout: 60_000 });
    expect((await box(page, "field")).height).toBeGreaterThanOrEqual(450);

    // a tab opens the bottom panel; Hide folds it; the choice is kept
    await page.getByTestId("plots-tab").click();
    await expect(page.getByTestId("plot-pose-error")).toBeVisible();
    await page.getByTestId("bottom-toggle").click();
    await expect(page.getByTestId("plot-pose-error")).toHaveCount(0);
  });

  test("during a run the field is 500 px or more, and a failed run's output opens by itself", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);
    await page.getByTestId("config").selectOption("1239E: driver");
    await page.getByTestId("run").click();
    await expect(page.getByTestId("status")).toHaveText("Running", { timeout: 120_000 });
    const field = await box(page, "field");
    expect(field.height).toBeGreaterThanOrEqual(500); // 378 before
    expect(field.width).toBeGreaterThanOrEqual(500);
    await page.getByTestId("stop").click();

    await page.getByTestId("runbar-edit").click();
    await page.getByLabel("Start x (in)").fill("left");
    await page.getByTestId("run").click();
    await expect(page.getByTestId("problem")).toContainText("Can't run"); // shown though the panel is folded
  });

  test("the key is a pop-up that starts closed, and stays as it was left", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);
    const key = page.getByTestId("key-toggle");
    await expect(key).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText("Where it went")).toHaveCount(0);
    expect(apart(await box(page, "key-toggle"), (await page.locator(".fieldtools").boundingBox())!)).toBe(true);
    await key.click();
    await expect(page.getByText("Where it went")).toBeVisible();
    await page.getByTitle("Show distance sensor beams (3)").getByRole("checkbox").uncheck();
    await page.reload();
    await expect(page.getByTestId("key-toggle")).toHaveAttribute("aria-expanded", "true"); // kept
    await page.getByTestId("key-toggle").click();
    await expect(page.getByText("Where it went")).toHaveCount(0);
  });

  test("an idle page draws nothing; a run draws; a finished one, shown, draws nothing", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);
    await expect(page.getByTestId("field")).toBeVisible();
    await page.getByTestId("config").selectOption(RUN);
    await page.waitForTimeout(500); // the preview arrives, the field fits
    const idle = await draws(page);
    await page.waitForTimeout(1000);
    expect(await draws(page)).toBe(idle);

    // moving the view draws; then it rests again
    await page.getByTestId("field").hover();
    await page.mouse.wheel(0, -200);
    await expect.poll(() => draws(page)).toBeGreaterThan(idle);
    await page.waitForTimeout(300);
    const zoomed = await draws(page);
    await page.waitForTimeout(700);
    expect(await draws(page)).toBe(zoomed);

    await runToTheEnd(page);
    await page.waitForTimeout(300);
    const ended = await draws(page);
    expect(ended).toBeGreaterThan(zoomed + 20); // the run was drawn as it went
    await page.waitForTimeout(1000);
    expect(await draws(page)).toBe(ended);
    await page.getByTestId("scrubber").fill("2"); // scrubbing draws, once
    await expect.poll(() => draws(page)).toBeGreaterThan(ended);

    // on another page the field isn't drawn at all
    await page.getByTestId("page-build").click();
    await page.waitForTimeout(200);
    const away = await draws(page);
    await page.waitForTimeout(700);
    expect(await draws(page)).toBe(away);
  });
});

test.describe("in a narrow window (1024 x 700)", () => {
  test.use({ viewport: { width: 1024, height: 700 } });

  test("the list and the readings open over the page, and nothing overlaps or is cut off", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);
    await expect(page.getByTestId("field")).toBeVisible();
    await expect(page.getByTestId("workspace")).toBeHidden(); // folded away: the field has the width
    await expect(page.getByTestId("readout")).toBeHidden();
    expect((await box(page, "field")).width).toBeGreaterThan(900);

    // the list opens over the page; picking from it, or Escape, puts it away
    await page.getByTestId("sidebar-toggle").click();
    await expect(page.getByTestId("workspace")).toBeVisible();
    expect((await box(page, "field")).width).toBeGreaterThan(900); // over the page, not beside it
    await page.getByTestId("item-examples/robots/full_omni_6m.yaml").click();
    await expect(page.getByTestId("workspace")).toBeHidden();
    await expect(page.getByTestId("robot")).toHaveValue("examples/robots/full_omni_6m.yaml");
    await page.getByTestId("sidebar-toggle").click();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("workspace")).toBeHidden();

    await runToTheEnd(page);
    expect(await spill(page)).toEqual([0, 0]);
    const field = await box(page, "field");
    expect(field.height).toBeGreaterThanOrEqual(400); // 250 before, its key over half of it
    const timeline = await box(page, "timeline");
    const controls = (await page.locator(".controls").boundingBox())!;
    const bottom = await box(page, "bottom-panel");
    for (const [above, below] of [
      [controls, field],
      [field, timeline],
      [timeline, bottom],
    ]) {
      expect(above.y + above.height).toBeLessThanOrEqual(below.y); // each under the one before
    }
    expect(bottom.y + bottom.height).toBeLessThanOrEqual(700);
    expect(apart(await box(page, "key-toggle"), (await page.locator(".fieldtools").boundingBox())!)).toBe(true);

    // the readings open over the field's side, and close again
    await page.getByTestId("readout-toggle").click();
    await expect(page.getByTestId("readout")).toBeVisible();
    expect((await box(page, "field")).width).toBe(field.width);
    await page.getByTestId("readout-toggle").click();
    await expect(page.getByTestId("readout")).toBeHidden();
  });
});

test("in a roomy window everything is open, and each panel folds by hand", async ({ page }) => {
  await page.goto(`/?token=${TOKEN}`); // 1280 x 860, as the other tests
  await expect(page.getByTestId("workspace")).toBeVisible();
  await page.getByTestId("config").selectOption(RUN);
  const before = await box(page, "field");
  await page.getByTestId("sidebar-toggle").click();
  await expect(page.getByTestId("workspace")).toBeHidden();
  await page.getByTestId("readout-toggle").click();
  await expect(page.locator(".readout")).toBeHidden();
  await expect.poll(async () => (await box(page, "field")).width).toBeGreaterThan(before.width + 400);
  await page.reload(); // each choice is kept, for windows this size
  await expect(page.getByTestId("field")).toBeVisible();
  await expect(page.getByTestId("workspace")).toBeHidden();
  await page.getByTestId("sidebar-toggle").click();
  await page.getByTestId("readout-toggle").click();
  await expect(page.getByTestId("workspace")).toBeVisible();
  await expect(page.locator(".readout")).toBeVisible();
  // every page's tab is in the one header row
  for (const id of ["simulate", "sweeps", "bench", "calibrate", "analyze", "build"]) {
    expect((await box(page, `page-${id}`)).y).toBeLessThan(40);
  }
});
