import { expect, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

// The pages beside Simulate (phase 11.5): every remaining command has one.

const ROBOT = "examples/robots/full_omni_6m.yaml";
const ROBOT_LOG = "examples/logs/full_omni_routine.csv";
const JOB = 150_000; // ms: a benchmark, a sweep or a fit, on a slow machine

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
  // leave nothing running for the next test to pick up
  for (const job of await (await page.request.get("/api/jobs")).json()) {
    if (job.state === "queued" || job.state === "running") await page.request.delete(`/api/jobs/${job.id}`);
  }
  for (const session of await (await page.request.get("/api/sessions")).json()) {
    if (session.state !== "stopped") await page.request.delete(`/api/sessions/${session.id}`);
  }
});

test("has a page for every command, a tab away", async ({ page }) => {
  for (const [id, heading] of [
    ["sweeps", "Sweeps"],
    ["bench", "Bench"],
    ["calibrate", "Calibrate"],
    ["analyze", "Analyze"],
    ["build", "Build"],
  ]) {
    await page.getByTestId(`page-${id}`).click();
    await expect(page.getByTestId(`${id}-page`).getByRole("heading", { level: 1 })).toHaveText(heading);
  }
  await page.getByTestId("page-simulate").click();
  await expect(page.getByTestId("field")).toBeVisible();
});

test("keeps the 1239E evaluation as a sweep, and runs a sweep to watch one of its trials", async ({ page }) => {
  test.setTimeout(JOB + 60_000);
  await page.getByTestId("page-sweeps").click();
  const pick = page.getByTestId("sweep-pick");
  await pick.selectOption("1239E: localization");
  await expect(page.getByTestId("sweep-count")).toHaveText("9 runs × 4 variations × 6 seeds = 216 trials");
  await expect(page.getByTestId("vary-key")).toHaveValue("VEXSIM_TRACKING");
  await expect(page.getByTestId("vary-values")).toHaveValue("rcl+mcl, mcl, rcl, odom");

  // a quick one, run without saving it
  await pick.selectOption("");
  await page.getByTestId("sweep-name").fill("Tour, twice");
  await page.getByTestId("sweep-editor").getByLabel("Tour (Python)").check();
  await page.getByTestId("vary-add").click();
  await page.getByTestId("vary-key").fill("TOUR_FLAVOR");
  await page.getByTestId("vary-values").fill("plain, spicy");
  await page.getByTestId("sweep-seeds").fill("1");
  await page.getByTestId("sweep-seconds").fill("4");
  await expect(page.getByTestId("sweep-count")).toHaveText("1 run × 2 variations × 1 seed = 2 trials");
  await page.getByTestId("sweep-run").click();

  const result = page.getByTestId("sweep-result");
  await expect(result.getByRole("link", { name: "trials.csv" })).toBeVisible({ timeout: JOB });
  const row = page.getByTestId("sweep-table").locator("tbody tr");
  await expect(row).toHaveCount(1);
  await expect(row.locator("td")).toHaveText([/^Tour \(Python\)$/, /\d/, /^\d+\.\d \/ \d+\.\d \/ \d+\.\d/, /^\d+\.\d \/ \d+\.\d \/ \d+\.\d/]);
  await expect(page.getByTestId("sweep-charts").locator(".plot")).toHaveCount(1);
  await expect(page.getByTestId("results").getByTestId("result").first()).toContainText("Tour, twice");

  // a trial runs again on the field, exactly: its seed and where it was put down
  await result.locator("details.trials summary").click();
  const trials = page.getByTestId("sweep-trials").locator("tbody tr");
  await expect(trials).toHaveCount(2);
  await trials.nth(1).getByTestId("watch-trial").click();
  await expect(page.getByTestId("page-simulate")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("status")).toContainText(/Running|Finished/i, { timeout: 30_000 });
  await expect(page.getByTestId("program")).toHaveValue("examples/programs/tour.py");
  expect(Number(await page.getByLabel("Start x (in)").inputValue())).not.toBe(0); // off its start
});

