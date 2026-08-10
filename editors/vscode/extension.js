/**
 * Refdes for VS Code.
 *
 * Everything here is a thin client over `refdes index`, which emits the whole
 * project -- items, fields, links, source locations, calc results, coverage, and
 * diagnostics -- as one JSON document without rendering the site. That is why the
 * extension needs no parser of its own and stays in sync with the real tool.
 *
 * Plain JavaScript on purpose: no build step, so F5 runs it as-is.
 */

"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const path = require("path");
const fs = require("fs");

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

// --------------------------------------------------------------------- helpers

function config() {
  return vscode.workspace.getConfiguration("refdes");
}

/** Walk up from a path looking for refdes.yaml. */
function findRoot(startPath) {
  let dir = startPath;
  if (fs.existsSync(dir) && fs.statSync(dir).isFile()) dir = path.dirname(dir);
  for (let i = 0; i < 40 && dir; i++) {
    if (fs.existsSync(path.join(dir, "refdes.yaml"))) return dir;
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

function itemMarkdown(item) {
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

  const cov = (index.data.coverage || {})[item.id];
  if (cov) md.appendMarkdown(`_coverage: ${cov.stage}_\n\n`);
  if (item.external) md.appendMarkdown(`_imported from ${item.origin} (read-only)_\n`);
  return md;
}

// ------------------------------------------------------------------- providers

const hoverProvider = {
  provideHover(document, position) {
    if (!index) return null;
    const range = document.getWordRangeAtPosition(position, ID_RE);
    if (!range) return null;
    const item = itemsById().get(document.getText(range));
    if (!item) return null;
    return new vscode.Hover(itemMarkdown(item), range);
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
      c.filterText = `${item.id} ${item.title}`;
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
 * A .md file is one item, so its front-matter id covers everything. A list file
 * holds many, so each `- id:` starts a region that runs to the next one.
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
    const calc = (item.calcs || []).find((c) => c.name === assign[1]);
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
    vscode.window.showWarningMessage("Refdes: no refdes.yaml found.");
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

// ------------------------------------------------------------------ activation

function activate(context) {
  output = vscode.window.createOutputChannel("Refdes");
  diagnostics = vscode.languages.createDiagnosticCollection("refdes");
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.command = "refdes.check";
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
    vscode.languages.registerHoverProvider(selector, hoverProvider),
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

  refreshIndex(true);
}

function deactivate() {
  if (refreshTimer) clearTimeout(refreshTimer);
}

module.exports = { activate, deactivate };
