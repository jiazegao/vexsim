import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

const ROBOT = "examples/robots/full_omni_6m.yaml";
const FIELD = "examples/fields/practice_elements.yaml";
const PROGRAM = "examples/programs/tour.py";
const WORKSPACE = resolve(import.meta.dirname, "../.."); // what the test server opened

/** The simulated time the page shows, in seconds. */
async function simTime(page: Page): Promise<number> {
  return Number((await page.getByTestId("sim-time").getAttribute("data-t")) ?? 0);
}

/** Where the robot really is: x, y (in), heading (deg). */
async function truePose(page: Page): Promise<[number, number, number]> {
  const pose = page.getByTestId("true-pose");
  const read = async (name: string) => Number(await pose.getAttribute(`data-${name}`));
  return [await read("x"), await read("y"), await read("heading")];
}

/** A point on the field (inches) as a point on the page; or on another canvas with the
 * same view (a config editor's diagram). */
async function onPage(page: Page, x: number, y: number, canvas = "field"): Promise<[number, number]> {
  const field = page.getByTestId(canvas);
  const box = (await field.boundingBox())!;
  const [scale, cx, cy] = ((await field.getAttribute("data-view")) ?? "1,0,0").split(",").map(Number);
  return [box.x + box.width / 2 + (x - cx) * scale, box.y + box.height / 2 - (y - cy) * scale];
}

async function drag(page: Page, from: [number, number], to: [number, number]): Promise<void> {
  await page.mouse.move(...(await onPage(page, ...from)));
  await page.mouse.down();
  const end = await onPage(page, ...to);
  await page.mouse.move(end[0], end[1], { steps: 8 });
  await page.mouse.up();
}

async function startValue(page: Page, which: "x" | "y" | "heading"): Promise<number> {
  const label = { x: "Start x (in)", y: "Start y (in)", heading: "Start heading (degrees)" }[which];
  return Number(await page.getByLabel(label).inputValue());
}

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
  // leave no run behind: the next page would reconnect to it
  for (const session of await (await page.request.get("/api/sessions")).json()) {
    if (session.state !== "stopped") await page.request.delete(`/api/sessions/${session.id}`);
  }
});

test("the token leaves the address bar once the server has set its cookie", async ({ page }) => {
  await expect(page.getByTestId(`item-${ROBOT}`)).toBeVisible();
  expect(new URL(page.url()).searchParams.has("token")).toBe(false);
  await page.reload(); // the cookie is enough from now on
  await expect(page.getByTestId(`item-${ROBOT}`)).toBeVisible();
});

test("runs a program from the workspace and controls the run", async ({ page }) => {
  const workspace = page.getByTestId("workspace");
  await expect(workspace.getByTestId(`item-${PROGRAM}`)).toBeVisible();
  await workspace.getByTestId(`item-${ROBOT}`).click();
  await workspace.getByTestId(`item-${PROGRAM}`).click();
  await expect(page.getByTestId("robot")).toHaveValue(ROBOT);
  await expect(page.getByTestId("program")).toHaveValue(PROGRAM);
  await page.getByTestId("run").click();

  await expect(page.getByTestId("status")).toHaveText("Running");
  await expect.poll(() => simTime(page)).toBeGreaterThan(1);
  const frames = Number(await page.getByTestId("field").getAttribute("data-frames"));
  expect(frames).toBeGreaterThan(30); // streamed, not just the last frame
  await expect(page.getByTestId("command")).toHaveAttribute("data-command", `vexsim run ${ROBOT} --program ${PROGRAM}`);
  await expect(page.getByTestId("console")).toContainText("autonomous start");

  // Run moved the focus to the field, so Space pauses instead of pressing Run again
  await page.keyboard.press("Space");
  await expect(page.getByTestId("status")).toHaveText("Paused");
  await page.waitForTimeout(300); // any frame already on its way
  const paused = await simTime(page);
  await page.waitForTimeout(500);
  expect(await simTime(page)).toBe(paused);
  await page.getByTestId("pause").click(); // the same button now resumes
  await expect(page.getByTestId("status")).toHaveText("Running");
  await expect.poll(() => simTime(page)).toBeGreaterThan(paused);

  await page.getByTestId("stop").click();
  await expect(page.getByTestId("status")).toHaveText("Stopped");
});

