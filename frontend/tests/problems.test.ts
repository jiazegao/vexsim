import { describe, expect, it } from "vitest";
import { compilerProblems, editorUrl, linkSegments, shortPath, tracebackProblem } from "../src/problems";

const GCC = `compile errors:
/home/me/bot/src/main.cpp: In function 'void opcontrol()':
/home/me/bot/src/main.cpp:12:5: error: 'drive' was not declared in this scope
   12 |     drive(1);
      |     ^~~~~
/home/me/bot/src/main.cpp:12:5: note: suggested alternative: 'driver'
In file included from /home/me/bot/src/auton.cpp:1:
/home/me/bot/include/robot.hpp:3:10: fatal error: missing.h: No such file or directory
/home/me/bot/src/main.cpp:20:7: warning: unused variable 'x' [-Wunused-variable]
/home/me/bot/src/main.cpp:12:5: error: 'drive' was not declared in this scope
/usr/bin/ld: /tmp/obj/main.cpp.o: in function \`opcontrol':
/home/me/bot/src/main.cpp:30:(.text+0x1c): undefined reference to \`spin()'
[ 12:30:45] not a file`;

describe("compiler output", () => {
  it("gives each error and warning once, with where it is", () => {
    expect(compilerProblems(GCC)).toEqual([
      { severity: "error", file: "/home/me/bot/src/main.cpp", line: 12, column: 5, message: "'drive' was not declared in this scope" },
      { severity: "error", file: "/home/me/bot/include/robot.hpp", line: 3, column: 10, message: "missing.h: No such file or directory" },
      { severity: "warning", file: "/home/me/bot/src/main.cpp", line: 20, column: 7, message: "unused variable 'x' [-Wunused-variable]" },
      { severity: "error", file: "/home/me/bot/src/main.cpp", line: 30, column: null, message: "undefined reference to `spin()'" },
    ]);
  });

  it("reads Windows paths, drive letter and all", () => {
    const [problem] = compilerProblems("C:\\Users\\me\\bot\\src\\main.cpp:7:1: error: expected ';'");
    expect(problem).toMatchObject({ file: "C:\\Users\\me\\bot\\src\\main.cpp", line: 7, column: 1 });
  });
});

const TRACEBACK = `Traceback (most recent call last):
  File "/home/me/vexsim/app/worker.py", line 140, in create
    self.sim = self.factory()
  File "/home/me/bot/auton.py", line 4, in autonomous
    1 / 0
  File "<frozen importlib._bootstrap>", line 1, in _call
ZeroDivisionError: division by zero
`;

describe("Python tracebacks", () => {
  it("point at the innermost frame in the workspace, with the exception", () => {
    expect(tracebackProblem(TRACEBACK, "/home/me/bot")).toEqual({
      severity: "error",
      file: "/home/me/bot/auton.py",
      line: 4,
      column: null,
      message: "ZeroDivisionError: division by zero",
    });
    expect(tracebackProblem(TRACEBACK)?.file).toBe("/home/me/bot/auton.py"); // innermost real file
    expect(tracebackProblem("no frames here")).toBeNull();
  });
});

describe("links", () => {
  it("find the places in a line of output", () => {
    expect(linkSegments("/home/me/bot/src/main.cpp:12:5: error: oops")).toEqual([
      { text: "/home/me/bot/src/main.cpp:12:5", file: "/home/me/bot/src/main.cpp", line: 12, column: 5 },
      ": error: oops",
    ]);
    expect(linkSegments('  File "/home/me/bot/auton.py", line 4, in autonomous')).toEqual([
      "  ",
      { text: 'File "/home/me/bot/auton.py", line 4', file: "/home/me/bot/auton.py", line: 4, column: null },
      ", in autonomous",
    ]);
    expect(linkSegments("listening on 127.0.0.1:8642 at 12:30")).toEqual(["listening on 127.0.0.1:8642 at 12:30"]);
  });

  it("open in the chosen editor", () => {
    const place = { file: "src/main.cpp", line: 12, column: 5 };
    expect(editorUrl("vscode", "/home/me/bot", place)).toBe("vscode://file/home/me/bot/src/main.cpp:12:5");
    expect(editorUrl("cursor", "C:\\Users\\me\\bot", { ...place, column: null })).toBe("cursor://file/C:/Users/me/bot/src/main.cpp:12");
    expect(editorUrl("vscode", "/x", { file: "/home/my bot/a.py", line: 1, column: null })).toBe("vscode://file/home/my%20bot/a.py:1");
    expect(editorUrl("none", "/x", place)).toBeNull();
  });

  it("show paths relative to the workspace", () => {
    expect(shortPath("/home/me/bot", "/home/me/bot/src/main.cpp")).toBe("src/main.cpp");
    expect(shortPath("C:\\Bot", "c:\\bot\\src\\main.cpp")).toBe("src/main.cpp");
    expect(shortPath("/home/me/bot", "/usr/include/stdio.h")).toBe("/usr/include/stdio.h");
  });
});
