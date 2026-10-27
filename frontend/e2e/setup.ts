import { rmSync } from "node:fs";
import { RUNS } from "../playwright.config";

/** Every test run starts with no recorded runs. */
export default function setup(): void {
  rmSync(RUNS, { recursive: true, force: true });
}
