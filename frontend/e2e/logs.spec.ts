import { expect, type Page, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

// Phase 11.6: what robot code draws on the field, and a robot's MCL log beside its replay.

const LOG = "examples/logs/left40_simulated.1239e";
const REPLAY = "Replay an MCL log (Python tank drive)";

let problems: string[] = []; // the page's errors, which fail the test

test.beforeEach(async ({ page }) => {
  problems = [];
  page.on("pageerror", (error) => problems.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  await page.goto(`/?token=${TOKEN}`);
});

test.afterEach(async ({ page }) => {
  expect(problems).toEqual([]);
  for (const session of await (await page.request.get("/api/sessions")).json()) {
    if (session.state !== "stopped") await page.request.delete(`/api/sessions/${session.id}`);
  }
});

async function drawn(page: Page, canvas = "field"): Promise<number> {
  return Number(await page.getByTestId(canvas).getAttribute("data-drawn"));
}

test("draws what the robot code draws, live and recorded, a layer at a time", async ({ page }) => {
  test.setTimeout(90_000);
  await page.getByTestId("config").selectOption("Tour (Python)");
  await page.locator(".controls .speed select").selectOption("0"); // as fast as it goes
  await page.getByTestId("run").click();
  await expect(page.getByTestId("shown-run")).toHaveText("Tour (Python)", { timeout: 60_000 });
  // the tour numbers its five stops: a dot and a number each
  await expect.poll(() => drawn(page)).toBe(10);
  const layer = page.getByTestId("drawn-layer");
  await expect(layer).toHaveText("stops");
  await layer.getByRole("checkbox").uncheck();
  await expect.poll(() => drawn(page)).toBe(0);
  await layer.getByRole("checkbox").check();
  await expect.poll(() => drawn(page)).toBe(10);
  await page.getByTestId("field").focus();
  await page.keyboard.press("5"); // all of it
  await expect.poll(() => drawn(page)).toBe(0);
  await expect(layer).toHaveCount(0);
  await page.keyboard.press("5");
  await expect.poll(() => drawn(page)).toBe(10);
  await page.getByTestId("scrubber").fill("0.5"); // before it drew anything
  await expect.poll(() => drawn(page)).toBe(0);
});

test("plays a robot's MCL log, then beside its replay on one timeline", async ({ page }) => {
  test.setTimeout(120_000);
  await page.getByTestId(`item-${LOG}`).click();
  const bar = page.getByTestId("logbar");
  await expect(bar).toContainText("502 updates over 15.0 s");
  // alone, it has its own timeline
  const log = page.getByTestId("log-field");
  await expect(page.getByTestId("scrubber")).toHaveAttribute("max", "15.03");
  await page.getByTestId("scrubber").fill("5");
  await expect(log).toHaveAttribute("data-time", "5.000");
  await expect.poll(() => drawn(page, "log-field")).toBeGreaterThan(5); // rays, a particle, the spread
  await expect(page.getByTestId(`item-${LOG}`)).toHaveAttribute("aria-pressed", "true");

  // replay it: a virtual driver drives the robot along its path, live, then recorded
  await page.getByTestId("replay-with").selectOption(REPLAY);
  await page.locator(".controls .speed select").selectOption("0");
  await page.getByTestId("replay-log").click();
  await expect(page.getByTestId("shown-run")).toHaveText(`${REPLAY} · left40_simulated.1239e`, { timeout: 90_000 });
  await expect(page.getByTestId("config")).toHaveValue(REPLAY);
  await expect(page.getByTestId("follow")).toHaveValue(LOG);

  // the log starts when the replay began following it, and plays along with it
  const runs = await (await page.request.get("/api/runs")).json();
  const replay = runs[0];
  expect(replay.spec.follow).toEqual({ log: LOG, sticks: "tank", curve: null });
  expect(replay.follow_start).toBeGreaterThanOrEqual(0);
  expect(Number(await page.getByTestId("log-start").inputValue())).toBeCloseTo(replay.follow_start, 2);
  const at = replay.follow_start + 4;
  await page.getByTestId("scrubber").fill(String(at));
  await expect(page.getByTestId("field")).toHaveAttribute("data-time", at.toFixed(3));
  await expect.poll(async () => Number(await log.getAttribute("data-time"))).toBeCloseTo(4, 2);
  // nudged later, it's earlier in the log at the same moment
  await page.getByTestId("log-start").fill(String(replay.follow_start + 1));
  await expect.poll(async () => Number(await log.getAttribute("data-time"))).toBeCloseTo(3, 2);

  await page.getByTestId("close-log").click();
  await expect(bar).toHaveCount(0);
  await expect(log).toHaveCount(0);
});
