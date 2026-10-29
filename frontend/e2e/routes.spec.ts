import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Locator, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

const WORKSPACE = resolve(import.meta.dirname, "../..");
const PROJECT = "examples/pros_projects/1239e_2026-27";
const ROBOT = "examples/robots/1239e_2026-27.yaml";
const FIELD = "examples/fields/1239e_2026-27.yaml";
const ROUTE = `${PROJECT}/routes/e2e_route.yaml`; // made, then deleted, by the test
const MIRRORED = `${PROJECT}/routes/e2e_route_mirrored.yaml`;
const BUILD = 300_000; // the first run of a route builds the 1239E project (and LemLib) here

/** A point on the field (inches) as a point on the page, on the autonomous maker's field. */
async function onField(canvas: Locator, x: number, y: number): Promise<[number, number]> {
  const box = (await canvas.boundingBox())!;
  const [scale, cx, cy] = ((await canvas.getAttribute("data-view")) ?? "1,0,0").split(",").map(Number);
  return [box.x + box.width / 2 + (x - cx) * scale, box.y + box.height / 2 - (y - cy) * scale];
}

/** "Add a step": `query` typed in its box, then the option `id` (a kind, or call:name) picked from
 * the steps it finds. */
async function addStep(editor: Locator, query: string, id: string): Promise<void> {
  await editor.getByTestId("add-step").fill(query);
  await editor.getByTestId(`add-step-option-${id}`).click();
}

/** How far the simulated end of a step is from (x, y), in inches (NaN while it's simulated). */
async function simulatedFrom(editor: Locator, step: number, x: number, y: number): Promise<number> {
  const pose = ((await editor.getByTestId(`step-end-${step}`).getAttribute("data-pose")) || "NaN,NaN").split(",").map(Number);
  return Math.hypot(pose[0] - x, pose[1] - y);
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
  for (const session of await (await page.request.get("/api/sessions")).json()) {
    if (session.state !== "stopped") await page.request.delete(`/api/sessions/${session.id}`);
  }
});

