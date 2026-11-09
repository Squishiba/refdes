/**
 * The Navis write commands (S6.2b of docs/design/navis-vscode-panel-plan.md):
 * the `refdes.navisArchive` / `refdes.navisRestore` / `refdes.navisMint`
 * handlers behind the Navis tree view's context menu and view title, plus
 * S6.3's secondary `refdes.navisOpenInEditor` (the deep link to the browser
 * form) and mint's keyed-file reload note in the log.
 *
 * Plain CommonJS on purpose, the same posture as navisTree.js and
 * serveClient.js: the editor host is INJECTED (`createNavisCommands(deps)`),
 * and nothing here imports the editor host, opens a socket, touches a file
 * or spawns a process -- the whole module is drivable under bare node,
 * which is how tests/test_vscode_navis_commands.py executes it (plan §7.2).
 * It is the RENDERER, not the decider: ./navisActions answers what one
 * POST result means (plan §4's table), and extension.js wires the handlers
 * to the real serve client, the tree's own refresh, and the status bar.
 *
 * Plan §6's security rules are shape rules here: every message shown is a
 * plain string (row and server text are untrusted, so server text passes
 * only through navisActions' sanitiser -- the transport row of plan §4 --
 * never a re-implementation), and the header policy and the launch secret
 * live in serveClient.js alone, so this file never names either.
 */

"use strict";

const navisActions = require("./navisActions");
const navisTree = require("./navisTree");

/**
 * ServeClient's own not-running sentence -- the plain literal its
 * request()/post() resolve as `error` with no live server. It is spelled
 * here, not imported: the client owns its transport strings, and a refused
 * write only needs the author's side of the same words.
 */
const NOT_RUNNING = "refdes serve is not running";

/**
 * Mint splices key bytes into item files (plan §11.1) -- the only
 * body-writing write -- so it asks ONE modal confirmation before the POST,
 * and only the named button proceeds. Archive and Restore are reversible
 * and write no bytes (plan §4), so they ask nothing at all.
 */
const MINT_CONFIRM =
  "Mint keys writes a key into every keyless Navi marker in this project. " +
  "Mint keys now?";
const MINT_BUTTON = "Mint keys";

/**
 * S6.3 "Open in editor": a row with no key has no deep link to open, and
 * nothing went wrong -- there is simply nothing to open -- so it is an
 * INFORMATION naming the missing key, not a warning.
 */
const NO_KEY_OPEN =
  "Refdes: this row has no key -- Mint keys first, then open it in the browser form.";

/**
 * The row a handed-out tree item stands for. The item carries no row field,
 * so it is matched against the last payload by recomputing navisTree's OWN
 * rendered fields -- calling the very functions that built the item, so the
 * two can never drift -- and taking the FIRST row whose rendered quadruple
 * equals the item's (an unset description counts as ""). A placeholder, a
 * null arg (a palette invocation) and a null payload all resolve to no row;
 * the caller refuses those with the shipped generic reason. Under a key6
 * collision two rows render identically and the UI cannot tell their items
 * apart: first match wins, and the selector is always the row's FULL key,
 * so the POST is never ambiguous on the wire.
 */
function rowForItem(item, payload) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return null;
  const rows = payload && Array.isArray(payload.navis) ? payload.navis : [];
  const label = item.label == null ? "" : String(item.label);
  const description = item.description == null ? "" : String(item.description);
  const tooltip = item.tooltip == null ? "" : String(item.tooltip);
  const contextValue = item.contextValue == null ? "" : String(item.contextValue);
  for (const row of rows) {
    if (!row || typeof row !== "object" || Array.isArray(row)) continue;
    if (label !== navisTree.navisLabel(row)) continue;
    if (description !== navisTree.navisDescription(row)) continue;
    if (tooltip !== navisTree.navisTooltip(row)) continue;
    if (contextValue !== navisTree.navisContextValue(row)) continue;
    return row;
  }
  return null;
}