test("benchmarks a scenario, then plays its worst case back on the field", async ({ page }) => {
  test.setTimeout(JOB + 60_000);
  await page.getByTestId("item-examples/scenarios/s_curve.yaml").click(); // from the sidebar
  await expect(page.getByTestId("bench-scenario")).toHaveValue("examples/scenarios/s_curve.yaml");
  const scenario = page.getByTestId("scenario-info");
  await expect(scenario).toContainText("push (0, 25) N for 0.3 s at 1.2 s");
  await scenario.getByLabel("drive encoders + IMU").uncheck();
  await page.getByTestId("bench-seeds").fill("2");
  await expect(scenario).toContainText("4 trials");
  await page.getByTestId("bench-run").click();

  const result = page.getByTestId("bench-result");
  await expect(result).toBeVisible({ timeout: JOB });
  await expect(page.getByTestId("bench-summary").locator("tbody tr")).toHaveText([/tracking wheels \+ IMU \/ pure pursuit/, /tracking wheels \+ IMU \/ RAMSETE/]);
  await expect(page.getByTestId("bench-charts").locator(".plot").first()).toBeVisible();
  await expect(result.locator(".command code")).toHaveText('vexsim bench examples/scenarios/s_curve.yaml --seeds 2 --localizers "tracking wheels + IMU"');

  await page.getByTestId("watch-worst").first().click();
  await expect(page.getByTestId("timeline")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("timeline")).toContainText("S-curve under a mid-path shove: the worst of tracking wheels + IMU / pure pursuit");
});

test("calibrates the simulated robot with a robot log, into its config", async ({ page }) => {
  test.setTimeout(JOB + 60_000);
  await page.getByTestId(`item-${ROBOT_LOG}`).click(); // a robot log: to the Calibrate page
  await expect(page.getByTestId("calibrate-log")).toHaveValue(ROBOT_LOG);
  await page.getByTestId("calibrate-robot").selectOption(ROBOT);
  await expect(page.getByTestId("routine-files").locator("li")).toHaveCount(4); // the routine and vexsim's logger
  const fit = page.getByTestId("fit");
  await fit.getByLabel(/longitudinal_mu/).uncheck();
  await fit.getByLabel(/rolling_resistance/).uncheck();
  await fit.getByLabel("Iterations, at most").fill("2");
  await page.getByTestId("calibrate-run").click();

  const result = page.getByTestId("calibration-result");
  await expect(result).toBeVisible({ timeout: JOB });
  await expect(page.getByTestId("fitted")).toContainText("wheel.omni.lateral_mu");
  await expect(page.getByTestId("rms").locator("tbody tr")).toHaveCount(4);
  await expect(page.getByTestId("calibration-charts").locator(".plot")).not.toHaveCount(0);

  // the fitted values go into the robot's config, for you to look over and save
  await page.getByTestId("apply-overrides").click();
  await expect(page.getByTestId("config-notice")).toContainText("Added 2 fitted values under overrides");
  await expect(page.getByTestId(`page-${ROBOT}`)).toContainText("●"); // unsaved
  await expect(page.getByTestId("config-state")).toContainText("unsaved changes");
  await page.getByRole("button", { name: `Close ${ROBOT}` }).click();
  await page.getByRole("button", { name: "Don't save" }).click();
  await expect(page.getByTestId(`page-${ROBOT}`)).toHaveCount(0);
});

test("analyzes a motor, a robot's drift and its odometry", async ({ page }) => {
  await page.getByTestId("page-analyze").click();
  await expect(page.getByTestId("motor-charts").locator(".plot")).toHaveCount(3); // shown on arrival
  await page.getByTestId("cartridge").selectOption("blue");
  await page.getByTestId("run-motors").click();
  await expect(page.getByTestId("analyze-page")).toContainText("A blue cartridge at 12.8 V");

  await page.getByTestId("tool-drift").click();
  await page.getByTestId("analyze-robot").first().selectOption(ROBOT);
  await page.getByTestId("run-drift").click();
  await expect(page.getByTestId("drift-table").locator("tbody tr")).toHaveCount(3);
  await expect(page.getByTestId("drift-chart")).toBeVisible();

  await page.getByTestId("tool-odometry").click();
  await page.getByTestId("run-odometry").click();
  await expect(page.getByTestId("odometry-table").locator("tbody tr")).toContainText(["tracking wheels + IMU"]);
  await expect(page.getByTestId("chart-position-error")).toBeVisible();
});

test("builds a PROS project and checks the compiler", async ({ page }) => {
  test.setTimeout(JOB);
  await page.getByTestId("page-build").click();
  await page.getByTestId("build-examples/pros_projects/minimal_pros4").click();
  await expect(page.getByTestId("build-result")).toBeVisible({ timeout: 120_000 });
  await page.getByTestId("doctor").click();
  await expect(page.getByTestId("doctor-lines").locator("li.ok")).toHaveCount(3, { timeout: 120_000 });
});