test("builds a route from scratch: a dragged end is planned at once and simulated soon after, and the comments stay", async ({ page }) => {
  test.setTimeout(BUILD + 180_000);
  try {
    // New route…: in the 1239E project, with its robot and field
    await page.getByTestId("new-route").click();
    const dialog = page.getByTestId("new-route-dialog");
    await dialog.getByTestId("new-route-name").fill("E2E route");
    await dialog.getByTestId("new-route-project").selectOption(PROJECT);
    await dialog.getByTestId("new-route-robot").selectOption(ROBOT);
    await dialog.getByTestId("new-route-field").selectOption(FIELD);
    await expect(dialog.getByTestId("new-route-path")).toHaveText(ROUTE);
    await dialog.getByTestId("new-route-create").click();
    const editor = page.locator('[data-testid="route-editor"]:not([hidden])');
    await expect(editor).toHaveAttribute("data-path", ROUTE);
    await expect(page.getByTestId(`item-${ROUTE}`)).toContainText("E2E route");
    const steps = editor.locator("[data-testid^='step-'][data-planned]");
    await expect(steps).toHaveCount(0);

    // where it starts: (-48, -24), facing +x (LemLib's 90)
    for (const [box, value] of [["x", "-48"], ["y", "-24"], ["theta", "90"]]) {
      await editor.getByTestId(`route-start-${box}`).fill(value);
      await editor.getByTestId(`route-start-${box}`).press("Enter");
    }
    await expect(editor.getByTestId("route-start-y")).toHaveValue("-24");

    // LemLib's motions, a pause and one of the team's functions, each after the one before
    await addStep(editor, "move to point", "move_to_point"); // 24 in ahead
    await expect(steps).toHaveCount(1);
    await addStep(editor, "turn to heading", "turn_to_heading"); // a quarter turn on
    await expect(steps).toHaveCount(2);
    await addStep(editor, "wait", "wait");
    await expect(steps).toHaveCount(3);
    await editor.getByTestId("header-include/custom/util_funcs.hpp").click(); // its functions
    await expect(editor.getByTestId("header-include/custom/util_funcs.hpp")).toBeChecked();
    await addStep(editor, "moveForward", "call:moveForward");
    await expect(steps).toHaveCount(4);
    await editor.getByTestId("step-3-arg-inches").fill("12");
    await editor.getByTestId("step-3-arg-inches").press("Enter");
    // its "// vexsim: drive(inches)" comment says where it goes: 12 in along the heading
    await expect(steps.nth(3)).toHaveAttribute("data-planned", "-24.00,-36.00,180.00");
    // a motion tool: a step where the field is clicked
    await editor.getByTestId("tool-move_to_point").click();
    const canvas = editor.getByTestId("route-canvas");
    await page.mouse.click(...(await onField(canvas, 0, -47)));
    await expect(steps).toHaveCount(5);
    await editor.getByTestId("tool-select").click();
    await expect(steps.locator(".step-label")).toHaveText([
      "Move to (-24, -24) · waits",
      "Turn to 180° · waits",
      "Wait 250 ms",
      "moveForward(inches 12, timeout 1000)",
      "Move to (0, -47) · waits",
    ]);

    // a comment, typed in its YAML
    await editor.getByTestId("view-yaml").click();
    await editor.locator(".cm-line", { hasText: "turn_to_heading: 180" }).click();
    await page.keyboard.press("End");
    await page.keyboard.type("   # face the far wall");
    await editor.getByTestId("view-steps").click();

    // simulated: where each step really ended, beside where it was planned to
    await expect(editor.getByTestId("route-sim")).toContainText("Simulated: done", { timeout: BUILD });
    for (let i = 0; i < 4; i++) {
      const [x, y] = ((await steps.nth(i).getAttribute("data-planned")) ?? "").split(",").map(Number);
      expect(await simulatedFrom(editor, i, x, y)).toBeLessThan(3);
    }

    // drag the first step's target: its plan follows at once, its simulated end soon after
    await steps.nth(0).locator(".design-item-head").click();
    await page.mouse.move(...(await onField(canvas, -24, -24)));
    await page.mouse.down();
    await page.mouse.move(...(await onField(canvas, -23.4, -11.7)), { steps: 8 });
    await expect(editor.getByTestId("route-drag-readout")).toHaveText("step 1: (-23.4, -11.7)");
    await expect(steps.nth(0)).toHaveAttribute("data-planned", /^-23\.40,-11\.70,/);
    await page.mouse.up();
    await expect.poll(() => simulatedFrom(editor, 0, -23.4, -11.7), { timeout: 20_000 }).toBeLessThan(3);

    // Undo and Redo take the drag back and put it again, plan and all
    await editor.getByTestId("undo").click();
    await expect(steps.nth(0)).toHaveAttribute("data-planned", /^-24\.00,-24\.00,/);
    await editor.getByTestId("redo").click();
    await expect(steps.nth(0)).toHaveAttribute("data-planned", /^-23\.40,-11\.70,/);

    // saved: every change written in place, the comments kept
    await editor.getByTestId("save-route").click();
    await expect(editor.getByTestId("route-notice")).toHaveText("Saved.");
    expect(readFileSync(resolve(WORKSPACE, ROUTE), "utf-8")).toBe(
      [
        "# An autonomous route, for vexsim (its README: Autonomous routes). Numbers are",
        "# LemLib's: inches, and theta in degrees clockwise from +y.",
        "version: 1",
        "name: E2E route",
        "robot: ../../../robots/1239e_2026-27.yaml   # relative to this file",
        "field: ../../../fields/1239e_2026-27.yaml",
        "start: [-48, -24, 90]   # chassis.setPose(x, y, theta)",
        "functions: [include/custom/util_funcs.hpp]   # headers whose functions steps can call",
        "steps:",
        "  - {move_to_point: [-23.4, -11.7], timeout: 1600, async: false}",
        "  - {turn_to_heading: 180, timeout: 1000, async: false}   # face the far wall",
        "  - {wait: 250}",
        "  - {call: moveForward, args: {inches: 12, timeout: 1000}}",
        "  - {move_to_point: [0, -47], timeout: 1900, async: false}",
        "",
      ].join("\n"),
    );

    // mirrored for the other side of the field: a copy beside it, open in its own tab
    await editor.getByTestId("mirror-x").click();
    await expect(editor).toHaveAttribute("data-path", MIRRORED);
    await expect(steps.nth(0)).toHaveAttribute("data-planned", /^23\.40,-11\.70,/);
    await expect(page.getByTestId(`item-${MIRRORED}`)).toContainText("E2E route (mirrored)");

    // Watch: the route runs on the Simulate page, in the project's own autonomous()
    await page.getByTestId(`page-${ROUTE}`).click();
    await editor.getByTestId("watch").click();
    await expect(page.getByTestId("page-simulate")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("routine")).toHaveValue(`route:${ROUTE}`);
    await expect(page.getByTestId("console")).toContainText("running the route instead", { timeout: 60_000 });
  } finally {
    for (const path of [ROUTE, MIRRORED]) {
      const file = resolve(WORKSPACE, path);
      if (existsSync(file)) rmSync(file);
    }
  }
});

