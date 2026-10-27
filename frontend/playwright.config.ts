import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

// The end-to-end tests drive the built app (vexsim/ui/static) served by a real
// `vexsim ui` for this repository. VEXSIM_PYTHON names a Python that has vexsim and
// its [ui] extra installed (default: `python`). The runs it records go to RUNS (emptied
// before the tests), not the repository's .vexsim/runs.
export const PORT = 8653;
export const TOKEN = "e2e-token";
export const RUNS = join(tmpdir(), "vexsim-e2e-runs");
const python = process.env.VEXSIM_PYTHON ?? "python";

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/setup.ts",
  timeout: 60_000,
  expect: { timeout: 30_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } } }],
  webServer: {
    command: `"${python}" -m vexsim ui .. --port ${PORT} --no-browser --token ${TOKEN}`,
    url: `http://127.0.0.1:${PORT}/api/info`, // answers 401 (ready) without the token
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: "pipe",
    env: { VEXSIM_RUNS_DIR: RUNS },
  },
});
