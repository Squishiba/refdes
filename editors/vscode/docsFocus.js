/**
 * The docs-context focus watcher (DC-4b).
 *
 * Posts the ACTIVE editor's cursor to a local docs-context viewer --
 * `POST <url>/api/focus` with `{"path", "line"}` (DC-4a, the merged server
 * in `tools/docs_context/server.py`) -- so the viewer page follows the
 * author through the file. The setting `refdes.docsContext.url` is the
 * whole feature: empty (the default) means no network call of any kind.
 *
 * Three rules the server side pins and the tests pin harder:
 *   * loopback only (127.0.0.1, localhost, ::1), judged on the URL *host*
 *     so a lookalike like `127.0.0.1.evil.example` is refused: file paths
 *     never leave the machine. A refused host says so once, throttled, in
 *     the output channel -- never a popup.
 *   * the payload is the workspace-relative path and the 1-based cursor
 *     line. Never file contents, never selection text.
 *   * fire-and-forget: every failure is swallowed (at most one throttled
 *     output-channel line per burst), and a post is dropped while one is
 *     in flight -- a slow viewer never stacks requests behind the cursor.
 *
 * Plain CommonJS with no `vscode` import (the host object is injected):
 * like serveClient.js this module stays drivable without an extension
 * host, which is exactly how tests/test_vscode_docs_focus.py drives it.
 */

"use strict";

const http = require("http");
const path = require("path");

/** Cursor moves coalesce into one post per this quiet period. */
const DEBOUNCE_MS = 300;
/** A focus POST that has not answered in this long is a dead viewer. */
const REQUEST_TIMEOUT_MS = 5000;
/** Swallowed failures say themselves at most once per this window. */
const LOG_WINDOW_MS = 1500;
/** The whole allow-list: paths must not leave the machine (§docs-context). */
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "::1"]);

/**
 * Classify the configured url:
 *   - {kind: "off"}     empty/unset -- post nothing, say nothing;
 *   - {kind: "invalid"} not an http:// url with a host -- ignored SILENTLY
 *     (the one output line belongs to "any other host", not to garbage);
 *   - {kind: "refused"} a real host that is not loopback -- never posted;
 *   - {kind: "ok", hostname, port, origin} the target to post to.
 */
function parseFocusUrl(raw) {
  if (typeof raw !== "string") return { kind: "off" };
  const text = raw.trim();
  if (!text) return { kind: "off" };
  let url;
  try {
    url = new URL(text);
  } catch (err) {
    return { kind: "invalid" };
  }
  if (url.protocol !== "http:" || !url.hostname) return { kind: "invalid" };
  // WHATWG keeps brackets on IPv6 hosts; the socket and the allow-list want `::1`.
  const hostname = url.hostname.replace(/^\[(.*)\]$/, "$1");
  if (!LOOPBACK_HOSTS.has(hostname)) return { kind: "refused", host: url.hostname };
  return {
    kind: "ok",
    hostname,
    port: url.port ? Number(url.port) : 80,
    origin: url.origin,
  };
}

/**
 * Build the watcher. `vscode` is the host API (injected for the tests),
 * `getOutput` returns the Refdes output channel lazily -- the channel
 * exists after activate(), not before.
 */
