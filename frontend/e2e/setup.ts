import { rmSync } from "node:fs";
import { RESULTS, RUNS } from "../playwright.config";

/** Every test run starts with no recorded runs and no results. */
export default function setup(): void {
  rmSync(RUNS, { recursive: true, force: true });
  rmSync(RESULTS, { recursive: true, force: true });
}
