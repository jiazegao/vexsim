// @ts-check
// vexsim's app in a VS Code panel, beside your code. "vexsim: Open the app" (or "Open in
// vexsim" on a folder in the Explorer) runs `vexsim ui FOLDER` with the Python of the
// vexsim.python setting and shows the app in a panel (see panel.js). There, file:line links
// open in VS Code's editor, files are saved through its save dialog, and reports open in
// your browser. Closing the panel stops vexsim; so does "vexsim: Stop the app".

const childProcess = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vscode = require("vscode");
const { appUrl, findUrl, panelHtml, runWith, themeOf } = require("./panel");

const START_TIMEOUT_MS = 120_000; // a first start can compile Python files for a while

/**
 * @typedef {object} App A folder's vexsim and its panel.
 * @property {string} folder
 * @property {childProcess.ChildProcess} process `vexsim ui FOLDER`
 * @property {vscode.WebviewPanel} [panel] once vexsim has said where it is
 * @property {string} [base] the app's origin, as the panel reaches it
 * @property {string} [token] the server's token
 * @property {boolean} ready the app has loaded in the panel
 * @property {boolean} failed it didn't start
 */

/** @type {Map<string, App>} the apps open or starting, by folder */
const apps = new Map();
/** @type {vscode.OutputChannel} */
let output;
let lastFailure = ""; // why the last app didn't start

/** @param {vscode.ExtensionContext} context */
function activate(context) {
  output = vscode.window.createOutputChannel("vexsim");
  const open = (/** @type {unknown} */ uri) => openApp(context, uri);
  context.subscriptions.push(
    output,
    vscode.commands.registerCommand("vexsim.open", open),
    vscode.commands.registerCommand("vexsim.openFolder", open),
    vscode.commands.registerCommand("vexsim.stop", stopAll),
  );
  // for tests: a folder's app, a message handled as if its page had sent it, and why the
  // last app didn't start
  return {
    app: (/** @type {string} */ folder) => apps.get(path.resolve(folder)),
    lastFailure: () => lastFailure,
    handle: (/** @type {string} */ folder, /** @type {any} */ message) => handle(apps.get(path.resolve(folder)), message),
  };
}

function deactivate() {
  stopAll();
}

/** Open the app for a folder: the one given (from the Explorer), the workspace's only one,
 * or one picked. */
async function openApp(context, uri) {
  const folder = uri instanceof vscode.Uri ? uri.fsPath : await pickFolder();
  if (!folder) return;
  const running = apps.get(path.resolve(folder));
  if (running) {
    running.panel?.reveal();
    return;
  }
  start(context, path.resolve(folder));
}

async function pickFolder() {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length === 1) return folders[0].uri.fsPath;
  if (folders.length > 1) {
    const picked = await vscode.window.showWorkspaceFolderPick({ placeHolder: "The folder to open in vexsim" });
    return picked?.uri.fsPath;
  }
  const chosen = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false, openLabel: "Open in vexsim" });
  return chosen?.[0]?.fsPath;
}

/** Run `vexsim ui FOLDER`; show its page once it says where it is. */
function start(context, folder) {
  const configured = vscode.workspace.getConfiguration("vexsim").get("python") || (process.platform === "win32" ? "python" : "python3");
  const python = runWith(String(configured), process.platform, fs.existsSync);
  // it stops by itself if VS Code goes without stopping it
  const args = ["-m", "vexsim", "ui", folder, "--no-browser", "--stop-when-closed"];
  output.appendLine(`> ${python} ${args.join(" ")}`);
  const child = childProcess.spawn(python, args, {
    cwd: folder,
    windowsHide: true,
    env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
  });
  /** @type {App} */
  const app = { folder, process: child, ready: false, failed: false };
  apps.set(folder, app);
  let said = "";
  const timer = setTimeout(() => app.panel || fail(app, "vexsim didn't start in time", said), START_TIMEOUT_MS);
  const hear = (/** @type {Buffer} */ chunk) => {
    const text = chunk.toString();
    output.append(text);
    if (app.panel || app.failed) return;
    said += text;
    const found = findUrl(said);
    if (found) {
      clearTimeout(timer);
      show(context, app, found.url, found.token).catch((error) => fail(app, `the panel didn't open: ${error}`, said));
    }
  };
  child.stdout?.on("data", hear);
  child.stderr?.on("data", hear);
  child.on("error", (error) => {
    clearTimeout(timer);
    fail(app, `vexsim didn't start: ${error.message}`, said);
  });
  child.on("exit", (code) => {
    clearTimeout(timer);
    output.appendLine(`vexsim stopped (exit code ${code})`);
    if (apps.get(folder) === app) apps.delete(folder);
    if (app.panel) app.panel.dispose();
    else if (!app.failed) fail(app, `vexsim stopped before it started (exit code ${code})`, said);
  });
}

