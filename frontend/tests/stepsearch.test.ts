// "Add a step" in the autonomous maker: the steps to add, and what typing finds among them.
import { describe, expect, it } from "vitest";
import type { RouteFunctionInfo } from "../src/protocol";
import { marked, matchRank, searchSteps, stepOptions, wordsOf } from "../src/stepsearch";

function fn(name: string, header: string): RouteFunctionInfo {
  return { name, header, line: 1, declaration: `void ${name}()`, params: [], required: 0, hint: null, hint_problem: null };
}

const LISTED = [fn("moveForward", "include/custom/util_funcs.hpp"), fn("turnBy", "include/custom/util_funcs.hpp")];
const MORE = [fn("startFrontIntake", "include/custom/lift_control.hpp"), fn("moveForward", "include/custom/other.hpp")];

describe("the steps to add", () => {
  it("are the motions, the pauses, the route's functions, then the project's other headers' (which add their header)", () => {
    const options = stepOptions(LISTED, MORE);
    expect(options.map((o) => o.id)).toEqual([
      "move_to_point", "move_to_pose", "turn_to_heading", "turn_to_point", "swing_to_heading", "swing_to_point", "move_arc", "ramsete",
      "wait", "wait_until", "wait_until_done",
      "call:moveForward", "call:turnBy", "call:startFrontIntake", // (another header's moveForward: the route's own)
    ]); // prettier-ignore
    const [point] = options;
    expect([point.title, point.detail, point.group]).toEqual(["Move to a point", "chassis.moveToPoint", "LemLib"]);
    expect(options.find((o) => o.id === "ramsete")?.detail).toBe("motions.ramsete");
    expect(options.find((o) => o.id === "wait_until")?.detail).toBe("chassis.waitUntil(distance)");
    const listed = options.find((o) => o.id === "call:moveForward")!;
    expect([listed.title, listed.group, listed.header, listed.fn?.name]).toEqual(["moveForward()", "util_funcs.hpp", undefined, "moveForward"]);
    const more = options.find((o) => o.id === "call:startFrontIntake")!;
    expect([more.group, more.header]).toEqual(["lift_control.hpp", "include/custom/lift_control.hpp"]);
  });
});

describe("what typing finds", () => {
  it("ranks a match at the start, then at a word, then inside, then letters in order", () => {
    expect(wordsOf("startFrontIntake")).toEqual(["start", "front", "intake"]);
    expect(wordsOf("chassis.moveToPoint")).toEqual(["chassis", "move", "to", "point"]);
    expect(matchRank("", "anything")).toBe(0);
    expect(matchRank("Move to", "Move to a point")).toBe(0);
    expect(matchRank("move to point", "move_to_point")).toBe(0); // case and punctuation don't count
    expect(matchRank("intake", "startFrontIntake")).toBe(1);
    expect(matchRank("front int", "startFrontIntake")).toBe(1); // on over the words after
    expect(matchRank("ntak", "startFrontIntake")).toBe(2);
    expect(matchRank("intake start", "startFrontIntake")).toBe(2); // each word of it, in any order
    expect(matchRank("sfi", "startFrontIntake")).toBe(3);
    expect(matchRank("xyz", "startFrontIntake")).toBeNull();
  });

  it("lists the matches best first, ties in their order; everything for nothing typed", () => {
    const options = stepOptions(LISTED, MORE);
    expect(searchSteps(options, "")).toEqual(options);
    const ids = (query: string) => searchSteps(options, query).map((o) => o.id);
    expect(ids("turn")).toEqual(["turn_to_heading", "turn_to_point", "call:turnBy"]);
    expect(ids("point")).toEqual(["move_to_point", "turn_to_point", "swing_to_point"]);
    expect(ids("intake")).toEqual(["call:startFrontIntake"]);
    expect(ids("arc")[0]).toBe("move_arc");
    expect(ids("ramsete")).toEqual(["ramsete"]);
    expect(ids("wait")).toEqual(["wait", "wait_until", "wait_until_done"]);
    expect(ids("lift_control")).toEqual(["call:startFrontIntake"]); // its header's name finds it too
    expect(ids("moveToPoint")).toEqual(["move_to_point"]); // as the C++ has it
    expect(ids("qqq")).toEqual([]);
  });

  it("marks where the typed text is in a title", () => {
    expect(marked("startFrontIntake()", "front")).toEqual(["start", "Front", "Intake()"]);
    expect(marked("Move to a point", " point ")).toEqual(["Move to a ", "point", ""]);
    expect(marked("Wait (ms)", "")).toEqual(["Wait (ms)", "", ""]);
    expect(marked("Wait (ms)", "sfi")).toEqual(["Wait (ms)", "", ""]);
  });
});
