import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "@playwright/test";
import { NEW, NEW_URL, TOKEN } from "../playwright.config";

// Phase 15.4: a way in. In a folder with nothing in it, the Simulate page says where to start,
// and a student makes a robot, drives it, adds a program and runs it without leaving the app.
// vexsim's own guides are a page of the app, and a calibration session's steps say which are
// done and which is next.

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
  const base = new URL(page.url()).origin;
  for (const session of await (await page.request.get(`${base}/api/sessions`)).json()) {
    if (session.state !== "stopped") await page.request.delete(`${base}/api/sessions/${session.id}`);
  }
});

/** A step of the first run's row, and one of a calibration session's. */
const step = (page: Page, key: string) => page.getByTestId(`first-steps-${key}`);
const sessionStep = (page: Page, key: string) => page.getByTestId(`session-steps-${key}`);
const selected = (page: Page, testid: string) => expect(page.getByTestId(testid)).toHaveAttribute("aria-selected", "true");
const hash = (page: Page) => new URL(page.url()).hash;
/** Where the robot really is: x (in). */
const trueX = async (page: Page) => Number(await page.getByTestId("true-pose").getAttribute("data-x"));

test.describe("in a folder with nothing in it", () => {
  test("the page says where to start; it can be put away, for this folder", async ({ page }) => {
    await page.goto(`${NEW_URL}/?token=${TOKEN}`);
    const start = page.getByTestId("first-run");
    await expect(start).toBeVisible();
    await expect(start).toContainText("Start here");
    await expect(step(page, "robot")).toHaveAttribute("data-state", "next");
    for (const key of ["driven", "program", "ran"]) await expect(step(page, key)).toHaveAttribute("data-state", "todo");
    await expect(page.getByTestId("first-steps-driven-do")).toBeDisabled(); // nothing to drive yet
    await expect(page.getByTestId("first-steps-ran-do")).toBeDisabled();
    await expect(page.getByTestId("workspace")).toContainText("No robot configs, programs or PROS projects in this folder yet.");

    await page.getByTestId("first-run-guide").click(); // the user guide, in the app
    await expect(page.getByTestId("guide-document")).toHaveAttribute("data-doc", "readme");
    await page.goBack();
    await expect(start).toBeVisible();

    await page.getByTestId("first-run-hide").click();
    await expect(start).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId("field")).toBeVisible();
    await expect(page.getByTestId("run")).toBeVisible();
    await expect(start).toHaveCount(0); // kept
  });

  test("a student makes a robot, drives it, adds a program and runs it", async ({ page }) => {
    await page.goto(`${NEW_URL}/?token=${TOKEN}`);
    const start = page.getByTestId("first-run");
    await expect(step(page, "robot")).toHaveAttribute("data-state", "next");

    // 1. a robot: made, and open to draw
    await page.getByTestId("first-steps-robot-do").click();
    await page.getByTestId("new-robot-name").fill("First robot");
    const made = await page.getByTestId("new-robot-path").inputValue();
    await page.getByTestId("new-robot-create").click();
    await expect(page.locator('[data-testid="config-editor"]:not([hidden])')).toHaveAttribute("data-path", made);
    await page.getByTestId("page-simulate").click();
    await expect(page.getByTestId("robot")).toHaveValue(made);
    await expect(step(page, "robot")).toHaveAttribute("data-state", "done");
    await expect(step(page, "driven")).toHaveAttribute("data-state", "next");
    await expect(page.getByTestId("first-steps-robot-do")).toHaveCount(0); // a step that's done has nothing to press

    // 2. drive it: no program, the keys drive
    await page.getByTestId("first-steps-driven-do").click();
    await expect(page.getByTestId("phase")).toContainText("opcontrol");
    await expect(start).toHaveCount(0); // out of the way while a run is on
    const x0 = await trueX(page);
    await page.keyboard.down("w");
    await expect.poll(() => trueX(page), { timeout: 10_000 }).toBeGreaterThan(x0 + 10);
    await page.keyboard.up("w");
    await page.getByTestId("stop").click();
    await expect(page.getByTestId("status")).toHaveText("Stopped");
    await expect(step(page, "driven")).toHaveAttribute("data-state", "done");
    await expect(step(page, "program")).toHaveAttribute("data-state", "next");

    // 3. a first program: written into the folder, and picked
    await page.getByTestId("first-steps-program-do").click();
    await expect(page.getByTestId("program")).toHaveValue("programs/first_program.py");
    expect(existsSync(join(NEW, "programs", "first_program.py"))).toBe(true);
    expect(readFileSync(join(NEW, "programs", "first_program.py"), "utf-8")).toContain("def autonomous(bot):");
    await expect(page.getByTestId("item-programs/first_program.py")).toBeVisible();
    await expect(step(page, "program")).toHaveAttribute("data-state", "done");
    await expect(step(page, "ran")).toHaveAttribute("data-state", "next");

    // 4. run it: its autonomous drives a square, and says so
    await page.locator(".controls .speed select").selectOption("0");
    await page.getByTestId("first-steps-ran-do").click();
    const output = page.getByTestId("console");
    await expect(output).toContainText("autonomous: a square, 24 in on a side");
    await expect(page.getByTestId("status")).toHaveText("Finished", { timeout: 60_000 });
    await expect(output).toContainText("back at Pose(");
    expect(Math.abs(await trueX(page))).toBeLessThan(6); // back where it started

    // every step done: nothing more to say, with a run on show or without
    await expect(start).toHaveCount(0);
    await page.getByTestId("close-run").click();
    await expect(page.getByTestId("timeline")).toHaveCount(0);
    await expect(start).toHaveCount(0);
  });
});

