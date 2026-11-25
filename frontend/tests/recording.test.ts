import { describe, expect, it } from "vitest";
import type { RunRecord } from "../src/protocol";
import { madeBy, runTitle } from "../src/recording";

const RUN = {
  id: "20261125-120000-ab12",
  name: "Tour",
  command: "vexsim run robot.yaml --program tour.py",
} as RunRecord;

describe("which physics step made a run", () => {
  it("is what its record says", () => {
    expect(madeBy({ ...RUN, physics: "compiled" })).toBe("the compiled physics step");
    expect(madeBy({ ...RUN, physics: "python" })).toBe("the Python physics step");
  });

  it("is nothing for a run recorded before vexsim said", () => {
    expect(madeBy(RUN)).toBeNull();
    expect(madeBy({ ...RUN, physics: null })).toBeNull();
  });

  it("is in what hovering over the run says, between its command and what a click does", () => {
    expect(runTitle({ ...RUN, physics: "compiled" })).toBe(
      "vexsim run robot.yaml --program tour.py\n\nSimulated with the compiled physics step\n\nOpen this run to play it back",
    );
    expect(runTitle(RUN)).toBe("vexsim run robot.yaml --program tour.py\n\nOpen this run to play it back");
  });
});