test("says why a run can't start", async ({ page }) => {
  await expect(page.getByTestId(`item-${ROBOT}`)).toBeVisible();
  await page.getByLabel("Start x (in)").fill("left");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("problem")).toContainText("Start x must be a number");
});

test("fills the run in from a saved run: start, routine and environment too", async ({ page }) => {
  await page.getByTestId("config").selectOption("1239E: Left 40");
  await expect(page.getByTestId("robot")).toHaveValue("examples/robots/1239e_2026-27.yaml");
  await expect(page.getByTestId("program")).toHaveValue("examples/pros_projects/1239e_2026-27");
  await expect(page.getByTestId("routine")).toHaveValue("left40");
  expect(await startValue(page, "x")).toBe(60);
  await expect(page.locator(".changed")).toHaveCount(0);
  await page.getByLabel("Seed").fill("3");
  await expect(page.locator(".changed")).toHaveCount(1); // no longer the saved run as it is
  await page.getByTestId("config").selectOption("1239E: replay an MCL log");
  await page.locator("summary", { hasText: "More" }).click();
  await expect(page.getByPlaceholder("VEXSIM_AUTON=Left 40")).toHaveValue("VEXSIM_AUTON=startMcl\nVEXSIM_BRAKE=hold");
});

test("runs the routine picked inside the project's autonomous(), from where it starts", async ({ page }) => {
  test.setTimeout(150_000); // the first PROS build here compiles vexsim's runtime too
  await page.getByTestId("robot").selectOption(ROBOT);
  await page.getByTestId("program").selectOption("tests/cpp/routine_test");
  const routine = page.getByTestId("routine");
  await expect(routine.locator("option")).toHaveText(["As the project picks", "alpha", "beta", "extra::gamma", "delta", "ghost (not found)"]);
  await expect(routine.locator("option", { hasText: "ghost" })).toHaveAttribute("disabled", "");
  await routine.selectOption("beta"); // its setPose(12, -36, 180): x, y and heading -90
  expect([await startValue(page, "x"), await startValue(page, "y"), await startValue(page, "heading")]).toEqual([12, -36, -90]);
  await page.getByTestId("run").click();
  const output = page.getByTestId("console");
  await expect(output).toContainText("vexsim: autonomous() called alpha(); running beta() instead", { timeout: 120_000 });
  await expect(output).toContainText("beta runs");
  await expect(output).toContainText("autonomous done");
  await page.getByTestId("program").selectOption(PROGRAM); // a Python program: no routines
  await expect(routine).toHaveCount(0);
});

test("lists a project's routes; picking one sets its run up", async ({ page }) => {
  const project = "examples/pros_projects/1239e_2026-27";
  const route = `${project}/routes/left_start.yaml`;
  const item = page.getByTestId(`item-${route}`);
  await expect(item).toContainText("Left start");
  await expect(item).toContainText("6 steps, from setPose(60, 0, 90)");
  await item.click(); // its project, robot, field and start
  await expect(page.getByTestId("program")).toHaveValue(project);
  await expect(page.getByTestId("robot")).toHaveValue("examples/robots/1239e_2026-27.yaml");
  await expect(page.getByTestId("field-select")).toHaveValue("examples/fields/1239e_2026-27.yaml");
  const routine = page.getByTestId("routine");
  await expect(routine).toHaveValue(`route:${route}`);
  expect([await startValue(page, "x"), await startValue(page, "y"), await startValue(page, "heading")]).toEqual([60, 0, 0]);
  await expect(item).toHaveClass(/\bselected\b/);
  // the run bar lists it with the project's routines: a routine instead, then the route again
  await expect(routine.locator("optgroup[label='Routes (routes/)'] option")).toHaveText(["Left start"]);
  await routine.selectOption("left40");
  await expect(item).not.toHaveClass(/\bselected\b/);
  await page.getByLabel("Start x (in)").fill("0");
  await routine.selectOption(`route:${route}`);
  expect(await startValue(page, "x")).toBe(60);
});

