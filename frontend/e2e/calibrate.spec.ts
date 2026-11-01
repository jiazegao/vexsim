import { rmSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

// Phase 14.7: a whole calibration session in the app (planned, practiced in vexsim, fitted,
// applied), and a routine's robot log played beside its routine, then checked against it.

const ROBOT = "examples/robots/1239e_2026-27.yaml";
const FIELD = "examples/fields/1239e_2026-27.yaml";
const PROJECT = "examples/pros_projects/1239e_2026-27";
const HERE = "calibration-e2e"; // in the repository, made by the tests and taken away after
const MINUTE = 60_000;

let problems: string[] = []; // the page's errors, which fail the test

test.beforeAll(() => rmSync(join("..", HERE), { recursive: true, force: true }));
test.afterAll(() => rmSync(join("..", HERE), { recursive: true, force: true }));

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
  for (const job of await (await page.request.get("/api/jobs")).json()) {
    if (job.state === "queued" || job.state === "running") await page.request.delete(`/api/jobs/${job.id}`);
  }
  for (const session of await (await page.request.get("/api/sessions")).json()) {
    if (session.state !== "stopped") await page.request.delete(`/api/sessions/${session.id}`);
  }
});

test("runs a whole calibration session in the app: planned, practiced, fitted and applied", async ({ page }) => {
  test.setTimeout(20 * MINUTE);
  await page.getByTestId("page-calibrate").click();
  await page.getByTestId("session-robot").selectOption(ROBOT);
  await page.getByTestId("session-field").selectOption(FIELD);

  // the plan, and its program for the robot
  await page.getByTestId("program-folder").fill(`${HERE}/vexsim_calibration`);
  await page.getByTestId("program-write").click();
  const tests = page.getByTestId("plan-tests").locator("tbody tr");
  await expect(tests).toHaveCount(10, { timeout: 5 * MINUTE });
  await expect(page.getByTestId("plan-tests").locator("img.map-thumb")).toHaveCount(6);
  await expect(page.getByTestId("not-pros")).toContainText(`pros c n ${HERE}/vexsim_calibration`);
  await expect(page.getByTestId("program-steps")).toContainText("pros upload --slot 8");

  // practiced in vexsim: the simulated student runs five of the tests
  const practice = page.getByTestId("practice");
  await practice.locator("summary").click();
  for (const test of [/IMU, still/, /IMU, 10 turns/, /Arc/, /Distance sweep 1/, /Distance sweep 2/]) await practice.getByLabel(test).uncheck();
  await page.getByTestId("practice-path").fill(`${HERE}/practice`);
  await page.getByTestId("practice-run").click();
  const runs = page.getByTestId("session-run");
  await expect(runs).toHaveCount(10, { timeout: 8 * MINUTE });
  await expect(page.getByTestId("session-path")).toHaveValue(`${HERE}/practice`);
  await expect(page.getByTestId("session-runs")).toContainText("practice");
  await expect(runs.first()).toContainText("passed: every device answers");
  await expect(page.getByTestId(`item-${HERE}/practice`)).toBeVisible(); // a session, in the workspace

  // fitted: the held-out run matches, and what Apply writes
  await page.getByTestId("session-fit-run").click();
  await expect(page.getByTestId("held-out")).toContainText("matches within the sensors' noise", { timeout: 8 * MINUTE });
  await expect(page.getByTestId("session-changes")).toContainText("diameter_in");
  await expect(page.getByTestId("session-plots").locator("img")).not.toHaveCount(0);

  // applied: written into the robot's config, for you to look over and save
  await page.getByTestId("session-apply").click();
  await expect(page.getByTestId("config-notice")).toContainText(`Wrote what ${HERE}/practice found in`);
  await expect(page.getByTestId("config-state")).toContainText("unsaved changes");
  await page.getByRole("button", { name: `Close ${ROBOT}` }).click();
  await page.getByRole("button", { name: "Don't save" }).click();

  // a run of the session, played on the field from its spot
  await page.getByTestId("page-calibrate").click();
  await page.getByTestId("session-runs").getByRole("button", { name: "Play" }).first().click();
  await expect(page.getByTestId("logbar")).toContainText("its pose by odometry, from its spot");
  await expect(page.getByTestId("log-field")).toBeVisible();
  await page.getByTestId("scrubber").fill("2");
  await expect.poll(async () => Number(await page.getByTestId("log-field").getAttribute("data-drawn"))).toBeGreaterThan(2); // its rays
});

test("plays a routine's robot log beside its routine, and checks the routine against it", async ({ page }) => {
  test.setTimeout(15 * MINUTE);
  // a log of Left 40, as the robot's card would have it: the routine run in vexsim, logging
  const started = await page.request.post("/api/sessions", {
    data: { spec: { robot: ROBOT, program: PROJECT, routine: "left40", field: FIELD, mode: "autonomous", start: [60, 0, 0], sd: `${HERE}/card` } },
  });
  expect(started.ok()).toBe(true);
  const { id } = await started.json();
  await expect.poll(async () => (await (await page.request.get(`/api/sessions/${id}`)).json()).state, { timeout: 8 * MINUTE }).toBe("finished");
  const log = `${HERE}/card/vexsim_0001_left_40.csv`;
  await page.getByTestId("refresh").click();

  // on the field, the code's pose and rays: and beside it, its routine run in vexsim
  await page.getByTestId("program").selectOption(PROJECT);
  await page.getByTestId(`item-${log}`).click();
  const bar = page.getByTestId("logbar");
  await expect(bar).toContainText("its code's lemlib pose");
  await expect(page.getByTestId("replay-log")).toBeVisible();
  await page.locator(".controls .speed select").selectOption("0");
  await page.getByTestId("run-log-routine").click();
  await expect(page.getByTestId("shown-run")).toContainText("left40", { timeout: 5 * MINUTE });
  await expect(page.getByTestId("log-field")).toBeVisible();
  await page.getByTestId("scrubber").fill("5");
  await expect.poll(async () => Number(await page.getByTestId("log-field").getAttribute("data-drawn"))).toBeGreaterThan(4);

  // checked: its end measured with tape at two corners
  await page.getByTestId("page-calibrate").click();
  await page.getByTestId("calibrate-tab-check").click();
  await page.getByTestId("check-robot").selectOption(ROBOT);
  await page.getByTestId("check-field").selectOption(FIELD);
  await page.getByTestId("check-program").selectOption(PROJECT);
  const runs = page.getByTestId("check-runs");
  await runs.getByText(log).click();
  await page.getByTestId("check-end").fill("front-left: 27.25 from +x, 56.5 from +y; back-right: 19.75 from +x, 39.25 from +y");
  await expect(page.getByTestId("check-end-found")).toContainText("It ended at");
  await page.getByTestId("check-run").click();
  await expect(page.getByTestId("check-verdict")).toContainText(/(Passed|Failed): the simulated left40/, { timeout: 5 * MINUTE });
  await expect(page.getByTestId("check-table").locator("tbody tr")).toHaveCount(1);
  await expect(page.getByTestId("check-result").locator(".report-plots img")).toHaveCount(3);
});
