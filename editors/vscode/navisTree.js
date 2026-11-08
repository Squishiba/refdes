/**
 * The read-only Navis tree (S6.1 of docs/design/navis-vscode-panel-plan.md).
 *
 * Plain CommonJS on purpose, and deliberately free of any editor-host import,
 * a fetch of any kind, and any file access: like serveClient.js and
 * docsFocus.js, everything in here is drivable under bare node, which is how
 * tests/test_vscode_navis_tree.py executes this mapping (plan §7.2). The
 * host is INJECTED into `createNavisTree(vscode)` -- the same posture as
 * docsFocus.js's createDocsFocusWatcher.
 *
 * The module turns one `GET /api/navis` payload (the panel rows the site and
 * preview panels render, plan §3) into tree rows: labels, descriptions,
 * tooltips, context values, the badge count, the click-through target, and
 * the four placeholder states. It renders; it never fetches and never writes
 * (S6.1 is the read-only half; the actions are S6.2).
 *
 * §6's security rule lives in the shape of the API: every string here is a
 * plain string built from row fields -- label, description and tooltip are
 * never markdown, so untrusted Navi text renders literally and a payload can
 * never name a command. The launch secret lives in ServeClient and never
 * enters this file; nothing here reads or renders anything like it.
 */

"use strict";

const path = require("path");

/**
 * Tree labels truncate for display at this many characters (plan §6: the
 * hover's field-row precedent, extension.js's `slice(0, 120)`). Length is a
 * legibility choice; the full text lives in the plain-string tooltip.
 */
const TEXT_LIMIT = 120;

function truncateText(text, limit = TEXT_LIMIT) {
  const s = String(text == null ? "" : text);
  return s.length > limit ? s.slice(0, limit) + "..." : s;
}

function isKeyless(row) {
  return !row.key;
}

/** `key6 · text` for a keyed row; a keyless row has no key6 to spell. */
function navisLabel(row) {
  const text = truncateText(row.text);
  return isKeyless(row) ? text : `${row.key6} · ${text}`;
}

/**
 * The disabled-state notes, each mirroring a shipped panel (plan §4): the
 * orphan is what `refdes navis` labels "marker not found", the keyless row
 * is the preview panel's KEYLESS_TITLE. A plain row carries no note.
 */
function navisDescription(row) {
  if (row.orphan) return "marker not found";
  if (isKeyless(row)) return "No key yet -- use Mint keys";
  return "";
}

/** The full untruncated text, plus the state note when there is one. */
function navisTooltip(row) {
  const note = navisDescription(row);
  const text = String(row.text == null ? "" : row.text);
  return note ? `${text} -- ${note}` : text;
}

/**
 * Space-separated context-value words for S6.2's menus (plan §4): the base
 * id first, then the archived/keyless state words.
 */
function navisContextValue(row) {
  const parts = ["refdesNavi"];
  if (row.archived) parts.push("refdesNaviArchived");
  if (isKeyless(row)) parts.push("refdesNaviKeyless");
  return parts.join(" ");
}

/** The view badge shows the active count (plan checklist 1). */
function navisBadge(payload) {
  return payload.counts.active;
}

/**
 * The click-through target, the definitionProvider's arithmetic (plan §5):
 * join the project root with the row's file and land on line - 1 (0-based
 * for the editor, clamped at 0). An orphan row keeps the record's snapshot
 * location, so the same arithmetic applies. No file, no target.
 */
function navisOpenTarget(row, root) {
  if (!root || !row.file) return null;
  return { file: path.join(root, row.file), line: Math.max(0, row.line - 1) };
}

/**
 * The provider surface the extension's tree wiring is written against.
 * `vscode` is injected, never imported (see the header).
 */
function createNavisTree(vscode) {
  /** What each handed-out "Show all" group stands for: rows + the root they
   * were rendered against, so its children get the same click-through. */
  const groups = new Map();

  function itemForRow(row, root) {
    const item = new vscode.TreeItem(navisLabel(row));
    const desc = navisDescription(row);
    if (desc) item.description = desc;
    item.tooltip = navisTooltip(row);
    item.contextValue = navisContextValue(row);
    const target = navisOpenTarget(row, root);
    if (target) {
      item.command = {
        command: "vscode.open",
        arguments: [
          vscode.Uri.file(target.file),
          {
            selection: {
              start: { line: target.line, character: 0 },
              end: { line: target.line, character: 0 },
            },
          },
        ],
      };
    }
    return item;
  }

  /** Top level: the active rows in the projection's order, then -- only when
   * archived rows exist -- one collapsed group for them. */
  function childrenFor(payload, root) {
    const rows = payload.navis || [];
    const items = rows.filter((row) => !row.archived).map((row) => itemForRow(row, root));
    const archived = rows.filter((row) => row.archived);
    if (archived.length) {
      const group = new vscode.TreeItem(
        `Show all (${archived.length}) archived`,
        vscode.TreeItemCollapsibleState.Collapsed
      );
      groups.set(group, { rows: archived, root });
      items.push(group);
    }
    return items;
  }

  /** The children of a handed-out group, in the projection's order. Any
   * other item (a row, a placeholder) is a leaf. */
  function childrenOf(item) {
    const group = groups.get(item);
    if (!group) return [];
    return group.rows.map((row) => itemForRow(row, group.root));
  }

  /** The four states the tree fails loudly with (plan §3/§5, checklist 6,
   * ratified Q7), each a plain-string leaf item. */
  function placeholderFor(state) {
    const labels = {
      "no-project": "No refdes-project.yaml found.",
      "no-server": "No server -- hover an item, or run Refdes: Attach to running server",
      "server-died": "Refdes: server died -- run Refdes: Attach to running server",
      "no-navis": "No Navis in this project",
    };
    return new vscode.TreeItem(labels[state]);
  }

  return {
    itemForRow,
    childrenFor,
    childrenOf,
    placeholderFor,
    badgeFor: navisBadge,
  };
}

module.exports = {
  TEXT_LIMIT,
  truncateText,
  navisLabel,
  navisDescription,
  navisTooltip,
  navisContextValue,
  navisBadge,
  navisOpenTarget,
  createNavisTree,
};
