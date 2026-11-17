import { readdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { NEW, RESULTS, RUNS } from "../playwright.config";

/** Every test run starts with no recorded runs and no results, and the new folder empty (its
 * server has it open, so the folder itself stays). */
export default function setup(): void {
  rmSync(RUNS, { recursive: true, force: true });
  rmSync(RESULTS, { recursive: true, force: true });
  for (const name of readdirSync(NEW)) rmSync(join(NEW, name), { recursive: true, force: true });
}
