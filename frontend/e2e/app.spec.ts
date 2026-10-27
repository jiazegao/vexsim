import { expect, type Page, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

const ROBOT = "examples/robots/full_omni_6m.yaml";
const FIELD = "examples/fields/practice_elements.yaml";
const PROGRAM = "examples/programs/tour.py";

/** The simulated time the page shows, in seconds. */
async function simTime(page: Page): Promise<number> {
  return Number((await page.getByTestId("sim-time").getAttribute("data-t")) ?? 0);
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
  await workspace.getByTestId(`item-${FIELD}`).click();
  await workspace.getByTestId(`item-${PROGRAM}`).click();
  await expect(page.getByTestId("robot")).toHaveValue(ROBOT);
  await expect(page.getByTestId("program")).toHaveValue(PROGRAM);
  await page.getByTestId("run").click();

  await expect(page.getByTestId("status")).toHaveText("Running");
  await expect.poll(() => simTime(page)).toBeGreaterThan(1);
  const frames = Number(await page.getByTestId("field").getAttribute("data-frames"));
  expect(frames).toBeGreaterThan(30); // streamed, not just the last frame
  await expect(page.getByTestId("command")).toHaveAttribute(
    "data-command",
    `vexsim run ${ROBOT} --program ${PROGRAM} --field ${FIELD}`,
  );
  await expect(page.getByTestId("console")).toContainText("autonomous start");

  await page.getByTestId("pause").click();
  await expect(page.getByTestId("status")).toHaveText("Paused");
  await page.waitForTimeout(300); // any frame already on its way
  const paused = await simTime(page);
  await page.waitForTimeout(500);
  expect(await simTime(page)).toBe(paused);

  // Space resumes, as in the pygame viewer (with no button focused: Space presses those)
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Space");
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