test("plans a RAMSETE path and an arc whole, shaded by speed: a point dragged, limits set, simulated close", async ({ page }) => {
  test.setTimeout(BUILD + 180_000);
  const route = `${PROJECT}/routes/e2e_motions.yaml`; // made, then deleted
  try {
    await page.getByTestId("new-route").click();
    const dialog = page.getByTestId("new-route-dialog");
    await dialog.getByTestId("new-route-name").fill("E2E motions");
    await dialog.getByTestId("new-route-project").selectOption(PROJECT);
    await dialog.getByTestId("new-route-robot").selectOption(ROBOT);
    await dialog.getByTestId("new-route-field").selectOption(FIELD);
    await expect(dialog.getByTestId("new-route-path")).toHaveText(route);
    await dialog.getByTestId("new-route-create").click();
    const editor = page.locator('[data-testid="route-editor"]:not([hidden])');
    await expect(editor).toHaveAttribute("data-path", route);
    for (const [box, value] of [["x", "-48"], ["y", "0"], ["theta", "90"]]) {
      await editor.getByTestId(`route-start-${box}`).fill(value);
      await editor.getByTestId(`route-start-${box}`).press("Enter");
    }
    await expect(editor.getByTestId("route-start-theta")).toHaveValue("90");
    const steps = editor.locator("[data-testid^='step-'][data-planned]");

    // vexsim's own motions: a RAMSETE path curving off to the right, then an arc
    await addStep(editor, "ramsete", "ramsete");
    await expect(steps).toHaveCount(1);
    await expect(steps.nth(0)).toHaveAttribute("data-planned", "0.00,-24.00,116.57"); // the way its last stretch goes
    await addStep(editor, "arc", "move_arc");
    await expect(steps).toHaveCount(2);
    await editor.getByTestId("step-1-degrees").fill("-90"); // counter-clockwise
    await editor.getByTestId("step-1-degrees").press("Enter");
    await expect(steps.nth(1)).toHaveAttribute("data-planned", "24.15,-15.95,26.57"); // a quarter turn on, 18 in round
    const canvas = editor.getByTestId("route-canvas");
    await expect(canvas).toHaveAttribute("data-trajectories", /^1:\d+\.\d\ds 2:\d+\.\d\ds$/); // each drawn whole, with its speeds
    await expect(editor.getByTestId("step-1-plan")).toContainText("Its plan takes");

    // the drive model they drive with: vexsim's, worked out from the robot
    const drive = editor.getByTestId("route-drive");
    await expect(drive).toContainText("vexsim's, from the robot");
    await expect(drive.getByTestId("route-drive-kV")).toHaveAttribute("placeholder", /^0\.1\d+$/);

    // the path's first point dragged on the field: its plan follows at once
    await steps.nth(0).locator(".design-item-head").click();
    const before = await canvas.getAttribute("data-trajectories");
    await page.mouse.move(...(await onField(canvas, -24, -12)));
    await page.mouse.down();
    await page.mouse.move(...(await onField(canvas, -24, 0)), { steps: 8 });
    await expect(editor.getByTestId("route-drag-readout")).toHaveText("step 1, point 1: (-24, 0)");
    await page.mouse.up();
    await expect(editor.getByTestId("step-0-point-0-y")).toHaveValue("0");
    await expect(canvas).not.toHaveAttribute("data-trajectories", before!);
    await expect(steps.nth(0)).toHaveAttribute("data-planned", "0.00,-24.00,135.00");
    await expect(steps.nth(1)).toHaveAttribute("data-planned", "25.46,-24.00,45.00"); // the arc goes on from there

    // its own top speed and timeout, and a gentler limit on turning for both
    await drive.locator("summary").click();
    for (const [box, value] of [["step-0-max_velocity", "40"], ["step-0-timeout", "5000"], ["route-drive-max_lateral_accel", "10"]]) {
      await editor.getByTestId(box).fill(value);
      await editor.getByTestId(box).press("Enter");
    }
    await expect(steps.locator(".step-label")).toHaveText(["RAMSETE path through (-24, 0), (0, -24) · max 40 in/s · waits", "Arc 90° counter-clockwise, radius 18 in · waits"]);
    await expect(drive).toContainText("its own numbers, and vexsim's for the rest");

    // simulated: each ends close to where it's planned to
    await expect(editor.getByTestId("route-sim")).toContainText("Simulated: done", { timeout: BUILD });
    for (let i = 0; i < 2; i++) {
      const [x, y] = ((await steps.nth(i).getAttribute("data-planned")) ?? "").split(",").map(Number);
      expect(await simulatedFrom(editor, i, x, y)).toBeLessThan(3);
    }
    await editor.getByTestId("save-route").click();
    await expect(editor.getByTestId("route-notice")).toHaveText("Saved.");
    const saved = readFileSync(resolve(WORKSPACE, route), "utf-8");
    expect(saved).toMatch(/\n {2}- \{ramsete: \[\[-24, 0\], \[0, -24\]\], timeout: 5000, async: false, max_velocity: 40\}\n {2}- \{move_arc: \[18, -90\], timeout: \d+, async: false\}\n/);
    expect(saved).toContain("\ndrive: {max_lateral_accel: 10}\n");
  } finally {
    const file = resolve(WORKSPACE, route);
    if (existsSync(file)) rmSync(file);
  }
});

