import { existsSync, readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

const WORKSPACE = resolve(import.meta.dirname, "../..");
const ROBOT = "examples/robots/full_omni_6m.yaml";
const COPY = "examples/robots/full_omni_6m_copy.yaml"; // made, then deleted, by the tests
const OTHER = "examples/robots/1239e_2026-27.yaml";
const PROGRAM = "examples/programs/tour.py";
const PROJECT = "examples/pros_projects/minimal_pros4";

/** A point on the robot (inches) as a point on the page, on the open editor's diagram. */
async function onDiagram(page: Page, x: number, y: number): Promise<[number, number]> {
  const diagram = page.locator('[data-testid="config-editor"]:not([hidden]) [data-testid="diagram"]');
  const box = (await diagram.boundingBox())!;
  const [scale, cx, cy] = ((await diagram.getAttribute("data-view")) ?? "1,0,0").split(",").map(Number);
  return [box.x + box.width / 2 + (x - cx) * scale, box.y + box.height / 2 - (y - cy) * scale];
}

/** Open a config's editor from its menu. */
async function edit(page: Page, path: string): Promise<void> {
  await page.getByTestId(`item-${path}`).click({ button: "right" });
  await page.getByTestId(`edit-${path}`).click();
  await expect(page.locator('[data-testid="config-editor"]:not([hidden])')).toHaveAttribute("data-path", path);
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

test.afterEach(() => {
  expect(problems).toEqual([]);
});

test("a workspace item's menu edits it, duplicates it and deletes it", async ({ page }) => {
  const copy = resolve(WORKSPACE, COPY);
  try {
    // a right-click opens it, Escape closes it
    await page.getByTestId(`item-${ROBOT}`).click({ button: "right" });
    const menu = page.getByTestId("item-menu");
    await expect(menu.getByRole("menuitem")).toHaveText(["Edit", "Duplicate", "Delete…"]);
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);

    // Duplicate (from its ⋯ button): a copy beside it, named as one, with all the rest as it was
    await page.getByTestId(`menu-${ROBOT}`).click();
    await page.getByTestId(`duplicate-${ROBOT}`).click();
    const made = page.getByTestId(`item-${COPY}`);
    await expect(made).toContainText("Example 6-motor full omni (copy)");
    const original = readFileSync(resolve(WORKSPACE, ROBOT), "utf-8");
    expect(readFileSync(copy, "utf-8")).toBe(original.replace("name: Example 6-motor full omni", "name: Example 6-motor full omni (copy)"));

    // Edit opens it in its editor; Delete asks first, then takes it, and its editor, away
    await edit(page, COPY);
    await made.click({ button: "right" });
    await page.getByTestId(`delete-${COPY}`).click();
    await expect(menu).toContainText(`Delete ${COPY}? It can't be undone.`);
    await page.getByTestId(`delete-${COPY}-confirm`).click();
    await expect(made).toHaveCount(0);
    await expect(page.getByTestId("config-editor")).toHaveCount(0);
    expect(existsSync(copy)).toBe(false);
  } finally {
    rmSync(copy, { force: true });
  }
});

test("a program is edited in your editor; a project's folder isn't copied or deleted here", async ({ page }) => {
  await page.getByTestId(`item-${PROGRAM}`).click({ button: "right" });
  const edit = page.getByTestId(`edit-${PROGRAM}`);
  await expect(edit).toHaveText("Edit in VS Code");
  await expect(edit).toHaveAttribute("href", /^vscode:\/\/file\/.*\/examples\/programs\/tour\.py:1$/);
  await page.keyboard.press("Escape");
  await page.getByTestId(`menu-${PROJECT}`).click();
  await expect(page.getByTestId(`edit-${PROJECT}`)).toHaveAttribute("href", /\/minimal_pros4\/src\/main\.cpp:1$/);
  for (const action of ["duplicate", "delete"]) {
    await expect(page.getByTestId(`${action}-${PROJECT}`)).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByTestId(`${action}-${PROJECT}`)).toHaveAttribute("title", /a folder/);
  }
});

test("Ctrl+C and Ctrl+V copy a robot's parts: into the robot, and into another", async ({ page }) => {
  const before = [ROBOT, OTHER].map((path) => readFileSync(resolve(WORKSPACE, path), "utf-8"));
  await edit(page, ROBOT);
  await page.getByTestId("view-design").click();
  const notice = page.getByTestId("config-notice");

  // a wheel: its copy is the next of its name, driven by its motor group
  await page.mouse.click(...(await onDiagram(page, 5.5, 6))); // lf
  await page.keyboard.press("Control+c");
  await expect(notice).toHaveText("Copied wheel lf: Ctrl+V pastes a copy, into this robot or another.");
  await page.keyboard.press("Control+v");
  await page.keyboard.press("Control+v");
  await expect(notice).toHaveText("Pasted wheel lf3.");
  await expect(page.getByTestId("wheels").locator("tbody tr")).toHaveCount(8);
  await expect(page.getByTestId("group-left").getByLabel("lf3")).toBeChecked();
  await expect(page.locator('[data-path="drivetrain.wheels[7]"]')).toHaveClass(/\bon\b/); // selected

  // a part of its shape (a footprint, until now)
  await page.mouse.click(...(await onDiagram(page, -4, -4)));
  await page.keyboard.press("Control+c");
  await page.keyboard.press("Control+v");
  await expect(notice).toHaveText("Pasted a copy of the rectangle.");
  await expect(page.getByTestId("shape-part-1")).toHaveText("Rectangle 15 × 15 in at 1, -1");

  // a sensor, on the first free port, into the 1239E robot
  await page.mouse.click(...(await onDiagram(page, 7, 0))); // the distance sensor, port 13
  await page.keyboard.press("Control+c");
  await expect(notice).toContainText("Copied the distance sensor on port 13");
  await edit(page, OTHER);
  await page.mouse.click(...(await onDiagram(page, 0, -3))); // its diagram has the keyboard
  await page.keyboard.press("Control+v");
  await expect(page.locator('[data-testid="config-editor"]:not([hidden]) [data-testid="config-notice"]')).toHaveText("Pasted a distance sensor on port 13."); // free there: it keeps it
  await expect(page.getByTestId(`page-${OTHER}`)).toContainText("●");
  expect([ROBOT, OTHER].map((path) => readFileSync(resolve(WORKSPACE, path), "utf-8"))).toEqual(before); // never saved
});
