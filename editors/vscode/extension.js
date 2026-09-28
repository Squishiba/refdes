/**
 * Refdes for VS Code.
 *
 * Everything here is a thin client over `refdes index`, which emits the whole
 * project -- items, fields, links, source locations, calc results, coverage, and
 * diagnostics -- as one JSON document without rendering the site. That is why the
 * extension needs no parser of its own and stays in sync with the real tool.
 *
 * Slice V0 (docs/design/editor-vscode-adapter.md §8) adds a second fetch path on
 * purpose, and keeps the choice visible in the status bar (§6 Q3): the facts the
 * live snapshot uniquely provides -- an item's coverage stage, its check state,
 * and the diagnostics attributed to it -- come from `GET /api/item/<ref>` on a
 * `refdes serve` process this window owns. Read-only: nothing here writes an item
 * file (§4), and every mutation the extension could ever make goes through the
 * server, not through `workspace.applyEdit` (§6 Q5).
 *
 * Plain JavaScript on purpose: no build step, so F5 runs it as-is.
 */

"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const fs = require("fs");
const { ServeClient, parseLaunchUrl } = require("./serveClient");

const ID_RE = /\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d{1,6}\b/;
const CALC_FENCE_RE = /^\s*```calc\b/;
const CALC_END_RE = /^\s*```\s*$/;
const ASSIGN_RE = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=]+?)?\s*=/;

/** @type {{root: string, data: any} | null} */
let index = null;
let diagnostics;
let statusBar;
let output;
let calcDecoration;
let showCalcResults = true;
let refreshTimer = null;

/** The one `refdes serve` handle this window has, or null (§3.1: one per project). */
let serve = null;
/** In-flight boot, so two hovers in the same tick spawn one server. */
let serveBoot = null;
/** True once a boot failed; only an explicit command clears it. */
let serveFailed = false;
/** One respawn per window for a 403 — a 403 that survives a respawn is not transient. */
let serveForbiddenRetries = 0;
/** `serial` from the last `GET /api/revision`, or null before the first one. */
let serveSerial = null;
let servePollTimer = null;
let serveStatusBar;

/** How long a hover waits for a booting server before rendering without it. */
const HOVER_SERVE_WAIT_MS = 1500;
/** The snapshot serial is cheap to re-read, and a dead server shows up here. */
const SERVE_POLL_MS = 5000;

// --------------------------------------------------------------------- helpers

function config() {
  return vscode.workspace.getConfiguration("refdes");
}

