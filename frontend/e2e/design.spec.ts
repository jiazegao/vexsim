import { readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

const WORKSPACE = resolve(import.meta.dirname, "../..");
const MADE = "examples/robots/designed_bot.yaml"; // beside the other robots; taken away after

/** A point on the robot (inches) as a point on the page, on the editor's diagram. */
async function onDiagram(page: Page, x: number, y: number): Promise<[number, number]> {
  const diagram = page.getByTestId("diagram");
  const box = (await diagram.boundingBox())!;
  const [scale, cx, cy] = ((await diagram.getAttribute("data-view")) ?? "1,0,0").split(",").map(Number);
  return [box.x + box.width / 2 + (x - cx) * scale, box.y + box.height / 2 - (y - cy) * scale];
}

async function drag(page: Page, from: [number, number], to: [number, number]): Promise<void> {
  await page.mouse.move(...(await onDiagram(page, ...from)));
  await page.mouse.down();
  const end = await onDiagram(page, ...to);
  await page.mouse.move(end[0], end[1], { steps: 8 });
  await page.mouse.up();
}

async function truePose(page: Page): Promise<[number, number, number]> {
  const pose = page.getByTestId("true-pose");
  const read = async (name: string) => Number(await pose.getAttribute(`data-${name}`));
  return [await read("x"), await read("y"), await read("heading")];
}

const comments = (text: string) => text.match(/#.*/g) ?? [];

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

test("draws a new robot, gives it a drive and sensors, saves it and drives it, the YAML unopened", async ({ page }) => {
  const file = resolve(WORKSPACE, MADE);
  try {
    await page.getByTestId("robot").selectOption({ label: "New robot…" });
    await page.getByTestId("new-robot-name").fill("Designed bot");
    await expect(page.getByTestId("new-robot-path")).toHaveValue(MADE);
    await page.getByTestId("new-robot-create").click();
    await expect(page.getByTestId("design-panel")).toBeVisible();
    await expect(page.getByTestId("yaml-editor")).toBeHidden();
    const template = readFileSync(file, "utf-8");

    // its shape: a round intake at the front, a tapered tail behind, bumpers at its sides
    await page.getByTestId("tool-circle").click();
    await drag(page, [7.5, 0], [9, 0]);
    await expect(page.getByTestId("shape-part-1")).toHaveText("Circle ⌀ 3 in at 7.5, 0");
    await page.getByTestId("tool-outline").click();
    for (const [x, y] of [[-7, 4], [-9, 2], [-9, -2], [-7, -4], [-7, 4]]) {
      await page.mouse.click(...(await onDiagram(page, x, y))); // the first point again closes it
    }
    await expect(page.getByTestId("shape-part-2")).toHaveText("Outline of 4 points");
    await page.getByTestId("mirror").check();
    await page.getByTestId("tool-rect").click();
    await drag(page, [-3, 7], [3, 9]);
    await expect(page.getByTestId("shape-part-3")).toHaveText("Rectangle 6 × 2 in at 0, 8");
    await expect(page.getByTestId("shape-part-4")).toHaveText("Rectangle 6 × 2 in at 0, -8"); // its mirror image
    // and an exact number: the base a little longer
    await page.getByTestId("shape-part-0").click();
    await page.getByLabel("Part 1 length (in)").fill("15.5");
    await page.getByLabel("Part 1 length (in)").press("Enter");
    await expect(page.getByTestId("shape-part-0")).toHaveText("Rectangle 15.5 × 15 in at 0, 0");

    // a six-motor drive on its base, an IMU and a distance sensor
    await page.getByTestId("drive-preset").selectOption("tank6");
    await expect(page.getByTestId("wheels").locator("tbody tr")).toHaveCount(6);
    await expect(page.getByTestId("drivetrain.gearing.left.motors")).toHaveValue("1, 2, 3");
    await page.getByTestId("add-imu").click();
    await expect(page.getByTestId("port-7")).toContainText("IMU");
    await page.getByTestId("add-distance").click();
    await expect(page.getByTestId("port-8")).toContainText("distance sensor");
    await expect(page.getByTestId("config-state")).toHaveText("no problems · unsaved changes");
    await page.getByTestId("save-config").click();
    await expect(page.getByTestId("config-notice")).toHaveText("Saved.");

    const saved = readFileSync(file, "utf-8");
    expect(comments(saved)).toEqual(comments(template)); // every comment the template had, in order
    expect(saved).toContain("    - {type: circle, pos_in: [7.5, 0], diameter_in: 3}\n");
    expect(saved).toContain("  - {type: imu, port: 7, pos_in: [-2, 2]}\n");
    expect(saved).toContain('    left: {motors: [1, 2, 3], cartridge: blue, ratio: "36:48", wheels: [lf, lm, lb]}\n');

    // it's the robot the next run uses: drive it
    await page.getByTestId("page-simulate").click();
    await expect(page.getByTestId("robot")).toHaveValue(MADE);
    await page.getByTestId("run").click();
    await expect(page.getByTestId("phase")).toContainText("opcontrol");
    const [x0] = await truePose(page);
    await page.keyboard.down("w"); // forward
    await expect.poll(async () => (await truePose(page))[0], { timeout: 10_000 }).toBeGreaterThan(x0 + 10);
    await page.keyboard.up("w");
  } finally {
    rmSync(file, { force: true });
  }
});

test("a robot's Design view writes its forms into the YAML, which an undo takes back", async ({ page }) => {
  const path = "examples/robots/full_omni_6m.yaml";
  const original = readFileSync(resolve(WORKSPACE, path), "utf-8");
  await page.getByTestId(`item-${path}`).click({ button: "right" }); // its menu
  await page.getByTestId(`edit-${path}`).click();
  await page.getByTestId("view-design").click();
  await page.getByLabel("Mass (kg)").fill("7.25");
  await page.getByLabel("Mass (kg)").press("Tab");
  await expect(page.getByTestId("config-state")).toHaveText("no problems · unsaved changes");
  // what doesn't read isn't written: the panel says why
  await page.getByTestId("drivetrain.gearing.left.motors").fill("1, 99");
  await page.getByTestId("drivetrain.gearing.left.motors").press("Enter");
  await expect(page.getByTestId("config-notice")).toContainText("motor ports are 1 to 21");
  await expect(page.getByTestId("drivetrain.gearing.left.motors")).toHaveValue("1, 2, 3");
  await page.getByTestId("view-yaml").click();
  await expect(page.locator(".cm-line", { hasText: "mass_kg: 7.25" })).toHaveCount(1);
  await page.getByTestId("view-design").click();
  await page.getByTestId("undo").click();
  await expect(page.getByLabel("Mass (kg)")).toHaveValue("6.5");
  await expect(page.getByTestId("config-state")).toHaveText("no problems");
  expect(readFileSync(resolve(WORKSPACE, path), "utf-8")).toBe(original); // never saved
});
