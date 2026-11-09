/**
 * The decision logic of the Navis write actions (S6.2 of
 * docs/design/navis-vscode-panel-plan.md): what one `ServeClient.post()`
 * result MEANS, which row actions are enabled and why not, the selector a
 * command POSTs, the Mint pill, and the session write-lock a 403 `refused`
 * flips.
 *
 * Plain CommonJS on purpose, like navisTree.js and serveClient.js: no
 * editor-host import, no transport, no files, no child processes -- the
 * whole module is drivable under bare node, which is how
 * tests/test_vscode_navis_actions.py executes it (plan §7.2). It is the
 * ANSWERER, not the caller: ServeClient.post() fetches, planResult()
 * decides, extension.js (S6.2b-2) renders.
 *
 * Plan §6's security rule lives in the shape of the API: every string here
 * is a plain string, and the server's text passes through verbatim except
 * for one sanitisation (control characters removed, 300-char cap) -- an
 * untrusted `error`/candidate text stays an inert plain string, never
 * markup. The module never names the launch secret, the header policy, or
 * any request detail: those live in serveClient.js, and the decision layer
 * must not grow a second copy of either.
 */

"use strict";

/** The server's text is passed through, stripped of control characters
 * (C0, DEL and C1 -- the C1 range includes NEL, U+0085, which has no
 * business in a UI string) and capped at 300 by default: a hostile
 * 5000-char `error` must not flood a toast. */
const MESSAGE_LIMIT = 300;

/** A candidate's text is capped at this many characters (with a `...`
 * marker) INSIDE the composed 409-ambiguous message -- the message itself
 * is not capped, so a collision with many candidates loses none of them
 * (the author must be able to pick one). */
const CANDIDATE_TEXT_LIMIT = 80;

/** At most this many candidates are named; the rest are counted in a
 * `(+N more)` tail. A real 409 is a key6 collision (a handful); the bound
 * keeps a fabricated payload from composing an unbounded string. */
const CANDIDATE_LIMIT = 20;

/** The shipped panels' disabled-state wordings, verbatim (plan §4: each
 * mirrors a shipped panel, docs/navis.md "The served preview panel"). The
 * keyless line is navisTree.js's `navisDescription` string (pinned equal by
 * tests/test_vscode_navis_actions.py against both files); the orphan line is
 * navis-panel.js's ORPHAN_TITLE. */
const KEYLESS_HINT = "No key yet -- use Mint keys";
const ORPHAN_HINT =
  "Marker not found -- hand-restore the marker, then it re-links by key";

/** A locked session's reason: the server answers 403 `kind:"refused"`
 * naming its own `--no-write` launch; every write action says so. */
const LOCKED_HINT =
  "This server runs with --no-write: writes are disabled for this session";

/** plan §4's 409 `conflict` reasons -> the refresh column of the table. The
 * message is always the store's own text (verbatim), so it lives here only
 * as the set of names the table's rows occupy. */
const CONFLICT_REFRESH = {
  keyless: false,
  not_archived: true,
  orphan: false,
  journal_pending: false,
};

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Control characters (C0, DEL, C1) have no business in a UI string. */
function stripControls(text) {
  return String(text == null ? "" : text).replace(/[\u0000-\u001f\u007f-\u009f]/g, "");
}

/** Pass the server's text through: stripped of control characters, capped
 * at `limit`. Applied to every message this module emits. */
function sanitize(text, limit = MESSAGE_LIMIT) {
  const stripped = stripControls(text);
  return stripped.length > limit ? stripped.slice(0, limit) : stripped;
}

function decision(kind, refresh, lockWrites, message) {
  return { kind, refresh, lockWrites, message };
}

/** The safe-by-default answer for any result the plan §4 table does not
 * name. Names the status (the author needs to know WHICH answer arrived),
 * never the body: an unnamed body is untrusted text and may be an HTML
 * gateway page, so it is not echoed. */
function unhandled(status) {
  return decision(
    "error",
    false,
    false,
    sanitize(
      `refdes serve answered ${status} with a response this client does not recognise`
    )
  );
}

/** The server's own `error` text when a body carries one. */
function serverText(body) {
  return typeof body.error === "string" ? body.error : null;
}

/**
 * The plan §4 table keyed the way the table is written: on `kind`/`reason`
 * (and the status that scopes them), NOT on the presence of an `error`
 * string. A named row answers with its behavioral flags even when its text
 * is missing (the message falls back to a safe generic) -- a lock never
 * degrades to a warn because a server forgot to phrase its refusal. null
 * for every result the table does not name.
 */