test("drags the robot to where it starts, and turns it by its handle", async ({ page }) => {
  await page.getByTestId("robot").selectOption(ROBOT);
  await page.getByTestId("field-select").selectOption(FIELD);
  // the default start, the field's center, is on the practice field's barrier
  await expect(page.getByTestId("start-blocked")).toContainText("on top of barrier");
  await expect.poll(() => page.getByTestId("field").getAttribute("data-view")).not.toBe(null);
  await drag(page, [0, 0], [-48.2, -23.9]); // grab the robot's middle and move it clear
  expect([await startValue(page, "x"), await startValue(page, "y")]).toEqual([-48, -24]);
  await expect(page.getByTestId("start-blocked")).toHaveCount(0);
  // the round handle sits just ahead of the front edge (the robot faces +x)
  const scale = Number((await page.getByTestId("field").getAttribute("data-view"))!.split(",")[0]);
  const handle: [number, number] = [-48 + 7.5 + 18 / scale, -24];
  await drag(page, handle, [-48, 0]); // pull it round to face +y
  expect(await startValue(page, "heading")).toBe(90);

  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Running");
  const [x, y, heading] = await truePose(page);
  expect([Math.round(x), Math.round(y), Math.round(heading)]).toEqual([-48, -24, 90]);
});

test("drives the robot with the keyboard", async ({ page }) => {
  await page.getByTestId("config").selectOption("Drive: full omni");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("phase")).toContainText("opcontrol"); // driver control
  const [x0] = await truePose(page);
  await page.keyboard.down("w"); // left stick up: arcade forward
  await expect.poll(async () => (await truePose(page))[0], { timeout: 10_000 }).toBeGreaterThan(x0 + 10);
  await expect(page.locator(".stick").first()).toHaveAttribute("title", /LEFT_Y 127/);
  await page.keyboard.up("w");
  await page.keyboard.down("d"); // right stick right: turn clockwise
  await expect.poll(async () => (await truePose(page))[2], { timeout: 10_000 }).toBeLessThan(-20);
  await page.keyboard.up("d");
});

test("drives the robot with a gamepad", async ({ page }) => {
  await page.addInitScript(() => {
    const pad = {
      id: "Test gamepad (STANDARD GAMEPAD)",
      index: 0,
      connected: true,
      mapping: "standard",
      timestamp: 0,
      axes: [0, 0, 0, 0],
      buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })),
    };
    (window as unknown as { pad: typeof pad }).pad = pad;
    navigator.getGamepads = () => [pad as unknown as Gamepad];
  });
  await page.reload();
  await page.getByTestId("config").selectOption("Drive: full omni");
  await page.getByTestId("run").click();
  await expect(page.getByTestId("phase")).toContainText("opcontrol");
  await expect(page.getByTestId("readout")).toContainText("so does Test gamepad");
  const [x0] = await truePose(page);
  await page.evaluate(() => {
    const pad = (window as unknown as { pad: { axes: number[]; buttons: { pressed: boolean }[] } }).pad;
    pad.axes[1] = -1; // the left stick pushed up
    pad.buttons[3].pressed = true; // the top face button: the V5's X
  });
  await expect.poll(async () => (await truePose(page))[0], { timeout: 10_000 }).toBeGreaterThan(x0 + 10);
  await expect(page.getByRole("button", { name: "X", exact: true })).toHaveAttribute("aria-pressed", "true");
});

test("lists where a program failed, as a link to the line", async ({ page }, testInfo) => {
  const program = testInfo.outputPath("fails.py"); // inside the workspace, cleaned each run
  mkdirSync(dirname(program), { recursive: true });
  writeFileSync(program, "def autonomous(bot):\n    yield\n    spin_the_wheels()\n");
  const path = relative(WORKSPACE, program).split("\\").join("/");
  await page.getByRole("button", { name: "Refresh" }).click();
  await page.getByTestId("robot").selectOption(ROBOT);
  await page.getByTestId("program").selectOption(path);
  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Error");
  const link = page.getByTestId("problem-link");
  await expect(link).toHaveText(`${path}:3`);
  const href = (await link.getAttribute("href"))!;
  expect(href.startsWith("vscode://file/") && href.endsWith("/fails.py:3")).toBe(true);
  await expect(page.getByTestId("problems")).toContainText("NameError: name 'spin_the_wheels' is not defined");
});

