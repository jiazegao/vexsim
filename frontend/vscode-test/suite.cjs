// @ts-check
// Runs inside VS Code, with this repository open and the vexsim extension installed from its
// .vsix: the panel opens the app, whose page loads in it, holds the server open and says it's
// ready; a place opens in an editor at its line; Stop stops vexsim.
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vscode = require("vscode");

/** Wait until `check()` gives something; fail after `seconds`, saying what it waited for
 * and, from `why()`, what it found. */
async function until(what, check, seconds, why = async () => "") {
  const deadline = Date.now() + seconds * 1000;
  for (;;) {
    const value = await check();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`timed out after ${seconds} s waiting for ${what}${await why()}`);
    await new Promise((done) => setTimeout(done, 250));
  }
}

async function info(app) {
  const response = await fetch(`${app.base}/api/info`, { headers: { authorization: `Bearer ${app.token}` } });
  return response.json();
}

async function suite() {
  const extension = vscode.extensions.getExtension("vexsim.vexsim");
  assert.ok(extension, "the vexsim extension is installed");
  const api = await extension.activate();
  const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  assert.ok(folder, "the repository is open");

  const started = Date.now();
  await vscode.commands.executeCommand("vexsim.open");
  const app = await until("vexsim to start", () => api.app(folder)?.panel && api.app(folder), 120, async () => {
    const failure = api.lastFailure();
    return failure ? ` (${failure})` : "";
  });
  await until("the app's page to load in the panel and say it's ready", () => app.ready, 60, async () => {
    const pages = (await info(app).catch(() => ({ pages: "?" }))).pages;
    return ` (the server counts ${pages} of its pages open: ${pages ? "the page loaded but didn't say so" : "the page didn't load"})`;
  });
  const ready = (Date.now() - started) / 1000;
  assert.ok((await info(app)).pages >= 1, "the page holds the server open");

  const tour = path.join(folder, "examples", "programs", "tour.py");
  await api.handle(folder, { type: "vexsim.open", file: tour, line: 5, column: 3 });
  const editor = vscode.window.activeTextEditor;
  assert.ok(editor, "a place opens in an editor");
  assert.strictEqual(editor.document.uri.fsPath, vscode.Uri.file(tour).fsPath);
  assert.deepStrictEqual([editor.selection.active.line, editor.selection.active.character], [4, 2]);

  await vscode.commands.executeCommand("vexsim.stop");
  assert.strictEqual(api.app(folder), undefined, "Stop closes the panel");
  await until("vexsim to stop", () => info(app).then(() => false, () => true), 30);
  return `VS Code ${vscode.version}: the app was ready in its panel ${ready.toFixed(1)} s after "Open the app", a place opened at its line, and Stop stopped vexsim`;
}

async function run() {
  const result = process.env.VEXSIM_VSCODE_RESULT;
  try {
    const found = await suite();
    if (result) fs.writeFileSync(result, JSON.stringify({ found }));
  } catch (error) {
    if (result) fs.writeFileSync(result, JSON.stringify({ error: error instanceof Error ? (error.stack ?? error.message) : String(error) }));
    throw error;
  }
}

module.exports = { run };