/**
 * The command surface: {archive, restore, mint}, one handler per command,
 * each never throwing. `deps` (every one injected -- the node harness is
 * the reference host):
 *   vscode                       the injected editor host
 *   getClient() -> client | null the live `refdes serve` handle (ServeClient
 *                                shape: .ready, .navisArchive/.navisRestore/.navisMint)
 *   refreshTree() -> Promise     re-renders the tree (its own next GET)
 *   getRows() -> payload | null  the last GET /api/navis payload the tree holds
 *   lock                         a navisActions.createWriteLock() instance
 *   setStatus(text | null)       the status bar's write state
 *   log(line)                    the output-channel sink
 *   openExternal(uri) -> thenable the host's external browser (S6.3, wired
 *                                to vscode.env.openExternal by the wiring)
 *   deepLink(key) -> string|null  the live client's own deep link (S6.3,
 *                                wired to ServeClient.deepLink -- the URL
 *                                and its launch secret are the client's,
 *                                never spelled here)
 */
function createNavisCommands(deps) {
  const window = deps.vscode.window;

  /** The shipped locked reason (it names the server's own launch flag),
   * read from navisActions so the wording can never drift from the rows'. */
  function lockedReason() {
    return navisActions.mintAvailable(null, { writesLocked: true }).tooltip;
  }

  /**
   * Plan §4's transport row as a boundary: a rejected promise is the same
   * event as a request that got no response, so it is fed through
   * planResult's transport case -- a plain string, control characters
   * stripped, capped. Never a stack, never anything the host renders as
   * markup; this is what keeps "a handler never throws" a promise.
   */
  function showError(err) {
    const text = err && err.message ? String(err.message) : String(err);
    window.showErrorMessage(navisActions.planResult({ error: text }).message);
  }

  /**
   * Render the plan §4 decision of one POST result: a success refreshes
   * SILENTLY (`changed:false` included -- a toast per double-click is
   * spam); warn/error show the server's text and refresh when the table
   * says the row set moved; a 403 `refused` locks the session, names the
   * flag on the status bar, warns, and does NOT refresh (the tree is fine,
   * the session is read-only). Returns the decision, so mint can read its
   * own 200's fields after the refresh.
   */
  async function render(result) {
    const d = navisActions.planResult(result);
    if (d.kind === "refresh") {
      await deps.refreshTree();
    } else if (d.kind === "warn") {
      window.showWarningMessage(d.message);
      if (d.refresh) await deps.refreshTree();
    } else if (d.kind === "error") {
      window.showErrorMessage(d.message);
      if (d.refresh) await deps.refreshTree();
    } else {
      deps.lock.lock();
      deps.setStatus(d.message);
      window.showWarningMessage(d.message);
    }
    return d;
  }

  /**
   * Archive and Restore share everything but the verb: locked -> the
   * shipped locked reason, no POST; no server -> ServeClient's own string,
   * no POST; the row's own disabled state (or no row at all) -> the shipped
   * tooltip, no POST; then the POST with the row's FULL key and the plan §4
   * rendering of the answer.
   */
  async function write(kind, item) {
    const writesLocked = deps.lock.locked();
    const state = { writesLocked };
    try {
      if (writesLocked) {
        window.showWarningMessage(navisActions.rowActions(null, state)[kind].tooltip);
        return;
      }
      const client = deps.getClient();
      if (!client || !client.ready) {
        window.showWarningMessage(NOT_RUNNING);
        return;
      }
      const row = rowForItem(item, deps.getRows());
      const action = navisActions.rowActions(row, state)[kind];
      if (!action.enabled) {
        window.showWarningMessage(action.tooltip);
        return;
      }
      const selector = navisActions.selectorFor(row);
      if (!selector) {
        // Enabled action, no key: the rowActions(null) generic refusal --
        // a call the UI must never make, refused the same conservative way.
        window.showWarningMessage(navisActions.rowActions(null, state).archive.tooltip);
        return;
      }
      let result;
      try {
        result = await (kind === "archive"
          ? client.navisArchive(selector)
          : client.navisRestore(selector));
      } catch (err) {
        showError(err);
        return;
      }
      await render(result);
    } catch (err) {
      showError(err);
    }
  }

  /** The mint 200's `still_keyless` (markers the store refused to mint) --
   * the tree refreshes either way; the author is told the mint was partial. */
  function mintStillKeyless(result) {
    const body =
      result && typeof result.body === "object" && result.body !== null
        ? result.body
        : null;
    const value = body ? Number(body.still_keyless) : Number.NaN;
    return Number.isFinite(value) && value > 0 ? value : 0;
  }

  /** The mint 200's `minted` list length -- the count S6.3's log line names
   * (the ANSWER's, not the pill's: a partial mint says what it did). */
  function mintCount(result) {
    const body =
      result && typeof result.body === "object" && result.body !== null
        ? result.body
        : null;
    return body && Array.isArray(body.minted) ? body.minted.length : 0;
  }

  /**
   * Mint, project-wide: the same refusals as the row writes (locked, no
   * server), then mintAvailable -- nothing to mint is an INFORMATION, not a
   * prompt -- then the ONE modal confirmation, then the POST. The refusal
   * order is pinned: the no-server case precedes the nothing-to-mint case.
   */
  async function mint() {
    try {
      if (deps.lock.locked()) {
        window.showWarningMessage(lockedReason());
        return;
      }
      const client = deps.getClient();
      if (!client || !client.ready) {
        window.showWarningMessage(NOT_RUNNING);
        return;
      }
      const availability = navisActions.mintAvailable(deps.getRows(), {
        writesLocked: false,
      });
      if (!availability.enabled) {
        window.showInformationMessage(availability.tooltip);
        return;
      }
      const choice = await window.showWarningMessage(
        MINT_CONFIRM,
        { modal: true },
        MINT_BUTTON
      );
      if (choice !== MINT_BUTTON) return;
      let result;
      try {
        result = await client.navisMint();
      } catch (err) {
        showError(err);
        return;
      }
      const d = await render(result);
      if (d.kind === "refresh") {
        // S6.3's deferred item: the mint touched files under the author's
        // feet (plan §11.1). Clean editors reload from disk; dirty ones get
        // VS Code's own external-change prompt -- say so on the log, once.
        const minted = mintCount(result);
        deps.log(
          `Refdes: minted ${minted} key${minted === 1 ? "" : "s"} -- open ` +
            "editors of those files reload from disk; dirty buffers get VS " +
            "Code's own prompt."
        );
        const left = mintStillKeyless(result);
        if (left > 0) {
          window.showInformationMessage(
            `Refdes: minted keys, but ${left} Navi marker${
              left === 1 ? " is" : "s are"
            } still keyless.`
          );
        }
      }
    } catch (err) {
      showError(err);
    }
  }

  /**
   * S6.3 "Open in editor": hand the author to the row's item in the browser
   * form, through the shipped V0 deep link (plan §5 -- the same
   * `client.deepLink` the CodeLens command opens, and the same
   * server-first refusal order as archive/restore: no server -> ServeClient's
   * own not-running warning, which PRECEDES the keyless refusal). The row is
   * recovered exactly the way the row writes recover it (rowForItem's first
   * match, then selectorFor's FULL key -- never key6); a keyless row, a
   * placeholder and a null arg all land on ONE information naming the
   * missing key, with no link built. The handler composes no URL and opens
   * nothing itself: openExternal receives EXACTLY what deepLink returned,
   * and a throwing deepLink is a plain-string error, never a throw.
   */
  async function openInEditor(item) {
    try {
      const client = deps.getClient();
      if (!client || !client.ready) {
        window.showWarningMessage(NOT_RUNNING);
        return;
      }
      const row = rowForItem(item, deps.getRows());
      const key = navisActions.selectorFor(row);
      if (!key) {
        window.showInformationMessage(NO_KEY_OPEN);
        return;
      }
      await deps.openExternal(deps.deepLink(key));
    } catch (err) {
      showError(err);
    }
  }

  return {
    archive: (item) => write("archive", item),
    restore: (item) => write("restore", item),
    openInEditor: (item) => openInEditor(item),
    mint,
  };
}

module.exports = { createNavisCommands };