/** Say why the app didn't start, with the last of what vexsim said. */
async function fail(app, message, said) {
  if (app.failed) return;
  app.failed = true;
  app.process.kill();
  if (apps.get(app.folder) === app) apps.delete(app.folder);
  const last = said.trim().split(/\r?\n/).slice(-2).join(" ");
  lastFailure = last ? `${message}: ${last}` : message;
  const choice = await vscode.window.showErrorMessage(lastFailure, "Show output", "Settings");
  if (choice === "Show output") output.show();
  if (choice === "Settings") vscode.commands.executeCommand("workbench.action.openSettings", "vexsim.python");
}

/** The app's page in a panel beside the editor. */
async function show(context, app, url, token) {
  const local = vscode.Uri.parse(appUrl(url, themeOf(vscode.window.activeColorTheme.kind)));
  const src = (await vscode.env.asExternalUri(local)).toString(true); // its query as it is
  const panel = vscode.window.createWebviewPanel(
    "vexsim",
    `vexsim · ${path.basename(app.folder)}`,
    vscode.ViewColumn.Beside,
    { enableScripts: true, retainContextWhenHidden: true }, // a run goes on while it's hidden
  );
  panel.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "vexsim.png");
  panel.webview.html = panelHtml(src, crypto.randomBytes(16).toString("base64"));
  panel.webview.onDidReceiveMessage((message) => handle(app, message));
  panel.onDidDispose(() => {
    app.process.kill();
    if (apps.get(app.folder) === app) apps.delete(app.folder);
  });
  Object.assign(app, { panel, base: new URL(src).origin, token });
}

/** Do what the app's page asked: it's ready; open a file at a line; save a file; open a page
 * in the browser. */
async function handle(app, message) {
  if (!app || typeof message !== "object" || message === null) return;
  if (message.type === "vexsim.ready") {
    app.ready = true;
  } else if (message.type === "vexsim.open") {
    const at = new vscode.Position(Math.max(0, Number(message.line) - 1 || 0), Math.max(0, Number(message.column) - 1 || 0));
    const column = app.panel?.viewColumn === vscode.ViewColumn.One ? vscode.ViewColumn.Beside : vscode.ViewColumn.One;
    await vscode.window.showTextDocument(vscode.Uri.file(String(message.file)), {
      selection: new vscode.Range(at, at),
      viewColumn: column,
      preview: false,
    });
  } else if (message.type === "vexsim.save") {
    const name = path.basename(String(message.name || "vexsim"));
    const target = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file(path.join(app.folder, name)) });
    if (!target) return;
    await vscode.workspace.fs.writeFile(target, bytes(message.data));
    vscode.window.showInformationMessage(`Saved ${vscode.workspace.asRelativePath(target)}`);
  } else if (message.type === "vexsim.browse") {
    const url = String(message.url);
    if (app.base && url.startsWith(`${app.base}/`)) await vscode.env.openExternal(vscode.Uri.parse(url));
  }
}

/** A saved file's bytes, however they came. */
function bytes(data) {
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  if (ArrayBuffer.isView(data)) return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  return new Uint8Array(0);
}

function stopAll() {
  for (const app of [...apps.values()]) {
    app.panel?.dispose();
    app.process.kill();
  }
  apps.clear();
}

module.exports = { activate, deactivate };