/** Walk up from a path looking for refdes-project.yaml. */
function findRoot(startPath) {
  let dir = startPath;
  if (fs.existsSync(dir) && fs.statSync(dir).isFile()) dir = path.dirname(dir);
  for (let i = 0; i < 40 && dir; i++) {
    if (fs.existsSync(path.join(dir, "refdes-project.yaml"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function currentRoot() {
  const editor = vscode.window.activeTextEditor;
  if (editor && editor.document.uri.scheme === "file") {
    const found = findRoot(editor.document.uri.fsPath);
    if (found) return found;
  }
  for (const folder of vscode.workspace.workspaceFolders || []) {
    const found = findRoot(folder.uri.fsPath);
    if (found) return found;
  }
  return null;
}

/** Split the configured command into an executable plus fixed arguments. */
function commandParts() {
  const raw = (config().get("command") || "refdes").trim();
  const parts = raw.match(/"[^"]+"|\S+/g) || ["refdes"];
  return parts.map((p) => p.replace(/^"|"$/g, ""));
}

function run(args, root) {
  return new Promise((resolve) => {
    const parts = commandParts();
    const child = cp.spawn(parts[0], parts.slice(1).concat(args), {
      cwd: root,
      shell: process.platform === "win32",
      env: Object.assign({}, process.env, { PYTHONIOENCODING: "utf-8" }),
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.on("error", (err) => resolve({ code: -1, stdout, stderr: String(err) }));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

// ----------------------------------------------------------------------- index

async function refreshIndex(silent) {
  const root = currentRoot();
  if (!root) return;

  const result = await run(["index", "--compact"], root);
  if (result.code !== 0 || !result.stdout.trim()) {
    if (!silent) {
      output.appendLine(result.stderr || "refdes index produced no output");
      output.show(true);
      vscode.window.showErrorMessage(
        "Refdes: could not run the CLI. Check the `refdes.command` setting."
      );
    }
    statusBar.text = "$(error) Refdes";
    statusBar.tooltip = "refdes index failed — see the Refdes output channel";
    return;
  }

  let data;
  try {
    data = JSON.parse(result.stdout);
  } catch (err) {
    output.appendLine("Could not parse index output: " + err);
    return;
  }

  index = { root, data };
  publishDiagnostics(root, data);
  updateStatusBar(data);
  updateCalcDecorations(vscode.window.activeTextEditor);
}

function scheduleRefresh() {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => refreshIndex(true), 250);
}

function updateStatusBar(data) {
  const errors = (data.diagnostics || []).filter((d) => d.level === "error").length;
  const warnings = (data.diagnostics || []).filter((d) => d.level === "warning").length;
  const open = Object.values(data.coverage || {}).filter(
    (c) => c.stage !== "verified"
  ).length;
  statusBar.text = errors
    ? `$(error) Refdes ${errors}`
    : `$(check) Refdes ${data.items.length}`;
  statusBar.tooltip =
    `${data.items.length} items · ${errors} errors · ${warnings} warnings\n` +
    `${open} not yet verified`;
  statusBar.show();
}

function publishDiagnostics(root, data) {
  diagnostics.clear();
  /** @type {Map<string, vscode.Diagnostic[]>} */
  const byFile = new Map();

  for (const d of data.diagnostics || []) {
    // Imported items report a pseudo-path like `<import:platform>`, which is not
    // a file anyone can open.
    if (!d.file || d.file.startsWith("<")) continue;
    const abs = path.isAbsolute(d.file) ? d.file : path.join(root, d.file);
    const line = Math.max(0, (d.line || 1) - 1);
    const range = new vscode.Range(line, 0, line, 200);
    const severity =
      d.level === "error"
        ? vscode.DiagnosticSeverity.Error
        : vscode.DiagnosticSeverity.Warning;
    const message = d.item ? `[${d.item}] ${d.message}` : d.message;
    const diag = new vscode.Diagnostic(range, message, severity);
    diag.source = "refdes";
    if (!byFile.has(abs)) byFile.set(abs, []);
    byFile.get(abs).push(diag);
  }

  for (const [file, list] of byFile) {
    diagnostics.set(vscode.Uri.file(file), list);
  }
}

function itemsById() {
  const map = new Map();
  if (!index) return map;
  for (const item of index.data.items || []) map.set(item.id, item);
  return map;
}

// -------------------------------------------------------------- item rendering

/** Escape the few characters that would change the shape of a Markdown bullet. */
function mdEscape(text) {
  return String(text == null ? "" : text).replace(/([\\`*_\[\]])/g, "\\$1");
}

/**
 * The three facts Slice V0 adds to the hover, all of them read straight out of
 * `GET /api/item/<ref>` and none of them derived here: coverage stage, check
 * state, and the item's own attributed diagnostics (`serve/api.py:_item_view`).
 *
 * The server rolls check state up into `check` (`none` / `pass` / `unknown` /
 * `fail`, `serve/filters.py:check_state`); the hover shows that rollup and the
 * server's own per-check rows stay as they were, rendered from the index.
 */
function appendSnapshotFacts(md, view) {
  const CHECK_ICONS = { pass: "$(check)", fail: "$(error)", unknown: "$(warning)", none: "" };

  md.appendMarkdown("---\n\n");
  const serial = typeof serveSerial === "number" ? ` · snapshot serial ${serveSerial}` : "";
  md.appendMarkdown(`**From \`refdes serve\`**${serial}\n\n`);

  const stage = view.coverage && view.coverage.stage;
  md.appendMarkdown(`- coverage: ${stage ? "`" + stage + "`" : "_no coverage record_"}\n`);

  const state = view.check || "none";
  const icon = CHECK_ICONS[state] === undefined ? "" : CHECK_ICONS[state];
  const count = (view.checks || []).length;
  md.appendMarkdown(`- checks: ${icon} \`${state}\` (${count} check${count === 1 ? "" : "s"})\n`);

  const diags = view.diagnostics || [];
  if (!diags.length) {
    md.appendMarkdown("- no diagnostics attributed to this item\n");
    return;
  }
  md.appendMarkdown(`- ${diags.length} attributed diagnostic${diags.length === 1 ? "" : "s"}:\n`);
  for (const d of diags) {
    const where = d.file ? ` — \`${d.file}${d.line ? ":" + d.line : ""}\`` : "";
    // The build emits three levels (`serve/api.py:_diagnostics_for` copies
    // `Diagnostic.level` straight through), so all three get their own icon
    // rather than an info note wearing a warning's face.
    const level = d.level === "error" ? "$(error)" : d.level === "warning" ? "$(warning)" : "$(info)";
    md.appendMarkdown(`  - ${level} ${mdEscape(d.message)}${where}\n`);
  }
}

/**
 * The hover body.
 *
 * `item` is the index row and is rendered exactly as it always was; `view`, when
 * present, is the live `GET /api/item/<ref>` payload and contributes the extra
 * facts below. When both speak about coverage the snapshot's answer wins, so one
 * hover never shows two different stages for one item (§6 Q3's drift worry).
 */
function itemMarkdown(item, view) {
  const md = new vscode.MarkdownString();
  md.supportThemeIcons = true;
  const typeInfo = (index.data.types || {})[item.type] || {};
  md.appendMarkdown(`**${item.id}** — ${typeInfo.label || item.type}\n\n`);
  md.appendMarkdown(`${item.title}\n\n`);

  const preview = ["status", "limit", "date", "author", "part_number"];
  const rows = [];
  for (const key of preview) {
    const value = item.fields && item.fields[key];
    if (value === undefined || value === null || value === "") continue;
    rows.push(`- \`${key}\`: ${String(value).slice(0, 120)}`);
  }
  if (rows.length) md.appendMarkdown(rows.join("\n") + "\n\n");

  const failing = (item.checks || []).filter((c) => c.ok === false);
  if (failing.length) {
    md.appendMarkdown(`$(error) **check failing**\n\n`);
    for (const c of failing) {
      md.appendMarkdown(`- \`${c.value}\` = ${c.actual} vs ${c.limit} (${c.against})\n`);
    }
    md.appendMarkdown("\n");
  }

  const cov = view ? view.coverage : (index.data.coverage || {})[item.id];
  if (cov) md.appendMarkdown(`_coverage: ${cov.stage}_\n\n`);
  if (item.external) md.appendMarkdown(`_imported from ${item.origin} (read-only)_\n`);

  if (view) appendSnapshotFacts(md, view);
  return md;
}

// ------------------------------------------------------------- the live server

/**
 * Start the project's `refdes serve`, or return the one already running.
 *
 * Lazy by design (§6 Q2): the child exists because a refdes feature was used, not
 * because a window opened, and it is killed on deactivate. One child per resolved
 * project root -- a second window on the same project spawns its own, because
 * finding another process's token is exactly what §3.2 refuses to build.
 */
async function startServe() {
  const root = currentRoot();
  if (!root) {
    setServeState("none", "no refdes-project.yaml found");
    return null;
  }
  const parts = commandParts();
  const client = new ServeClient({
    command: parts[0],
    args: parts.slice(1).concat(["-c", path.join(root, "refdes-project.yaml")]),
    root,
    onLog: logServe,
    onExit: onServeExit,
  });
  serveFailed = false;
  serve = client;
  serveSerial = null;
  setServeState("starting", `spawning \`refdes serve\` in ${root}`);

  serveBoot = client.start();
  const booted = await serveBoot;
  serveBoot = null;
  if (!booted) {
    serveFailed = true;
    setServeState("died", client.error || "the server process exited before it was ready");
    output.show(true);
    const retry = await vscode.window.showErrorMessage(
      "Refdes: could not start `refdes serve`. See the Refdes output channel.",
      "Retry"
    );
    if (retry === "Retry") return startServe();
    return null;
  }
  startServePoll();
  await pollServeRevision();
  return client;
}

/** Like `startServe`, but never boots twice and never throws. */
async function ensureServe() {
  if (serve && serve.ready) return serve;
  if (serveBoot) return serveBoot;
  if (serveFailed) return null;
  return startServe();
}

/**
 * One item view from the live snapshot, or null -- with the boot waited on only
 * as long as a hover can plausibly block. The boot keeps running in the
 * background, so the next hover over the same item gets its facts.
 */
async function serveItemView(ref) {
  const client = await withTimeout(ensureServe(), HOVER_SERVE_WAIT_MS);
  if (!client || !client.ready) return null;
  const res = await client.item(ref);
  if (!res) return null;
  if (res.status !== 200) {
    if (res.status === 403) handleServeForbidden();
    else logServe(`GET /api/item/${ref} -> ${res.status || res.error}`);
    return null;
  }
  return res.body;
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((resolve) => setTimeout(() => resolve(null), ms)),
  ]);
}

function startServePoll() {
  stopServePoll();
  servePollTimer = setInterval(() => pollServeRevision(), SERVE_POLL_MS);
}

function stopServePoll() {
  if (servePollTimer) clearInterval(servePollTimer);
  servePollTimer = null;
}

/**
 * Re-read `GET /api/revision`. This is what keeps "snapshot serial N" honest and
 * what notices the server went away -- an attached server has no process we can
 * watch, so the poll is its liveness check.
 */
async function pollServeRevision() {
  const client = serve;
  if (!client || !client.ready) return;
  const res = await client.revision();
  if (!res || res.error) {
    setServeState("died", (res && res.error) || "no response from the server");
    stopServePoll();
    return;
  }
  if (res.status === 403) {
    handleServeForbidden();
    return;
  }
  if (res.status !== 200) {
    setServeState("died", `GET /api/revision -> ${res.status}`);
    stopServePoll();
    return;
  }
  serveSerial = res.body.serial;
  if (res.body.load_error) logServe(`snapshot could not rebuild: ${res.body.load_error}`);
  setServeState("connected");
}

/**
 * A 403 means the token is from a launch that is already over (§3.2). For a
 * server we spawned, retry the handshake once; for one somebody pasted, there is
 * nothing to retry -- the URL in the box is stale and only they can refresh it.
 */
async function handleServeForbidden() {
  const attached = serve && serve.attached;
  logServe("403 from the server: the launch token is not this server's token");
  stopServePoll();
  setServeState("died", "403 — the launch token is stale");
  if (attached) {
    await vscode.window.showErrorMessage(
      "Refdes: the server at that URL no longer accepts this launch token. " +
        "Run `refdes serve` again and paste its new launch URL.",
      "Attach again"
    );
    return;
  }
  if (serveForbiddenRetries >= 1) {
    vscode.window.showErrorMessage(
      "Refdes: the server keeps refusing this window's launch token. " +
        "See the Refdes output channel."
    );
    return;
  }
  serveForbiddenRetries += 1;
  if (serve) serve.kill();
  serve = null;
  serveFailed = false;
  await startServe();
}

function onServeExit(code, signal, stderr) {
  stopServePoll();
  if (stderr && stderr.trim()) logServe(stderr.trim());
  logServe(`the server process exited (code ${code}${signal ? ", signal " + signal : ""})`);
  setServeState("died", `the server process exited with code ${code}`);
}

async function stopServe() {
  stopServePoll();
  if (serve) serve.kill();
  serve = null;
  serveBoot = null;
  serveSerial = null;
}

function logServe(line) {
  if (output) output.appendLine("[serve] " + line);
}

/**
 * The four states §8 names: no server, starting, snapshot serial N, server died.
 * Each one's detail goes to the output channel, which is one click away because
 * the status bar item's command is `refdes.showServerLog`.
 */
function setServeState(state, detail) {
  if (!serveStatusBar) return;
  const labels = {
    none: "$(circle-slash) Refdes: no server",
    starting: "$(sync~spin) Refdes: starting server",
    connected:
      typeof serveSerial === "number"
        ? `$(check) Refdes: snapshot ${serveSerial}`
        : "$(check) Refdes: connected",
    died: "$(error) Refdes: server died",
  };
  const text = labels[state] || labels.none;
  if (detail) logServe(`${text.replace(/\$\([^)]*\)\s*/, "")} — ${detail}`);
  serveStatusBar.text = text;
  serveStatusBar.tooltip =
    `Refdes: ${text.replace(/\$\([^)]*\)\s*/, "")}\n` +
    (detail ? detail + "\n" : "") +
    (state === "connected"
      ? "Hover an item id for its snapshot facts."
      : "Hover an item id, or run Refdes: Attach to running server.") +
    "\nClick to show the Refdes output channel.";
  serveStatusBar.show();
}

// ------------------------------------------------------------------- providers

const hoverProvider = {
  async provideHover(document, position) {
    if (!index) return null;
    const range = document.getWordRangeAtPosition(position, ID_RE);
    if (!range) return null;
    const id = document.getText(range);
    const item = itemsById().get(id);
    if (!item) return null;
    // The index hover is still the body of it; the snapshot adds three facts and
    // is deliberately awaited last, with a timeout, so a booting server can never
    // make a hover hang.
    const view = await serveItemView(id);
    return new vscode.Hover(itemMarkdown(item, view), range);
  },
};

/**
 * One CodeLens per item's own `id:` line. The key for the deep link comes from
 * the index row when it has one and from the item view otherwise; either way the
 * URL is the server's own `/edit/#/items/<key>`, never a form the extension
 * builds itself (§3.3).
 */
const codeLensProvider = {
  provideCodeLenses(document) {
    if (!index) return [];
    const byId = itemsById();
    const lenses = [];
    for (let i = 0; i < document.lineCount; i++) {
      const match = document.lineAt(i).text.match(/^\s*(?:-\s*)?id:\s*(\S+)\s*$/);
      if (!match) continue;
      const item = byId.get(match[1]);
      if (!item) continue;
      lenses.push(
        new vscode.CodeLens(new vscode.Range(i, 0, i, document.lineAt(i).text.length), {
          title: "Open in editor",
          command: "refdes.openInEditor",
          arguments: [{ id: item.id, key: item.key || null }],
          tooltip: "Open this item in the refdes browser editor",
        })
      );
    }
    return lenses;
  },
};

const definitionProvider = {
  provideDefinition(document, position) {
    if (!index) return null;
    const range = document.getWordRangeAtPosition(position, ID_RE);
    if (!range) return null;
    const item = itemsById().get(document.getText(range));
    if (!item || !item.source || !item.source.file || item.external) return null;
    const target = path.join(index.root, item.source.file);
    const line = Math.max(0, (item.source.line || 1) - 1);
    return new vscode.Location(vscode.Uri.file(target), new vscode.Position(line, 0));
  },
};

const completionProvider = {
  provideCompletionItems(document, position) {
    if (!index) return null;
    const line = document.lineAt(position.line).text;
    const before = line.slice(0, position.character);

    // Offer enum values right after `status: `, `verdict: `, and friends.
    const fieldMatch = before.match(/(?:^|[\s\-\[])([a-z_]+):\s*([A-Za-z_-]*)$/);
    if (fieldMatch) {
      const values = enumChoicesFor(fieldMatch[1]);
      if (values.length) {
        return values.map((v) => {
          const c = new vscode.CompletionItem(v, vscode.CompletionItemKind.EnumMember);
          c.detail = fieldMatch[1];
          return c;
        });
      }
    }

    // Offer field/link key names at the start of a front-matter line, once
    // the current item's type is known from context -- the gap yaml-
    // language-server can't close for .md front matter (vscode-yaml#207),
    // and .refdes/schema.json's own freshness plays no part here: this
    // reuses index.data.types, the same payload enumChoicesFor already
    // reads on every refresh.
    const keyMatch = before.match(/^(\s*(?:-\s*)?)([a-z_]*)$/);
    if (keyMatch) {
      const typeName = itemTypeAtLine(document, position.line);
      const spec = typeName && index.data.types && index.data.types[typeName];
      if (spec) {
        const fieldKeys = Object.keys(spec.fields || {});
        const linkKeys = Object.keys(spec.links || {});
        const items = fieldKeys
          .map((k) => {
            const fspec = spec.fields[k] || {};
            const c = new vscode.CompletionItem(k, vscode.CompletionItemKind.Field);
            c.detail = fspec.type;
            // A `doc:` definition from the schema (finding 38), when declared.
            if (fspec.doc) c.documentation = fspec.doc;
            c.insertText = `${k}: `;
            return c;
          })
          .concat(
            linkKeys.map((k) => {
              const c = new vscode.CompletionItem(k, vscode.CompletionItemKind.Reference);
              c.detail = `link -> ${(spec.links[k] || []).join(", ") || "any"}`;
              c.insertText = `${k}: `;
              return c;
            })
          );
        if (items.length) return items;
      }
    }

    // Otherwise offer item IDs, after `[[` or once a prefix with its hyphen has
    // been typed. Requiring the hyphen keeps completions out of ordinary prose --
    // "PCB" and "TODO" should not pop a list, but "REQ-" should.
    const trigger =
      before.match(/\[\[([A-Za-z0-9\-_]*)$/) ||
      before.match(/\b([A-Z][A-Z0-9]*-[A-Z0-9\-]*)$/);
    if (!trigger) return null;

    return (index.data.items || []).map((item) => {
      const c = new vscode.CompletionItem(item.id, vscode.CompletionItemKind.Reference);
      c.detail = item.title;
      c.documentation = itemMarkdown(item);
      // Finding 8: narrow by the file an item lives in, or its board, not
      // just the id and title -- "power" matches an item declared in
      // power.yaml even before its id is remembered. Both are already in
      // the index payload (items_json() emits source: {file, line} and
      // board: unconditionally on each item), so this is a filter-text
      // change only, no new data to export.
      const sourceFile = (item.source && item.source.file) || "";
      c.filterText = `${item.id} ${item.title} ${sourceFile} ${item.board || ""}`.trim();
      return c;
    });
  },
};

function enumChoicesFor(fieldName) {
  const seen = new Set();
  for (const type of Object.values((index && index.data.types) || {})) {
    const spec = (type.fields || {})[fieldName];
    if (spec && Array.isArray(spec.choices)) spec.choices.forEach((c) => seen.add(c));
  }
  return [...seen];
}

// ------------------------------------------------------------ calc decorations

/**
 * Which item owns a given line.
 *
 * Tracks the most recent `id:` line at or before `targetLine`: a `- id:` entry
 * in a list file, or an item's own front-matter in a .md file -- including a
 * multi-item .md file, where a later item's front-matter simply overrides the
 * one before it as the scan reaches it.
 */
function itemIdAtLine(document, targetLine) {
  let current = null;
  for (let i = 0; i <= targetLine; i++) {
    const text = document.lineAt(i).text;
    const match = text.match(/^\s*(?:-\s*)?id:\s*(\S+)\s*$/);
    if (match) current = match[1];
  }
  return current;
}

// Same scan as itemIdAtLine, tracking `type:` instead of `id:` -- what the
// key-completion trigger in completionProvider needs to know which type's
// fields/links to offer.
function itemTypeAtLine(document, targetLine) {
  let current = null;
  for (let i = 0; i <= targetLine; i++) {
    const text = document.lineAt(i).text;
    const match = text.match(/^\s*(?:-\s*)?type:\s*(\S+)\s*$/);
    if (match) current = match[1];
  }
  return current;
}

function updateCalcDecorations(editor) {
  if (!editor || !calcDecoration) return;
  if (!index || !showCalcResults) {
    editor.setDecorations(calcDecoration, []);
    return;
  }

  const document = editor.document;
  const byId = itemsById();
  const decorations = [];
  let inCalc = false;

  for (let i = 0; i < document.lineCount; i++) {
    const text = document.lineAt(i).text;

    if (!inCalc) {
      if (CALC_FENCE_RE.test(text)) inCalc = true;
      continue;
    }
    if (CALC_END_RE.test(text)) {
      inCalc = false;
      continue;
    }

    const stripped = text.split("#")[0];
    const assign = stripped.match(ASSIGN_RE);
    if (!assign) continue;

    const item = byId.get(itemIdAtLine(document, i));
    if (!item) continue;
    // Match by source line, not by name: two calc blocks in the same item can
    // assign the same name (refdes now rejects that at build time, but an
    // unbuilt or stale-index document can still show it), and `.find()` by
    // name alone always grabbed the first one, decorating every later
    // same-named line with the first line's stale result. `line` is 1-indexed
    // from `refdes index`; `i` here is 0-indexed.
    const calc = (item.calcs || []).find((c) => c.line === i + 1);
    if (!calc) continue;

    const label = calc.error
      ? `  ⚠ ${calc.error}`
      : `  → ${calc.result}${calc.bounds ? "   " + calc.bounds : ""}`;

    decorations.push({
      range: new vscode.Range(i, text.length, i, text.length),
      renderOptions: {
        after: {
          contentText: label,
          color: new vscode.ThemeColor(
            calc.error ? "editorError.foreground" : "editorCodeLens.foreground"
          ),
          fontStyle: "italic",
        },
      },
    });
  }

  editor.setDecorations(calcDecoration, decorations);
}

// -------------------------------------------------------------------- commands

async function runVisible(args, message) {
  const root = currentRoot();
  if (!root) {
    vscode.window.showWarningMessage("Refdes: no refdes-project.yaml found.");
    return null;
  }
  output.clear();
  output.appendLine(`$ refdes ${args.join(" ")}`);
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: message },
    () => run(args, root)
  );
  output.appendLine(result.stdout);
  if (result.stderr) output.appendLine(result.stderr);
  await refreshIndex(true);
  return result;
}

async function commandBuild() {
  const result = await runVisible(["build", "--keep-going"], "Refdes: building…");
  if (!result) return;
  if (result.code !== 0) output.show(true);
  else vscode.window.setStatusBarMessage("Refdes: build complete", 3000);
}

async function commandCheck() {
  const result = await runVisible(["check"], "Refdes: checking…");
  if (result && result.code !== 0) output.show(true);
}

async function commandAllocateIds() {
  await runVisible(["id"], "Refdes: allocating IDs…");
  output.show(true);
}

async function commandOpenPreview() {
  const root = currentRoot();
  if (!root) return;
  const candidate = path.join(root, "_site", "index.html");
  if (!fs.existsSync(candidate)) {
    const choice = await vscode.window.showInformationMessage(
      "No built site found. Build it now?",
      "Build"
    );
    if (choice === "Build") await commandBuild();
    if (!fs.existsSync(candidate)) return;
  }
  vscode.env.openExternal(vscode.Uri.file(candidate));
}

function commandToggleCalcResults() {
  showCalcResults = !showCalcResults;
  updateCalcDecorations(vscode.window.activeTextEditor);
  vscode.window.setStatusBarMessage(
    `Refdes: inline calc results ${showCalcResults ? "on" : "off"}`,
    2000
  );
}

/**
 * The one deep link Slice V0 adds: this item's form in the browser editor, in
 * the system's external browser. Nothing here renders a form or a webview -- the
 * server owns that surface, and this hands the author to it (§3.3).
 */
async function commandOpenInEditor(target) {
  const id = target && target.id;
  if (!id) {
    vscode.window.showInformationMessage(
      "Refdes: run this from an item's own `id:` line, using its Open in editor CodeLens."
    );
    return;
  }
  const client = await ensureServe();
  if (!client || !client.ready) return; // startServe already said why, loudly

  let key = target.key;
  if (!key) {
    const res = await client.item(id);
    if (!res || res.status !== 200) {
      vscode.window.showErrorMessage(
        `Refdes: the server has no item ${id} (${res ? res.status : "no response"}).`
      );
      return;
    }
    key = res.body.key || res.body.handle;
  }
  if (!key) {
    vscode.window.showErrorMessage(
      `Refdes: ${id} has no key yet, so there is nothing to open. Run \`refdes build\` to mint one.`
    );
    return;
  }
  logServe(`opening ${client.deepLinkForLog(key)}`);
  const opened = await vscode.env.openExternal(vscode.Uri.parse(client.deepLink(key)));
  if (!opened) {
    vscode.window.showWarningMessage(
      "Refdes: VS Code could not open a browser for the editor URL."
    );
  }
}

/**
 * §3.2 option 2: attach to a `refdes serve` the author started themselves. Zero
 * server change makes this work -- the token is already in the printed URL.
 */
async function commandAttachServer() {
  const url = await vscode.window.showInputBox({
    title: "Refdes: attach to a running server",
    prompt:
      "Paste the launch URL `refdes serve` printed in your terminal. " +
      "Its token stays in this window's memory.",
    placeHolder: "http://127.0.0.1:54321/?token=…",
    ignoreFocusOut: true,
    validateInput: (value) =>
      parseLaunchUrl(value || "")
        ? null
        : "Expected the launch URL `refdes serve` printed, including its ?token=… part.",
  });
  if (!url) return;
  const parsed = parseLaunchUrl(url);
  if (!parsed) {
    vscode.window.showErrorMessage("Refdes: that is not a refdes launch URL.");
    return;
  }

  await stopServe();
  serveFailed = false;
  serve = ServeClient.attach(parsed, { onLog: logServe });
  logServe(
    `attached to ${parsed.base}` +
      (parsed.normalizedFromLocalhost
        ? " (localhost rewritten to 127.0.0.1: the server binds IPv4 only)"
        : "")
  );
  setServeState("connected");
  startServePoll();
  await pollServeRevision();
}

function commandShowServerLog() {
  output.show(true);
}

// ------------------------------------------------------------------ activation

function activate(context) {
  output = vscode.window.createOutputChannel("Refdes");
  diagnostics = vscode.languages.createDiagnosticCollection("refdes");
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.command = "refdes.check";
  serveStatusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 90);
  serveStatusBar.command = "refdes.showServerLog";
  calcDecoration = vscode.window.createTextEditorDecorationType({});
  showCalcResults = config().get("showCalcResults") !== false;

  vscode.commands.executeCommand("setContext", "refdes.active", true);

  const selector = [
    { language: "markdown", scheme: "file" },
    { language: "yaml", scheme: "file" },
  ];

  context.subscriptions.push(
    output,
    diagnostics,
    statusBar,
    serveStatusBar,
    calcDecoration,
    vscode.commands.registerCommand("refdes.build", commandBuild),
    vscode.commands.registerCommand("refdes.check", commandCheck),
    vscode.commands.registerCommand("refdes.allocateIds", commandAllocateIds),
    vscode.commands.registerCommand("refdes.openPreview", commandOpenPreview),
    vscode.commands.registerCommand("refdes.refreshIndex", () => refreshIndex(false)),
    vscode.commands.registerCommand(
      "refdes.toggleCalcResults",
      commandToggleCalcResults
    ),
    vscode.commands.registerCommand("refdes.attachServer", commandAttachServer),
    vscode.commands.registerCommand("refdes.openInEditor", commandOpenInEditor),
    vscode.commands.registerCommand("refdes.showServerLog", commandShowServerLog),
    vscode.languages.registerHoverProvider(selector, hoverProvider),
    vscode.languages.registerCodeLensProvider(selector, codeLensProvider),
    vscode.languages.registerDefinitionProvider(selector, definitionProvider),
    vscode.languages.registerCompletionItemProvider(selector, completionProvider, "[", "-"),
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (!config().get("checkOnSave")) return;
      if (!/\.(md|ya?ml)$/.test(doc.fileName)) return;
      scheduleRefresh();
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) =>
      updateCalcDecorations(editor)
    ),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("refdes")) {
        showCalcResults = config().get("showCalcResults") !== false;
        refreshIndex(true);
      }
    })
  );

  setServeState("none", "no server started yet for this window");
  refreshIndex(true);
}

function deactivate() {
  if (refreshTimer) clearTimeout(refreshTimer);
  // The child is ours, so it dies with the extension host (§3.1). Its token dies
  // with it: nothing about a launch outlives the launch (§3.2 row 5).
  stopServe();
}

module.exports = { activate, deactivate };