function tableRow(status, body) {
  if (!isPlainObject(body)) return null;
  if (status === 200) {
    // Any 200 with an object body is a success; `changed:false` is a SILENT
    // one (a re-archive is a no-op, and a toast per double-click is spam).
    // The 200's fields (verb/key/changed, or mint's minted[]) are the
    // caller's business -- planResult must not read them: mint's 200
    // carries no verb/key at all.
    return { kind: "refresh", refresh: true, lockWrites: false };
  }
  if (status === 400 && body.kind === "bad_request") {
    // A bug in the client -- loud per plan §3.2's rule, with the server's text.
    return { kind: "error", refresh: false, lockWrites: false };
  }
  if (status === 403 && body.kind === "refused") {
    // The --no-write refusal (gate-first, JSON body): lock writes for the
    // session. A 403 WITHOUT the JSON `kind:"refused"` is the security
    // layer's plain-text refusal -- a launch-secret problem, NOT the
    // read-only lock -- and falls through to the generic error below,
    // never a lock (plan §3's stale-secret case).
    return { kind: "lock", refresh: false, lockWrites: true };
  }
  if (status === 404 && body.kind === "not_found") {
    // The row set moved under us (ordinals); refresh, the number may be
    // valid now.
    return { kind: "warn", refresh: true, lockWrites: false };
  }
  if (status === 409 && body.kind === "ambiguous") {
    return { kind: "warn", refresh: false, lockWrites: false };
  }
  if (
    status === 409 &&
    body.kind === "conflict" &&
    Object.prototype.hasOwnProperty.call(CONFLICT_REFRESH, body.reason)
  ) {
    return { kind: "warn", refresh: CONFLICT_REFRESH[body.reason], lockWrites: false };
  }
  if (status === 500) {
    // The server's own failure text, when it has one; never a silent one.
    return { kind: "error", refresh: false, lockWrites: false };
  }
  return null;
}

/**
 * A 409 `ambiguous`: the message names EVERY candidate -- key, its
 * `file:line`, and its text (plan §4; the author picks one and retries
 * with the full key). Composed OUTSIDE the 300-char message cap (each
 * candidate's text capped at CANDIDATE_TEXT_LIMIT, at most CANDIDATE_LIMIT
 * named, the rest counted) so a collision with many candidates loses
 * none.
 */
function ambiguousMessage(body) {
  const parts = [];
  const intro = serverText(body);
  if (intro) parts.push(sanitize(intro));
  const candidates = Array.isArray(body.candidates) ? body.candidates : [];
  const named = candidates.slice(0, CANDIDATE_LIMIT);
  for (const cand of named) {
    if (!isPlainObject(cand)) continue;
    const text = sanitize(cand.text, CANDIDATE_TEXT_LIMIT);
    const shown =
      stripControls(cand.text).length > CANDIDATE_TEXT_LIMIT
        ? `${text}...`
        : text;
    parts.push(`${cand.key} (${cand.file}:${cand.line}) ${shown}`);
  }
  const rest = candidates.length - named.length;
  if (rest > 0) parts.push(`(+${rest} more)`);
  return parts.join(" -- ");
}

/**
 * One `ServeClient.post()` result -> a plain decision object per plan §4's
 * Result-mapping table. `result` is `{status, body}` (the body JSON-parsed
 * for every status, raw text when a non-200 body is not JSON) or `{error}`
 * for a request that got no response at all -- which for post() also
 * covers a 200 whose body will not parse (its message omits the body).
 * The decision is `{kind, refresh, lockWrites, message}` with kind one of
 * "refresh" | "error" | "warn" | "lock"; the caller renders it (toast /
 * status bar / tree refresh) and never sees a body object.
 */
function planResult(result) {
  if (!isPlainObject(result)) return unhandled("no response");
  if (typeof result.error === "string" && result.status === undefined) {
    // The transport case: the request itself failed. Loud error, no lock
    // (a dead server is not a read-only server), no refresh (nothing moved).
    return decision("error", false, false, sanitize(result.error));
  }
  const status = Number(result.status);
  const body = result.body;
  const row = tableRow(status, body);
  if (!row) return unhandled(status);
  if (row.kind === "refresh") return decision("refresh", true, false, "");
  const text = serverText(body);
  let message;
  if (row.kind === "warn" && body.kind === "ambiguous") {
    // The candidates are the message (the intro text is optional): name
    // every one, outside the 300-char cap.
    message = ambiguousMessage(body);
  } else if (text !== null) {
    message = sanitize(text);
  } else if (row.kind === "lock") {
    // A `refused` without text is still the lock; say why in the shipped
    // wording (it names --no-write).
    message = LOCKED_HINT;
  } else {
    message = sanitize(
      `refdes serve answered ${status} (${body.kind}) without a message`
    );
  }
  return decision(row.kind, row.refresh, row.lockWrites, message);
}

