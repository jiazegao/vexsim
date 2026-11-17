// Makes the README's pictures of the app (docs/img/ui_*.png) from this repository's examples,
// so a change to the page's layout doesn't leave them stale:
//
//     cd frontend
//     npm run build                 # the page the pictures are of
//     node scripts/pictures.mjs     # every picture; or name some: node scripts/pictures.mjs 1239e sweeps
//
// It starts its own `vexsim ui` on this repository (VEXSIM_PYTHON names the Python that has
// vexsim and its [ui] extra; default `python`), with its runs and results in a folder of
// their own, and drives the page as a person would. A C++ compiler is needed (1239E's project
// is built). The sweep's picture takes a few minutes: 54 runs.
//
// Two pictures aren't made here, and stay as they are: ui_mcl_log.png is of team 1239E's real
// MCL log 1040, which isn't in the repository, and ui_maker_motions.png is of a route made by
// hand for it (a RAMSETE path and an arc).

import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const OUT = join(ROOT, "docs", "img");
const PORT = 8655;
const TOKEN = "pictures";
const BASE = `http://127.0.0.1:${PORT}`;
const ROBOT_1239E = "examples/robots/1239e_2026-27.yaml";
const ROUTE = "examples/pros_projects/1239e_2026-27/routes/left_start.yaml";
const MINUTE = 60_000;

/** A point on a canvas's field (inches) as a point on the page: the canvas says its view. */
async function onPage(page, x, y, canvas) {
  const element = page.getByTestId(canvas);
  const box = await element.boundingBox();
  const [scale, cx, cy] = ((await element.getAttribute("data-view")) ?? "1,0,0").split(",").map(Number);
  return [box.x + box.width / 2 + (x - cx) * scale, box.y + box.height / 2 - (y - cy) * scale];
}

const fastest = (page) => page.locator(".controls .speed select").selectOption("0");

/** How many runs the history has: other pictures' runs are in it too. */
const kept = async (page) => (await (await page.request.get(`${BASE}/api/runs`)).json()).length;

/** Wait until the run history has this many runs: the one just started has ended. */
async function recorded(page, count) {
  for (let i = 0; i < 600; i++) {
    if ((await kept(page)) >= count) return;
    await page.waitForTimeout(200);
  }
  throw new Error("the run didn't end");
}
const settled = (page) => page.waitForTimeout(600);

async function edit(page, path) {
  await page.getByTestId(`item-${path}`).click({ button: "right" });
  await page.getByTestId(`edit-${path}`).click();
}