test("finds a step by typing: a function from a header the route doesn't list adds the header too", async ({ page }) => {
  const route = `${PROJECT}/routes/e2e_search.yaml`; // made, then deleted
  try {
    await page.getByTestId("new-route").click();
    const dialog = page.getByTestId("new-route-dialog");
    await dialog.getByTestId("new-route-name").fill("E2E search");
    await dialog.getByTestId("new-route-project").selectOption(PROJECT);
    await dialog.getByTestId("new-route-robot").selectOption(ROBOT);
    await expect(dialog.getByTestId("new-route-path")).toHaveText(route);
    await dialog.getByTestId("new-route-create").click();
    const editor = page.locator('[data-testid="route-editor"]:not([hidden])');
    await expect(editor).toHaveAttribute("data-path", route);
    const steps = editor.locator("[data-testid^='step-'][data-planned]");
    const box = editor.getByTestId("add-step");
    const list = editor.getByTestId("add-step-list");

    // empty, it lists every step there is: LemLib's motions first
    await box.click();
    await expect(list.getByRole("option").first()).toHaveAttribute("data-testid", "add-step-option-move_to_point");
    // typed, the ones that match, best first: here, 1239E's intake functions in a header the route doesn't list
    await box.fill("front intake");
    await expect(list.getByRole("option")).toHaveText([/^startFrontIntake\(\)lift_control\.hpp \(adds it\)/, /^reverseFrontIntake\(\)/, /^stopFrontIntake\(\)/]);
    await page.keyboard.press("ArrowDown");
    await expect(list.getByRole("option").nth(1)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Enter"); // picks it: the step, and its header in the route's functions
    await expect(steps).toHaveCount(1);
    await expect(steps.locator(".step-label")).toHaveText(["reverseFrontIntake()"]);
    await expect(editor.getByTestId("header-include/custom/lift_control.hpp")).toBeChecked();
    await expect(box).toHaveValue("");
    await expect(list).toHaveCount(0);
    // a motion by its C++ name; Esc closes the list, then empties the box
    await box.fill("moveToPose");
    await expect(list.getByRole("option")).toHaveText([/^Move to a poseLemLib/]);
    await page.keyboard.press("Escape");
    await expect(list).toHaveCount(0);
    await page.keyboard.press("Escape");
    await expect(box).toHaveValue("");
    await box.fill("no such step");
    await expect(list).toHaveText(/Nothing matches/);
  } finally {
    const file = resolve(WORKSPACE, route);
    if (existsSync(file)) rmSync(file);
  }
});

test("exports the project's routes: the files it changes, shown first; then the routine list has them", async ({ page }) => {
  const route = `${PROJECT}/routes/left_start.yaml`;
  const header = resolve(WORKSPACE, PROJECT, "include/custom/auton.hpp");
  const generated = resolve(WORKSPACE, PROJECT, "src/vexsim_autons.cpp");
  const original = readFileSync(header, "utf-8");
  try {
    await page.getByTestId(`item-${route}`).click({ button: "right" });
    await page.getByTestId(`edit-${route}`).click();
    const editor = page.locator('[data-testid="route-editor"]:not([hidden])');
    await expect(editor).toHaveAttribute("data-path", route);
    await editor.getByTestId("export").click();
    const dialog = page.getByTestId("export-dialog");
    await expect(dialog.getByTestId("export-routines")).toHaveText("left_start() from routes/left_start.yaml");
    await expect(dialog.getByTestId("export-file-src/vexsim_autons.cpp")).toHaveAttribute("data-state", "new");
    await expect(dialog.getByTestId("export-file-include/custom/auton.hpp")).toHaveAttribute("data-state", "changed");
    expect(existsSync(generated)).toBe(false); // nothing's written yet
    await dialog.getByTestId("export-write").click();
    await expect(dialog).toHaveCount(0);
    await expect(editor.getByTestId("route-notice")).toHaveText(`Exported left_start() into ${PROJECT}: wrote src/vexsim_autons.cpp and include/custom/auton.hpp.`);
    expect(readFileSync(generated, "utf-8")).toContain("void left_start() {\n    chassis.setPose(60, 0, 90);\n    moveForward(-10, 800, 127, 1);\n");
    expect(readFileSync(header, "utf-8")).toBe(
      original.replace(/\n*$/, "\n\n// vexsim routes: begin (vexsim writes these from routes/ when it exports the routes)\nvoid left_start();  // routes/left_start.yaml\n// vexsim routes: end\n"),
    );
    // again: nothing changes
    await editor.getByTestId("export").click();
    await expect(page.getByTestId("export-write")).toHaveText("Up to date");
    await expect(page.getByTestId("export-write")).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("export-dialog")).toHaveCount(0);
    // the run bar lists it with the project's routines
    await page.getByTestId("page-simulate").click();
    await page.getByTestId("program").selectOption(PROJECT);
    await expect(page.getByTestId("routine").locator("option", { hasText: /^left_start$/ })).toHaveCount(1);
  } finally {
    writeFileSync(header, original);
    if (existsSync(generated)) rmSync(generated);
  }
});
