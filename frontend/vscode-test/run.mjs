// The VS Code extension in a real VS Code: `vexsim vscode` packs it into a .vsix, VS Code's
// command line installs it, and suite.cjs runs inside VS Code with this repository open.
// VEXSIM_PYTHON names a Python that has vexsim and its [ui] extra (default: python). On
// Linux, run it under xvfb-run: VS Code needs a display. On GitHub, what it found is an
// annotation too, which the job's page shows: a notice, or the failure.
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath, runTests } from "@vscode/test-electron";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const python = process.env.VEXSIM_PYTHON ?? "python";
const scratch = mkdtempSync(join(tmpdir(), "vexsim-vscode-"));
const vsix = join(scratch, "vexsim.vsix");
const result = join(scratch, "result.json"); // what the suite found

function run(command, args) {
  // VS Code's command is a batch file on Windows, which only a shell runs
  const shell = process.platform === "win32";
  const quoted = shell ? args.map((arg) => (/\s/.test(arg) ? `"${arg}"` : arg)) : args;
  const done = spawnSync(shell && /\s/.test(command) ? `"${command}"` : command, quoted, { stdio: "inherit", shell });
  if (done.status !== 0) throw new Error(`${command} ${args.join(" ")} failed (${done.status ?? done.error})`);
}

try {
  run(python, ["-m", "vexsim", "vscode", "--no-install", "--out", vsix]);
  const vscode = await downloadAndUnzipVSCode(process.env.VSCODE_VERSION ?? "stable");
  const [cli, ...cliArgs] = resolveCliArgsFromVSCodeExecutablePath(vscode);
  run(cli, [...cliArgs, "--install-extension", vsix]);
  await runTests({
    vscodeExecutablePath: vscode,
    extensionDevelopmentPath: join(here, "runner"),
    extensionTestsPath: join(here, "suite.cjs"),
    launchArgs: [root, "--disable-workspace-trust", "--skip-welcome", "--skip-release-notes"],
    extensionTestsEnv: { VEXSIM_RUNS_DIR: join(scratch, "runs"), VEXSIM_VSCODE_RESULT: result },
  });
  const { found } = JSON.parse(readFileSync(result, "utf-8"));
  if (process.env.GITHUB_ACTIONS) console.log(`::notice title=VS Code panel::${found}`);
  console.log(found);
} catch (error) {
  const found = existsSync(result) ? JSON.parse(readFileSync(result, "utf-8")) : null;
  const message = found?.error ?? (error instanceof Error ? error.message : String(error));
  if (process.env.GITHUB_ACTIONS) console.log(`::error title=VS Code panel::${message.replace(/\r?\n/g, "%0A")}`);
  console.error(message);
  process.exit(1);
}