/**
 * The Archive/Restore enabled state of one row (plan §4 "Disabled states,
 * computed from the row"): a keyed active row archives, an archived keyed
 * row restores, a keyless row has no Archive (the Mint hint), an orphan has
 * no Restore (the hand-restore hint), and a locked session (`--no-write`
 * seen as a 403) disables everything with the reason. No client-side rule
 * invention -- each disabled state mirrors a shipped panel. The impossible
 * keyless-archived row (the projection never archives a keyless marker)
 * must not crash and keeps Archive disabled; it lands on the keyless
 * branch first, which disables both. A missing row (null/undefined -- a
 * call the UI must never make) disables everything with a generic reason.
 */
function rowActions(row, state) {
  const locked = Boolean(state && state.writesLocked);
  if (locked) {
    return {
      archive: { enabled: false, tooltip: LOCKED_HINT },
      restore: { enabled: false, tooltip: LOCKED_HINT },
    };
  }
  if (!isPlainObject(row)) {
    const reason = "No Navis row to act on";
    return {
      archive: { enabled: false, tooltip: reason },
      restore: { enabled: false, tooltip: reason },
    };
  }
  const keyless = !row.key;
  const archived = Boolean(row.archived);
  const orphan = Boolean(row.orphan);

  const archiveEnabled = !keyless && !archived && !orphan;
  let archiveTooltip = "";
  if (!archiveEnabled) {
    if (keyless) archiveTooltip = KEYLESS_HINT;
    else if (archived) archiveTooltip = "Already archived";
    else archiveTooltip = ORPHAN_HINT;
  }

  const restoreEnabled = archived && !keyless && !orphan;
  let restoreTooltip = "";
  if (!restoreEnabled) {
    if (keyless) restoreTooltip = KEYLESS_HINT;
    else if (orphan) restoreTooltip = ORPHAN_HINT;
    else restoreTooltip = "Not archived -- nothing to restore";
  }

  return {
    archive: { enabled: archiveEnabled, tooltip: archiveTooltip },
    restore: { enabled: restoreEnabled, tooltip: restoreTooltip },
  };
}

/**
 * The selector a command POSTs: the row's FULL key (never key6 -- an
 * ambiguous prefix races the projection; never an ordinal -- positions move
 * between refreshes, docs/navis.md "The serve API"). A keyless row has no
 * selector: null, the conservative answer for a call the UI must never
 * make (rowActions disables its Archive; the caller checks for null).
 */
function selectorFor(row) {
  if (!row || !row.key) return null;
  return String(row.key);
}

/**
 * The Mint command's state (plan §4, docs/navis.md "Mint keys (N)"): count
 * = keyless rows among ALL rows (active AND archived), enabled iff count>0
 * and the session is unlocked. Mint is project-wide (body `{}`), so the
 * count is a legibility aid, not a scope.
 */
function mintAvailable(payload, state) {
  const rows = payload && Array.isArray(payload.navis) ? payload.navis : [];
  let count = 0;
  for (const row of rows) {
    if (row && !row.key) count += 1;
  }
  const locked = Boolean(state && state.writesLocked);
  let tooltip;
  if (locked) {
    tooltip = LOCKED_HINT;
  } else if (count === 0) {
    tooltip = "No keyless Navis to mint";
  } else {
    tooltip = `Mint keys for ${count} unkeyed Navis`;
  }
  return {
    enabled: count > 0 && !locked,
    count,
    label: `Mint keys (${count})`,
    tooltip,
  };
}

/**
 * The session write-lock a 403 `refused` flips (plan §4: writes are
 * disabled for the rest of the session; reset() on re-attach / new serve).
 * Plain per-instance state, idempotent lock.
 */
function createWriteLock() {
  let locked = false;
  return {
    locked() {
      return locked;
    },
    lock() {
      locked = true;
    },
    reset() {
      locked = false;
    },
  };
}

module.exports = {
  planResult,
  rowActions,
  selectorFor,
  mintAvailable,
  createWriteLock,
};