test.describe("the guide", () => {
  test("shows vexsim's documents: their text, tables, code and pictures, each heading with its address", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);
    await page.getByTestId("page-guide").click();
    const document = page.getByTestId("guide-document");
    await expect(document).toHaveAttribute("data-doc", "readme"); // the user guide first
    await expect(document.locator("h1").first()).toHaveText(/vexsim/);
    await expect.poll(() => hash(page)).toBe("#/guide");
    await expect(page.locator('[data-testid^="guide-doc-"]')).toHaveCount(10);
    expect(await document.locator("h2").count()).toBeGreaterThan(8);
    expect(await document.locator("table").count()).toBeGreaterThan(20);
    expect(await document.locator("pre").count()).toBeGreaterThan(40);
    await expect(document).not.toContainText("**"); // read, not shown as typed
    await expect(document).not.toContainText("](");

    // a section, from the list beside the document: its heading at the top, its address the page's
    await page.getByTestId("guide-sections").getByText("7. The browser app").click();
    await expect.poll(() => hash(page)).toBe("#/guide/readme?at=7-the-browser-app-vexsim-ui");
    const heading = page.locator("#guide-7-the-browser-app-vexsim-ui");
    await expect(heading).toBeInViewport();
    expect((await heading.boundingBox())!.y).toBeLessThan(140);

    // a picture of the document's loads
    const picture = document.locator('img[alt^="The browser app after the 1239E port"]');
    await picture.scrollIntoViewIfNeeded();
    await expect.poll(() => picture.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(600);

    // a link to a heading of the same document, and one to another document, go there in the app
    await document.locator('a[href="#/guide/readme?at=picking-an-autonomous-routine"]').first().click();
    await expect.poll(() => hash(page)).toBe("#/guide/readme?at=picking-an-autonomous-routine");
    await expect(page.locator("#guide-picking-an-autonomous-routine")).toBeInViewport();
    await page.getByTestId("guide-doc-programming").click();
    await expect(document).toHaveAttribute("data-doc", "programming");
    await expect(document.locator("h1")).toHaveText("Writing robot programs");
    await document.locator('a[href="#/guide/cpp"]').first().click(); // "see cpp.md"
    await expect(document).toHaveAttribute("data-doc", "cpp");
    await expect.poll(() => hash(page)).toBe("#/guide/cpp");

    // Back steps through where you've read; a reload comes back to the same heading
    await page.goBack();
    await expect(document).toHaveAttribute("data-doc", "programming");
    await page.goBack();
    await expect(document).toHaveAttribute("data-doc", "readme");
    await expect(page.locator("#guide-picking-an-autonomous-routine")).toBeInViewport();
    await page.reload();
    await selected(page, "page-guide");
    await expect(page.locator("#guide-picking-an-autonomous-routine")).toBeInViewport();

    // a link out of vexsim's documents opens in a tab of its own
    await page.goto("/#/guide/cpp");
    const out = document.locator('a[href="https://www.msys2.org"]').first();
    await expect(out).toHaveAttribute("target", "_blank");
    await expect(out).toHaveAttribute("rel", "noreferrer noopener");
  });

  test("a calibration session's steps say which are done and which is next, and link to the guide", async ({ page }) => {
    await page.goto(`/?token=${TOKEN}`);
    await page.getByTestId("page-calibrate").click();
    const steps = page.getByTestId("session-steps");
    await expect(steps.locator("li")).toHaveCount(5);
    await expect(sessionStep(page, "setup")).toHaveAttribute("data-state", "done"); // a robot and a field are picked
    await expect(sessionStep(page, "program")).toHaveAttribute("data-state", /next|done/); // done once the tests have written one
    await expect(sessionStep(page, "fit")).toHaveAttribute("data-state", "todo");
    await expect(sessionStep(page, "collect")).toContainText("Run each test on the robot");

    // a click on a step goes to its part of the page
    await sessionStep(page, "fit").getByRole("button").click();
    await expect(page.getByTestId("session-fit")).toBeInViewport();

    // each step's section of the guide
    await page.getByTestId("session-steps-collect-guide").click();
    await selected(page, "page-guide");
    await expect(page.getByTestId("guide-document")).toHaveAttribute("data-doc", "calibration_guide");
    await expect.poll(() => hash(page)).toBe("#/guide/calibration_guide?at=5-the-session");
    await expect(page.locator("#guide-5-the-session")).toBeInViewport();
    await page.goBack();
    await selected(page, "page-calibrate");
    await page.getByTestId("calibrate-guide").click(); // and the guide itself, from the page's first lines
    await expect(page.getByTestId("guide-document").locator("h1")).toHaveText(/Calibrating vexsim to your robot/);
  });
});
