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
    const add = editor.getByTestId("add-step");
    await add.selectOption("move_to_point"); // 24 in ahead
    await expect(steps).toHaveCount(1);
    await add.selectOption("turn_to_heading"); // a quarter turn on
    await expect(steps).toHaveCount(2);
    await add.selectOption("wait");
    await expect(steps).toHaveCount(3);
    await editor.getByTestId("header-include/custom/util_funcs.hpp").click(); // its functions
    await add.selectOption("call:moveForward");
    await expect(steps).toHaveCount(4);
    await editor.getByTestId("step-3-arg-inches").fill("12");
    await editor.getByTestId("step-3-arg-inches").press("Enter");
    // its "// vexsim: drive(inches)" comment says where it goes: 12 in along the heading
    await expect(steps.nth(3)).toHaveAttribute("data-planned", "-24.00,-36.00,180.00");
    // a motion tool: a step where the field is clicked (to the nearest half tile)
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
      "Move to (0, -46.8) · waits",
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
        "  - {move_to_point: [0, -46.8], timeout: 1900, async: false}",
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
