import { expect, type Page, test } from "@playwright/test";
import { TOKEN } from "../playwright.config";

// A robot whose body is a shape (body.shape): a 12 x 14 in base, a round bumper at its back
// and a clamp at its front with a notch between its jaws.
const ROBOT = "examples/robots/shaped_6m.yaml";
const FIELD = "examples/fields/practice_elements.yaml";

/** A point on the field (inches) as a point on the page. */
async function onPage(page: Page, x: number, y: number): Promise<[number, number]> {
  const field = page.getByTestId("field");
  const box = (await field.boundingBox())!;
  const [scale, cx, cy] = ((await field.getAttribute("data-view")) ?? "1,0,0").split(",").map(Number);
  return [box.x + box.width / 2 + (x - cx) * scale, box.y + box.height / 2 - (y - cy) * scale];
}

async function startValue(page: Page, which: "x" | "y"): Promise<number> {
  return Number(await page.getByLabel(`Start ${which} (in)`).inputValue());
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

test("a robot with a shape starts where its outline fits, and is grabbed by it", async ({ page }) => {
  await page.getByTestId("robot").selectOption(ROBOT);
  await page.getByTestId("field-select").selectOption(FIELD);
  await expect(page.getByTestId("start-blocked")).toContainText("on top of barrier");
  // its sides are 7 in from its origin: against the barrier's face (1.5 in) is fine
  await page.getByLabel("Start y (in)").fill("8.5");
  await expect(page.getByTestId("start-blocked")).toHaveCount(0);
  await page.getByLabel("Start y (in)").fill("8.4");
  await expect(page.getByTestId("start-blocked")).toContainText("on top of barrier");

  await expect.poll(() => page.getByTestId("field").getAttribute("data-view")).not.toBe(null);
  // the notch between the jaws is empty: a press there doesn't grab the robot...
  const notch = await onPage(page, 7.6, 8.4);
  await page.mouse.move(...notch);
  await page.mouse.down();
  await page.mouse.move(notch[0] + 30, notch[1] + 30, { steps: 4 });
  await page.mouse.up();
  expect([await startValue(page, "x"), await startValue(page, "y")]).toEqual([0, 8.4]);
  // ...a jaw does
  const jaw = await onPage(page, 8, 12.4);
  const to = await onPage(page, -40, -20); // the robot's origin to (-48, -24)
  await page.mouse.move(...jaw);
  await page.mouse.down();
  await page.mouse.move(to[0], to[1], { steps: 8 });
  await page.mouse.up();
  expect([await startValue(page, "x"), await startValue(page, "y")]).toEqual([-48, -24]);
  await expect(page.getByTestId("start-blocked")).toHaveCount(0);

  await page.getByTestId("run").click();
  await expect(page.getByTestId("status")).toHaveText("Running");
  const pose = page.getByTestId("true-pose");
  const where = async () => ["x", "y"].map(async (k) => Math.round(Number(await pose.getAttribute(`data-${k}`))));
  await expect.poll(async () => Promise.all(await where())).toEqual([-48, -24]);
});
