import { mkdirSync, writeFileSync } from "node:fs";
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

/** A point on the field (inches) as a point on the page. */
async function onPage(page: Page, x: number, y: number): Promise<[number, number]> {
  const field = page.getByTestId("field");
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

test("fills the run in from a saved run, start and environment too", async ({ page }) => {
  await page.getByTestId("config").selectOption("1239E: Left 40");
  await expect(page.getByTestId("robot")).toHaveValue("examples/robots/1239e_2026-27.yaml");
  await expect(page.getByTestId("program")).toHaveValue("examples/pros_projects/1239e_2026-27");
  expect(await startValue(page, "x")).toBe(60);
  await page.locator("summary", { hasText: "More" }).click();
  await expect(page.getByPlaceholder("VEXSIM_AUTON=Left 40")).toHaveValue("VEXSIM_AUTON=Left 40");
  await expect(page.locator(".changed")).toHaveCount(0);
  await page.getByLabel("Seed").fill("3");
  await expect(page.locator(".changed")).toHaveCount(1); // no longer the saved run as it is
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