test("lists every key", async ({ page }) => {
  await expect(page.getByTestId(`item-${ROBOT}`)).toBeVisible();
  await page.keyboard.press("?");
  await expect(page.getByTestId("keys-help")).toContainText("I L K J");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("keys-help")).toHaveCount(0);
});

test("records every run: scrub one, reopen an older one, overlay two", async ({ page }) => {
  test.setTimeout(120_000);
  const runCount = async () => ((await (await page.request.get("/api/runs")).json()) as unknown[]).length;
  const before = await runCount();
  await page.getByTestId("robot").selectOption(ROBOT);
  await page.getByTestId("field-select").selectOption("examples/fields/v5rc_empty.yaml");
  await page.getByTestId("program").selectOption(PROGRAM);
  await page.locator(".controls .speed select").selectOption("0"); // as fast as it goes
  for (const [i, y] of ["0", "24"].entries()) {
    await page.getByLabel("Start y (in)").fill(y); // the second starts 24 in further up the field
    await page.getByTestId("run").click();
    await expect.poll(runCount, { timeout: 60_000 }).toBe(before + i + 1);
  }

  // The run that just ended is on the field to scrub, at its end; the field, its time
  // and the readings follow the scrubber
  const field = page.getByTestId("field");
  const scrubber = page.getByTestId("scrubber");
  await expect(page.getByTestId("timeline")).toBeVisible();
  const [start, end] = [Number(await scrubber.getAttribute("min")), Number(await scrubber.getAttribute("max"))];
  expect(end - start).toBeGreaterThan(5);
  await expect(field).toHaveAttribute("data-time", end.toFixed(3));
  const atEnd = await truePose(page);
  await scrubber.fill("2");
  await expect(field).toHaveAttribute("data-time", "2.000");
  await expect(page.getByTestId("playhead-time")).toHaveAttribute("data-t", "2.000");
  const atTwo = await truePose(page);
  expect(Math.hypot(atTwo[0] - atEnd[0], atTwo[1] - atEnd[1])).toBeGreaterThan(5);
  // Space plays it on from there and pauses it again; Home goes back to its start
  await field.focus();
  await page.keyboard.press("Space");
  await expect.poll(async () => Number(await field.getAttribute("data-time"))).toBeGreaterThan(2.3);
  await page.keyboard.press("Space");
  // the field draws a frame later, where it paused (the time it shows until then is older)
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  const paused = await field.getAttribute("data-time");
  await page.waitForTimeout(300);
  await expect(field).toHaveAttribute("data-time", paused!);
  await page.keyboard.press("Home");
  await expect(field).toHaveAttribute("data-time", start.toFixed(3));

  // Reopen the older run (newest first in the list): the form, the field and the console
  // are that run's again
  await page.getByTestId("tab-runs").click();
  const runs = page.getByTestId("recorded-run");
  await expect(runs).toHaveCount(before + 2);
  const [newer, older] = [runs.nth(0), runs.nth(1)];
  await older.getByTestId("open-run").click();
  await expect(older).toHaveClass(/shown/);
  expect(await startValue(page, "y")).toBe(0);
  await expect(page.getByTestId("console")).toContainText("autonomous start");
  await expect(page.getByTestId("status")).toHaveCount(0); // the live run is put away
  const csv = await page.request.get((await page.getByRole("link", { name: "CSV" }).getAttribute("href"))!);
  expect((await csv.text()).split("\n")[0]).toContain("time_s,phase,x_in");

  // Overlay the newer run: drawn over it on the field, in the key and in the plots
  await newer.getByTestId("compare-run").click();
  await expect(page.getByTestId("compared-key")).toHaveCount(1);
  await expect(field).toHaveAttribute("data-ghosts", "1");
  await page.getByTestId("plots-tab").click();
  await expect(page.getByTestId("plot-pose-error").locator(".plot-key")).toHaveCount(2);
  await expect(page.getByTestId("plot-speed").locator(".plot-key")).toHaveCount(2);
  await expect(page.getByTestId("plot-x").locator(".plot-key")).toHaveText([/^True/, /^Its code's estimate/]);
  // a click on a plot goes to that moment
  const plot = page.getByTestId("plot-pose-error").locator(".u-over");
  const box = (await plot.boundingBox())!;
  await plot.click({ position: { x: box.width * 0.25, y: box.height / 2 } });
  await expect.poll(async () => Number(await field.getAttribute("data-time"))).toBeLessThan(start + (end - start) * 0.5);

  // Keep it, rename it, and delete the other: the overlay goes with it
  await older.getByRole("button", { name: "Keep" }).click();
  await expect(older.locator(".tag")).toHaveText("kept");
  await older.getByRole("button", { name: "Rename" }).click();
  await older.getByLabel("New name").fill("from the middle");
  await older.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("shown-run")).toHaveText("from the middle");
  await newer.getByRole("button", { name: "Delete" }).click();
  await newer.getByRole("button", { name: "Sure?" }).click();
  await expect(runs).toHaveCount(before + 1);
  await expect(page.getByTestId("compared-key")).toHaveCount(0);
});

test("drags a sensor of the 1239E robot: its number changes and the comments stay", async ({ page }) => {
  const path = "examples/robots/1239e_2026-27.yaml";
  const file = resolve(WORKSPACE, path);
  const original = readFileSync(file, "utf-8");
  try {
    await page.getByTestId(`item-${path}`).click({ button: "right" }); // its menu
    await page.getByTestId(`edit-${path}`).click();
    await expect(page.getByTestId("config-state")).toHaveText("no problems");
    // frontL, the distance sensor on port 1: about an inch further forward, along x only
    const from = await onPage(page, 4.656207, 5.6937585, "diagram");
    const to = await onPage(page, 5.75, 5.6937585, "diagram");
    await page.mouse.move(...from);
    await page.mouse.down();
    await page.mouse.move(...to, { steps: 8 });
    await expect(page.getByTestId("drag-readout")).toHaveText(/^D1: x 5\.75\s+y 5\.6937585 in$/);
    await page.mouse.up();
    await expect(page.getByTestId("config-state")).toHaveText("no problems · unsaved changes");
    await expect(page.getByTestId(`page-${path}`)).toContainText("●");
    await page.keyboard.press("Control+s"); // the diagram has the focus
    await expect(page.getByTestId("config-notice")).toHaveText("Saved.");
    await expect(page.getByTestId(`page-${path}`)).not.toContainText("●");

    const before = original.split("\n");
    const after = readFileSync(file, "utf-8").split("\n");
    expect(after.length).toBe(before.length);
    const changed = before.map((line, i) => [line, after[i]]).filter(([a, b]) => a !== b);
    expect(changed).toEqual([
      [
        "  - {type: distance, port: 1,  pos_in: [ 4.656207,  5.6937585], heading_deg: 0,   height_in: 9.12}  # frontL",
        "  - {type: distance, port: 1,  pos_in: [ 5.75,  5.6937585], heading_deg: 0,   height_in: 9.12}  # frontL",
      ],
    ]);
  } finally {
    writeFileSync(file, original);
  }
});

test("marks a config's mistakes at their lines as you type", async ({ page }) => {
  await page.getByTestId("item-examples/fields/practice_elements.yaml").click({ button: "right" }); // its menu
  await page.getByTestId("edit-examples/fields/practice_elements.yaml").click();
  await expect(page.getByTestId("config-state")).toHaveText("no problems");
  await page.locator(".cm-line", { hasText: "size_in: [144, 144]" }).click();
  await page.keyboard.press("End");
  await page.keyboard.press("Backspace");
  await page.keyboard.type(", 12]"); // a third number
  await expect(page.getByTestId("config-state")).toHaveText("1 error, 0 warnings · unsaved changes");
  await expect(page.getByTestId("config-problems")).toContainText("size_in (line 8)");
  await expect(page.locator(".cm-lint-marker-error")).toHaveCount(1);
  await page.getByRole("button", { name: "Revert" }).click();
  await expect(page.getByTestId("config-state")).toHaveText("no problems");
  await page.getByRole("button", { name: "Close examples/fields/practice_elements.yaml" }).click();
  await expect(page.getByTestId("config-editor")).toHaveCount(0);
});