/** Each picture: its file, its window, and what to do before it's taken. */
const PICTURES = {
  // after 1239E's Left 40: where the robot went, and where its MCL thought it was
  "1239e": {
    size: [1280, 800],
    async make(page) {
      await page.getByTestId("config").selectOption("1239E: Left 40");
      await fastest(page);
      await page.getByTestId("run").click();
      await page.getByTestId("timeline").waitFor({ timeout: 5 * MINUTE });
    },
  },
  // two runs of the tour, one over the other, scrubbed to 6 s, with their plots
  compare: {
    size: [1400, 960],
    async make(page) {
      await page.getByTestId("robot").selectOption("examples/robots/full_omni_6m.yaml");
      await page.getByTestId("field-select").selectOption("examples/fields/v5rc_empty.yaml");
      await page.getByTestId("program").selectOption("examples/programs/tour.py");
      await fastest(page);
      const before = await kept(page);
      for (const [i, y] of ["0", "24"].entries()) {
        await page.getByLabel("Start y (in)").fill(y);
        await page.getByTestId("run").click();
        await recorded(page, before + i + 1); // run to its end, and kept
      }
      await page.getByTestId("tab-runs").click();
      const runs = page.getByTestId("recorded-run");
      await runs.nth(1).getByTestId("open-run").click(); // the first, from the middle
      await runs.nth(0).getByTestId("compare-run").click(); // the second over it
      await page.getByTestId("scrubber").fill("6");
      await page.getByTestId("plots-tab").click();
    },
  },
  // 1239E's config in the editor, its front-left distance sensor just dragged forward
  editor: {
    size: [1400, 900],
    async make(page) {
      await edit(page, ROBOT_1239E);
      await page.getByTestId("config-state").filter({ hasText: "no problems" }).waitFor();
      await page.mouse.move(...(await onPage(page, 4.656207, 5.6937585, "diagram")));
      await page.mouse.down();
      await page.mouse.move(...(await onPage(page, 5.75, 5.6937585, "diagram")), { steps: 8 });
      await page.mouse.up(); // not saved: the file stays as it is
    },
  },
  // the example shaped robot in the Design view, its clamp selected
  design: {
    size: [1400, 900],
    async make(page) {
      await edit(page, "examples/robots/shaped_6m.yaml");
      await page.getByTestId("config-state").filter({ hasText: "no problems" }).waitFor();
      await page.getByRole("button", { name: "Design", exact: true }).click();
      await settled(page);
      await page.mouse.click(...(await onPage(page, 8, -5, "diagram"))); // inside the clamp, clear of the sensor
    },
  },
  // 1239E's route in the autonomous maker, a step open in its form, the simulated path drawn
  maker: {
    size: [1400, 900],
    async make(page) {
      await edit(page, ROUTE);
      await page.getByTestId("route-state").waitFor();
      await page.getByTestId("step-2").click();
      await page.getByTestId("route-sim").filter({ hasText: /simulated|ends/i }).waitFor({ timeout: 5 * MINUTE }).catch(() => {});
      await page.waitForTimeout(3000);
    },
  },
  // the 1239E evaluation as a sweep: every routine, two ways of localizing, three seeds
  sweeps: {
    size: [1400, 1000],
    async make(page) {
      await page.getByTestId("page-sweeps").click();
      await page.getByTestId("sweep-pick").selectOption("1239E: RCL + MCL vs odometry");
      await page.getByTestId("sweep-run").click();
      await page.getByTestId("sweep-result").getByRole("link", { name: "trials.csv" }).waitFor({ timeout: 30 * MINUTE });
    },
  },
};

async function serverReady() {
  for (let i = 0; i < 120; i++) {
    try {
      await fetch(`${BASE}/api/info`); // 401 without the token: it's up
      return;
    } catch {
      await new Promise((done) => setTimeout(done, 500));
    }
  }
  throw new Error("vexsim ui didn't start");
}

async function main() {
  const wanted = process.argv.slice(2);
  const unknown = wanted.filter((name) => !(name in PICTURES));
  if (unknown.length) throw new Error(`no picture called ${unknown.join(", ")}: there's ${Object.keys(PICTURES).join(", ")}`);
  const names = wanted.length ? wanted : Object.keys(PICTURES);
  const scratch = mkdtempSync(join(tmpdir(), "vexsim-pictures-"));
  const python = process.env.VEXSIM_PYTHON ?? "python";
  const server = spawn(python, ["-m", "vexsim", "ui", ROOT, "--port", String(PORT), "--no-browser", "--token", TOKEN], {
    env: { ...process.env, VEXSIM_RUNS_DIR: join(scratch, "runs"), VEXSIM_RESULTS_DIR: join(scratch, "results") },
    stdio: "ignore",
  });
  const browser = await chromium.launch();
  try {
    await serverReady();
    for (const name of names) {
      const { size, make } = PICTURES[name];
      const context = await browser.newContext({ viewport: { width: size[0], height: size[1] }, colorScheme: "light" });
      const page = await context.newPage();
      await page.goto(`${BASE}/?token=${TOKEN}`);
      await page.getByTestId("field").waitFor();
      await make(page);
      await settled(page);
      const file = join(OUT, `ui_${name}.png`);
      await page.screenshot({ path: file });
      console.log(`wrote ${file}`);
      await context.close();
    }
  } finally {
    await browser.close();
    server.kill();
    rmSync(scratch, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.message ?? error);
  process.exit(1);
});