function createDocsFocusWatcher(vscode, getOutput) {
  let timer = null;
  let pending = null; // the pair the running debounce will post
  let lastSentKey = null; // the pair the last dispatched post carried (default 5)
  let inFlight = false; // never stack (default 2's drop rule)
  let lastLogAt = 0;
  let disposed = false;

  function logThrottled(text) {
    const now = Date.now();
    if (now - lastLogAt < LOG_WINDOW_MS) return;
    lastLogAt = now;
    const out = getOutput ? getOutput() : null;
    if (out) out.appendLine("Refdes docs-context: " + text);
  }

  function target() {
    return parseFocusUrl(
      vscode.workspace.getConfiguration("refdes").get("docsContext.url", "")
    );
  }

  /** The fsPath's path relative to the deepest workspace folder containing
   * it, forward-slashed, or null when it is in none -- `..` is then
   * unconstructable and the server's own string comparison is the last
   * gate. */
  function workspaceRelative(fsPath) {
    let best = null;
    for (const folder of vscode.workspace.workspaceFolders || []) {
      const rel = path.relative(folder.uri.fsPath, fsPath);
      const outside =
        !rel ||
        rel === ".." ||
        rel.startsWith(".." + path.sep) ||
        path.isAbsolute(rel);
      if (outside) continue;
      if (best === null || rel.length < best.length) best = rel;
    }
    return best === null ? null : best.split(path.sep).join("/");
  }

  /** The ACTIVE editor's (path, line): the active editor is the source of
   * truth, not the editor the event names -- and a selection event on some
   * other pane must not post that pane's file. Untitled buffers and files
   * outside every workspace folder have nothing to post. */
  function activePair() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return null;
    const document = editor.document;
    if (!document || document.uri.scheme !== "file") return null;
    const rel = workspaceRelative(document.uri.fsPath);
    if (rel === null) return null;
    const line = editor.selection.active.line + 1; // VS Code is 0-based
    return { path: rel, line, key: rel + "\u0000" + line };
  }

  /** Called from onDidChangeTextEditorSelection. Reads everything at event
   * time so clearing the setting takes effect on the very next move. */
  function note() {
    if (disposed) return;
    const url = target();
    if (url.kind === "off" || url.kind === "invalid") return;
    if (url.kind === "refused") {
      logThrottled(
        `refdes.docsContext.url names the non-loopback host "${url.host}" — ` +
          "only 127.0.0.1, localhost and ::1 are honoured, so focus posts are off."
      );
      return;
    }
    const pair = activePair();
    if (!pair || pair.key === lastSentKey) return;
    pending = pair;
    if (timer) clearTimeout(timer);
    timer = setTimeout(flush, DEBOUNCE_MS);
  }

  function flush() {
    timer = null;
    const pair = pending;
    pending = null;
    if (!pair || disposed) return;
    // Re-read the setting: it may have been cleared during the debounce.
    const url = target();
    if (url.kind !== "ok") return;
    if (inFlight) return; // drop; a later cursor move re-posts
    inFlight = true;
    lastSentKey = pair.key;
    post(url, pair);
  }

  function post(url, pair) {
    const body = JSON.stringify({ path: pair.path, line: pair.line });
    let req;
    try {
      req = http.request(
        {
          protocol: "http:",
          hostname: url.hostname,
          port: url.port,
          method: "POST",
          path: "/api/focus",
          headers: {
            "Content-Type": "application/json",
            "X-Docs-Context": "1",
            Origin: url.origin,
            // Explicit: the real server answers a chunked body with 400,
            // and an implicit length is the chunked client's disguise.
            "Content-Length": Buffer.byteLength(body),
          },
        },
        (res) => {
          res.resume();
          inFlight = false;
          if (res.statusCode >= 300) {
            logThrottled(`the focus post to ${url.origin} got ${res.statusCode}`);
          }
        }
      );
    } catch (err) {
      inFlight = false;
      logThrottled("the focus post could not be built");
      return;
    }
    req.setTimeout(REQUEST_TIMEOUT_MS, () => req.destroy());
    // Swallowed by contract: a failure line, never the raw message (an
    // ECONNREFUSED text naming the refused host would read as a refusal),
    // and never a popup.
    req.on("error", () => {
      inFlight = false;
      logThrottled(`the focus post to ${url.origin} failed`);
    });
    req.end(body);
  }

  /** A refdes configuration change: a pending debounce dies with the
   * setting that scheduled it (default 6's "stops posting immediately"),
   * and a re-enabled setting posts the current cursor again. */
  function configChanged() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    pending = null;
    lastSentKey = null;
  }

  function dispose() {
    disposed = true;
    configChanged();
  }

  return { note, configChanged, dispose };
}

module.exports = { createDocsFocusWatcher, parseFocusUrl, DEBOUNCE_MS };
