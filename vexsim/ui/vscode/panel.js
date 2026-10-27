// @ts-check
// The panel's page and what the extension works out without VS Code (tested by Vitest in
// frontend/tests/vscode.test.ts).

/** The app's address in what `vexsim ui` prints: the URL, its origin and the token. */
function findUrl(text) {
  const match = /http:\/\/127\.0\.0\.1:(\d+)\/\?token=([\w-]+)/.exec(text);
  if (!match) return null;
  return { url: match[0], base: `http://127.0.0.1:${match[1]}`, token: match[2] };
}

/** The address the panel opens: the app's, saying it's in VS Code and in which colors. */
function appUrl(url, theme) {
  return `${url}&embed=vscode&theme=${theme}`;
}

/** Light or dark, from VS Code's ColorThemeKind (1 light, 2 dark, 3 high contrast, 4 high
 * contrast light). */
function themeOf(kind) {
  return kind === 1 || kind === 4 ? "light" : "dark";
}

/** The program to run vexsim with: the Python configured; on Windows its pythonw.exe when
 * there is one, so no console windows open for the processes vexsim starts. */
function runWith(python, platform, exists) {
  if (platform !== "win32" || !/python\.exe$/i.test(python)) return python;
  const windowless = python.replace(/python\.exe$/i, "pythonw.exe");
  return exists(windowless) ? windowless : python;
}

const escapeHtml = (text) =>
  String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** The panel's page: the app in a frame filling it. The page says hello to the app once it
 * has loaded and tells it when VS Code's colors change; what the app says, it passes on to
 * the extension. */
function panelHtml(src, nonce) {
  const origin = new URL(src).origin;
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src ${origin}; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
<style nonce="${nonce}">
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; }
  #status { position: absolute; inset: 0; display: grid; place-items: center; color: var(--vscode-descriptionForeground); font-family: var(--vscode-font-family); }
  iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
</style>
</head>
<body>
<div id="status">Starting vexsim…</div>
<iframe id="app" title="vexsim" src="${escapeHtml(src)}" allow="clipboard-read; clipboard-write; gamepad; fullscreen"></iframe>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const frame = document.getElementById("app");
  const origin = ${JSON.stringify(origin)};
  const classes = document.body.classList;
  const theme = () => (classes.contains("vscode-light") || classes.contains("vscode-high-contrast-light") ? "light" : "dark");
  const say = (message) => frame.contentWindow.postMessage(message, origin);
  frame.addEventListener("load", () => say({ type: "vexsim.host", theme: theme() }));
  new MutationObserver(() => say({ type: "vexsim.theme", theme: theme() })).observe(document.body, { attributes: true, attributeFilter: ["class"] });
  window.addEventListener("message", (event) => {
    if (event.source !== frame.contentWindow || event.origin !== origin) return;
    if (event.data && event.data.type === "vexsim.ready") document.getElementById("status")?.remove();
    vscode.postMessage(event.data);
  });
</script>
</body>
</html>`;
}

module.exports = { appUrl, findUrl, panelHtml, runWith, themeOf };
