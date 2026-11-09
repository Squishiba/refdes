"""W5b.4c-2a contract tests: the tick pane's SAVE model (docs/design/
thread-workbench-w5b-plan.md, §4 W5b.2/W5b.4 + §6 Q2/Q3/Q5/Q6/Q8, all
RATIFIED 2026-11-06).

The module under test is `src/refdes/serve/static/tick-save.js`: ONE new pure
ES module -- the REQUEST and RESPONSE logic of the pane's Save. No DOM, no
network, no storage, no token: the token and Origin live in the permission
seam (serve/server.py:782-787, enforced by tests/test_serve_continue_http.py),
and the caller (the 4c-2b glue) owns the fetch. Like tick-drafts.js /
tick-pane.js the module is PURE by design, so these node harnesses drive it
headless and deliberately define NO `document`, `window`, `sessionStorage` or
`localStorage` globals: a module that touches any of them fails the import
itself (the purity proof runs, it is not only a text scan; `fetch` is node's
own global on 18+, so the fetch ban is pinned by the text scan).

The server contract these tests pin was CAPTURED, not guessed, by running the
real routes on a live EditorApp (the fixture of tests/test_serve_continue_http.py;
its assertions are the shipped record of the same payloads):

    POST /api/item/<ref>/continue
      body {ticks: [[taskId, state], ...], expected_revision: "<sha256>"}

    200 Applied   {kind:"applied", ok:true, message, path, revision, describe,
                   id, handle, pinned, diagnostics}
                   (api.py _apply_outcome; id/handle = the NEW entry's id and
                   minted key, revision = the target file's NEW revision)
    409 Conflict  {kind:"conflict", ok:false, message, path,
                   expected_revision, current_revision, current_text, diff}
                   (current_text is the RAW current file text, NOT task rows --
                   the pane shows rows against the ticks from data it already
                   rendered; the 409 carries no structured list)
    422 Refused   {kind:"refused", ok:false, message:"refused: <reason>",
                   reason, path}
    422 Invalid   {kind:"invalid", ok:false, message, reason, path,
                   diagnostics}   -- NOT a 400: api.py maps Invalid to 422
    400 malformed {error: "<text>"}   (no kind key)
    403 read-only {kind:"refused", error:"this server was started with
                   --no-write: continuations are disabled"}
    403 token     plain text "missing or invalid launch token" (text/plain)
    415           plain text "expected application/json"
    405 GET on the route: JSON {"error":"method not allowed"}; PUT: plain text

The pinned export surface (the 4c-2b glue builds against this; deviations from
the slice brief are recorded in in-prog-logs/w5b4c2a-tests.md):

    buildSaveRequest({ref, revision, pendingTicks})
      -> {ok:true, path, body}  path = '/api/item/'+encodeURIComponent(ref)
                                +'/continue', body = {ticks, expected_revision}
      -> {ok:false, reason}     reason a plain string

    planSaveResponse({status, body}) -> {kind, message, ...}
      kinds: "saved" (200 applied), "conflict" (409), "refused" (422 refused),
      "invalid" (422 invalid; 400 malformed carries the server's error text),
      "forbidden" (403 -- names --no-write / the token), "error" (transport
      {status:0, body:{error}}, 405/415/500/anything unnamed: generic, with
      the status, never a raw body verbatim). Every message a plain string;
      server text is control-stripped and capped at 300.

    conflictChoices({revision, pendingTicks, current})
      -> {keepTheirs:{discard:true},
          keepMine:{revision, ticks, dropped},   // re-stamp, never merge
          copyOut:{text}}                        // pasteable plain text
      current = {revision, rows: [{taskId, state, text}, ...]} -- the CURRENT
      tip's rows as the caller has them (the 409 carries no rows, only text).

    describeConflict({pendingTicks, current})
      -> [{taskId, mine, theirs, differs}, ...]  // Q3a: the current tip's
      list against the ticks, current order first, vanished pending rows
      appended with theirs:null.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.parse

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO_ROOT, "src", "refdes", "serve", "static")
TICK_SAVE_JS = os.path.join(STATIC, "tick-save.js")

NODE = shutil.which("node")

# One node spawn per scenario group; generous for a cold process start on a
# shared runner (the timeout note in tests/test_editor_draft_mirror.py).
NODE_TIMEOUT_S = 120

STATES = ("open", "done", "dropped")

# ---------------------------------------------------------------------------
# The REAL captured payloads (verbatim from the live routes, see the module
# docstring). planSaveResponse must carry these fields; the tests below pin
# the mapping against exactly these bytes.
APPLIED = {
    "kind": "applied",
    "ok": True,
    "message": "applied: continuation LOG-SYS-003 appended to items/log.yaml (2 ticks)",
    "path": "items/log.yaml",
    "revision": "c88b48127656086d63c021722f211eb10099be44f6367f8bc152f955ea21525c",
    "describe": "continuation LOG-SYS-003 appended to items/log.yaml (2 ticks)",
    "id": "LOG-SYS-003",
    "handle": "chhccjq1czf",
    "pinned": [],
    "diagnostics": [],
}

CONFLICT = {
    "kind": "conflict",
    "ok": False,
    "message": "conflict: items/log.yaml changed since this edit was planned (expected c68cdc444d38, found 1ed6705e3d60)",
    "path": "items/log.yaml",
    "expected_revision": "c68cdc444d38d14a1ad4bd804d46d0c046511d0fdbfe32b83ac156d54933103f",
    "current_revision": "1ed6705e3d60f4af26151330340bc8bf1227940792c59ed6a9b9cb4d545758fc",
    "current_text": "defaults:\n  type: log\n\nitems:\n  - id: LOG-SYS-002\n    tasks:\n      - {id: T-rail, text: Settle the rail budget., state: open}\n",
    "diff": "--- items/log.yaml (on disk)\n+++ items/log.yaml (your continuation)\n@@ -16,3 +16,9 @@\n",
}

REFUSED = {
    "kind": "refused",
    "ok": False,
    "message": "refused: task 'T-nope' is not in the task list at the tip: the fold owns the list, and a continuation invents no rows",
    "reason": "task 'T-nope' is not in the task list at the tip: the fold owns the list, and a continuation invents no rows",
    "path": "items/log.yaml",
}

INVALID = {
    "kind": "invalid",
    "ok": False,
    "message": "blocked: the edit would leave 1 error(s): task state 'closed' is outside the vocabulary",
    "reason": "blocked: the edit would leave 1 error(s): task state 'closed' is outside the vocabulary",
    "path": "items/log.yaml",
    "diagnostics": [{"level": "error", "message": "task state 'closed' is outside the vocabulary"}],
}

READ_ONLY_403 = {
    "kind": "refused",
    "error": "this server was started with --no-write: continuations are disabled",
}

BAD_REQUEST_400 = {
    "error": "expected_revision is required: the file_revision from GET /api/item/<ref>"
}

HOSTILE_REFUSED = {
    "kind": "refused",
    "ok": False,
    "message": "refused: task '\"><img src=x onerror=alert(1)>' is not in the task list at the tip: the fold owns the list, and a continuation invents no rows",
    "reason": "task '\"><img src=x onerror=alert(1)>' is not in the task list at the tip: the fold owns the list, and a continuation invents no rows",
    "path": "items/log.yaml",
}


def enc(text: str) -> str:
    # encodeURIComponent's unreserved set in urllib terms (test_tick_drafts.py)
    return urllib.parse.quote(text, safe="!*()'")


HARNESS = """
import { pathToFileURL } from 'node:url';

const [modulePath, scenario, seedJson] = process.argv.slice(2);
const input = JSON.parse(seedJson);

// Purity by execution: this harness defines NO document, NO window, NO
// sessionStorage/localStorage/Storage. The module importing and every export
// running prove it never reaches for a page global. (node >= 18 defines a
// global fetch of its own, so the fetch ban is the text scan's job.)
const mod = await import(pathToFileURL(modulePath).href);

const NAMES = ['buildSaveRequest', 'planSaveResponse', 'conflictChoices', 'describeConflict'];
const out = { scenario, exports: {}, threw: {} };
for (const name of NAMES) out.exports[name] = typeof mod[name];

const call = (name, arg) => {
  try {
    return { result: mod[name](arg) };
  } catch (e) {
    return { threw: String(e && e.message ? e.message : e) };
  }
};

if (scenario === 'build') {
  out.cases = {};
  for (const [name, arg] of Object.entries(input.cases)) {
    out.cases[name] = call('buildSaveRequest', arg);
  }
  // deep-copy proof: mutating the caller's arrays after the build must not
  // reach into the returned body (the fetch caller keeps ticking; the request
  // it already built is a snapshot).
  {
    const ticks = [['T-1', 'done']];
    const built = mod.buildSaveRequest({ ref: 'LOG-1', revision: 'r1', pendingTicks: ticks });
    ticks.push(['T-2', 'dropped']);
    ticks[0][1] = 'open';
    out.copyProof = { body: built.body };
  }
}

if (scenario === 'plan') {
  out.cases = {};
  for (const [name, arg] of Object.entries(input.cases)) {
    out.cases[name] = call('planSaveResponse', arg);
  }
}

if (scenario === 'conflict') {
  out.cases = {};
  for (const [name, arg] of Object.entries(input.cases)) {
    out.cases[name] = {
      choices: call('conflictChoices', arg),
      describe: call('describeConflict', arg),
    };
  }
}

process.stdout.write(JSON.stringify(out));
"""


def _run(tmp_path, scenario: str, cases: dict) -> dict:
    if NODE is None:
        pytest.skip("no node on PATH to run the tick save module")
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8", newline="")
    seed = json.dumps({"cases": cases}, ensure_ascii=False)
    proc = subprocess.run(
        [NODE, str(harness), TICK_SAVE_JS, scenario, seed],
        capture_output=True,
        text=True,
        # node speaks UTF-8; a Windows runner's locale is cp1252 and would
        # mojibake the unicode task ids on the way back in.
        encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, f"node harness {scenario!r} failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# The captured server payloads are the contract. If the route's shapes move,
# these pins notice (they are hand-copied from the live capture; the shipped
# round-trips in tests/test_serve_continue_http.py are the live record).


CAPTURED_BUILD = {
    "healthy": {
        "ref": "LOG-SYS-002",
        "revision": "c68cdc444d38d14a1ad4bd804d46d0c046511d0fdbfe32b83ac156d54933103f",
        "pendingTicks": [["T-rail", "done"], ["T-probe", "dropped"]],
    },
}

REJECT_CASES = {
    "ref-empty": {"ref": "", "revision": "r1", "pendingTicks": [["T-1", "done"]]},
    "ref-missing": {"revision": "r1", "pendingTicks": [["T-1", "done"]]},
    "ref-number": {"ref": 7, "revision": "r1", "pendingTicks": [["T-1", "done"]]},
    "ref-null": {"ref": None, "revision": "r1", "pendingTicks": [["T-1", "done"]]},
    "revision-empty": {"ref": "LOG-1", "revision": "", "pendingTicks": [["T-1", "done"]]},
    "revision-missing": {"ref": "LOG-1", "pendingTicks": [["T-1", "done"]]},
    "revision-number": {"ref": "LOG-1", "revision": 7, "pendingTicks": [["T-1", "done"]]},
    "ticks-empty": {"ref": "LOG-1", "revision": "r1", "pendingTicks": []},
    "ticks-missing": {"ref": "LOG-1", "revision": "r1"},
    "ticks-null": {"ref": "LOG-1", "revision": "r1", "pendingTicks": None},
    "ticks-not-array": {"ref": "LOG-1", "revision": "r1", "pendingTicks": {"T-1": "done"}},
    "tick-bare-string": {"ref": "LOG-1", "revision": "r1", "pendingTicks": ["T-1"]},
    "tick-short": {"ref": "LOG-1", "revision": "r1", "pendingTicks": [["T-1"]]},
    "tick-long": {"ref": "LOG-1", "revision": "r1", "pendingTicks": [["T-1", "done", "x"]]},
    "id-number": {"ref": "LOG-1", "revision": "r1", "pendingTicks": [[7, "done"]]},
    "id-empty": {"ref": "LOG-1", "revision": "r1", "pendingTicks": [["", "done"]]},
    "state-outside": {"ref": "LOG-1", "revision": "r1", "pendingTicks": [["T-1", "closed"]]},
    "state-number": {"ref": "LOG-1", "revision": "r1", "pendingTicks": [["T-1", 7]]},
    "state-null": {"ref": "LOG-1", "revision": "r1", "pendingTicks": [["T-1", None]]},
}

HOSTILE_BUILD = {
    "proto-id": {
        "ref": "LOG-1",
        "revision": "r1",
        "pendingTicks": [["__proto__", "done"]],
    },
    "markup-id": {
        "ref": "LOG-1",
        "revision": "r1",
        "pendingTicks": [['"><img src=x onerror=alert(1)>', "done"]],
    },
    "unicode-id": {
        "ref": "LOG-1",
        "revision": "r1",
        "pendingTicks": [["T-résumé-✓", "dropped"]],
    },
    "hostile-ref": {
        "ref": "../secret?x=a#b c",
        "revision": "r1",
        "pendingTicks": [["T-1", "done"]],
    },
}


@pytest.fixture(scope="module")
def build_results(tmp_path_factory):
    return _run(
        tmp_path_factory.mktemp("build"),
        "build",
        {**CAPTURED_BUILD, **REJECT_CASES, **HOSTILE_BUILD},
    )


def test_the_request_is_the_captured_post_body_and_path(build_results):
    """The save posts exactly the W5b.2 body the route pins (api.py
    _continue_item; tests/test_serve_continue_http.py): {ticks in order,
    expected_revision} to /api/item/<encodeURIComponent(ref)>/continue."""
    r = build_results["cases"]["healthy"]
    assert "threw" not in r, r
    built = r["result"]
    assert built["ok"] is True
    assert built["path"] == "/api/item/LOG-SYS-002/continue"
    assert set(built["body"]) == {"ticks", "expected_revision"}
    assert built["body"]["ticks"] == [["T-rail", "done"], ["T-probe", "dropped"]]
    assert built["body"]["expected_revision"] == (
        "c68cdc444d38d14a1ad4bd804d46d0c046511d0fdbfe32b83ac156d54933103f"
    )


def test_the_path_percent_encodes_the_ref_like_the_route_decodes(build_results):
    """The dispatcher unquotes the ref (api.py: `urllib.parse.unquote`); the
    module builds the path with encodeURIComponent, so every hostile ref --
    slashes, query, fragment, spaces -- travels as ONE path segment."""
    r = build_results["cases"]["hostile-ref"]["result"]
    assert r["ok"] is True
    assert r["path"] == "/api/item/" + enc("../secret?x=a#b c") + "/continue"
    assert r["path"].endswith("/continue")


def test_the_ticks_carry_the_states_the_draft_holds_in_order(build_results):
    """pendingTicks() is insertion-ordered [[id, state], ...] (the pinned
    tick-drafts.js shape, tests/test_tick_drafts.py); every legal state of
    Q6(b) (open, done, dropped -- un-ticking back to open is a real save)
    passes through unchanged."""
    cases = build_results["cases"]
    # healthy carries done + dropped in order; add the open re-stamp here:
    assert cases["healthy"]["result"]["body"]["ticks"][0][1] == "done"
    assert cases["healthy"]["result"]["body"]["ticks"][1][1] == "dropped"
    proto = cases["proto-id"]["result"]
    assert proto["ok"] is True
    assert proto["body"]["ticks"] == [["__proto__", "done"]]
    uni = cases["unicode-id"]["result"]
    assert uni["ok"] is True
    assert uni["body"]["ticks"] == [["T-résumé-✓", "dropped"]]


def test_hostile_ids_are_data_never_prototype_mischief(build_results):
    """An id like `__proto__` is an ordinary string in the ticks list: the
    body is a list of pairs, and the pair survives the JSON round trip the
    fetch will do (a builder that indexes an object by id loses it)."""
    proto = build_results["cases"]["proto-id"]["result"]
    round_tripped = json.loads(json.dumps(proto["body"]))
    assert round_tripped["ticks"] == [["__proto__", "done"]]
    markup = build_results["cases"]["markup-id"]["result"]
    assert markup["ok"] is True
    assert markup["body"]["ticks"][0][0] == '"><img src=x onerror=alert(1)>'


def test_the_body_is_a_snapshot_the_caller_can_keep_ticking_on(build_results):
    """Each pair is COPIED: mutating the draft's arrays after the build must
    not change the request already built (the caller keeps ticking while the
    save is in flight)."""
    proof = build_results["copyProof"]["body"]
    assert proof["ticks"] == [["T-1", "done"]], (
        "the body aliases the caller's arrays"
    )


@pytest.mark.parametrize("name", sorted(REJECT_CASES))
def test_an_unpostable_save_is_refused_locally_with_a_plain_reason(build_results, name):
    """The module refuses locally, with {ok:false, reason:<plain string>}:
    empty ref, revision that is not a non-empty string, an empty tick list,
    a pair that is not a pair, a non-string/empty id, a state outside
    open|done|dropped. None of these may reach the server as a request the
    route 400s on (api.py's malformed-body gate)."""
    r = build_results["cases"][name]
    assert "threw" not in r, r
    built = r["result"]
    assert built["ok"] is False, f"{name} built a request that cannot be posted"
    assert "path" not in built and "body" not in built
    assert isinstance(built["reason"], str) and built["reason"] != ""


PLAN_CASES = {
    "applied": {"status": 200, "body": APPLIED},
    "conflict": {"status": 409, "body": CONFLICT},
    "conflict_text_gone": {
        "status": 409,
        "body": {**CONFLICT, "current_text": None, "diff": ""},
    },
    "refused": {"status": 422, "body": REFUSED},
    "refused_hostile": {"status": 422, "body": HOSTILE_REFUSED},
    "refused_huge": {
        "status": 422,
        "body": {**REFUSED, "message": "x" * 500 + "a\tb\x00c\x1bd" + "y" * 500},
    },
    "refused_no_message": {
        "status": 422,
        "body": {"kind": "refused", "ok": False, "reason": "the reason text", "path": None},
    },
    "invalid": {"status": 422, "body": INVALID},
    "bad_request": {"status": 400, "body": BAD_REQUEST_400},
    "bad_request_text": {"status": 400, "body": "not a json object at all"},
    "forbidden_read_only": {"status": 403, "body": READ_ONLY_403},
    "forbidden_token_text": {"status": 403, "body": "missing or invalid launch token"},
    "forbidden_empty": {"status": 403, "body": None},
    "transport": {"status": 0, "body": {"error": "TypeError: Failed to fetch"}},
    "method": {"status": 405, "body": {"error": "method not allowed"}},
    "content_type": {"status": 415, "body": "expected application/json"},
    "boom_html": {"status": 500, "body": "<html><body>Internal Server Error</body></html>"},
    "applied_garbage": {"status": 200, "body": {"kind": "wat"}},
    "no_status": {"status": None, "body": None},
}


@pytest.fixture(scope="module")
def plan_results(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("plan"), "plan", PLAN_CASES)


def _plan(plan_results, name):
    r = plan_results["cases"][name]
    assert "threw" not in r, r
    return r["result"]


def test_a_200_applied_is_saved_carrying_the_new_landing_spot(plan_results):
    """kind "saved" -- the caller clears the draft on this. It carries what
    the REAL 200 gives (captured, pinned by tests/test_serve_continue_http.py):
    the target file's NEW revision, the NEW entry's id and minted handle, the
    project-relative path, and the server's own plain message."""
    saved = _plan(plan_results, "applied")
    assert saved["kind"] == "saved"
    assert saved["revision"] == APPLIED["revision"]
    assert saved["id"] == "LOG-SYS-003"
    assert saved["handle"] == "chhccjq1czf"
    assert saved["path"] == "items/log.yaml"
    assert saved["message"] == APPLIED["message"]
    assert isinstance(saved["message"], str)


def test_a_409_is_a_conflict_carrying_the_current_state_verbatim(plan_results):
    """kind "conflict": the current revision and the raw current text/diff
    the 409 REALLY carries (api.py _apply_outcome -- it carries NO task rows,
    only disk text), plus the plain message. Nothing is merged; nothing is
    renamed: the fields are the server's, camelCased for JS."""
    c = _plan(plan_results, "conflict")
    assert c["kind"] == "conflict"
    assert c["currentRevision"] == CONFLICT["current_revision"]
    assert c["expectedRevision"] == CONFLICT["expected_revision"]
    assert c["currentText"] == CONFLICT["current_text"]
    assert c["diff"] == CONFLICT["diff"]
    assert c["message"] == CONFLICT["message"]
    assert "merge" not in c["message"]  # plain server text, untouched


def test_a_conflict_whose_disk_text_vanished_still_names_the_revision(plan_results):
    """The rare atomic-move race leaves current_text None (edit.py's _Moved
    path reads the file back and may fail): currentText passes through as
    null, currentRevision stays the truth the caller re-stamps against."""
    c = _plan(plan_results, "conflict_text_gone")
    assert c["kind"] == "conflict"
    assert c["currentRevision"] == CONFLICT["current_revision"]
    assert c["currentText"] is None


def test_a_422_refused_keeps_the_servers_own_text_as_the_message(plan_results):
    """kind "refused" (422): the server's own text is the message (the
    draft is KEPT -- that is the caller's rule; the message is what it shows).
    The captured refused body's message starts "refused: " (api.py)."""
    r = _plan(plan_results, "refused")
    assert r["kind"] == "refused"
    assert r["message"] == REFUSED["message"]


def test_a_refused_message_is_control_stripped_and_capped_at_300(plan_results):
    """The server's text is capped at 300 chars with control characters
    stripped (a refusal may echo an author's task text; a pane message is
    plain text, not a scroll of NULs). 500 leading 'x' chars pin the cap
    exactly: the message is the first 300 of the cleaned text."""
    r = _plan(plan_results, "refused_huge")
    assert r["kind"] == "refused"
    assert r["message"] == "x" * 300


def test_a_hostile_server_echo_stays_an_inert_plain_string(plan_results):
    """The route echoes a rejected task id as repr-in-JSON (pinned by
    tests/test_serve_continue_http.py); the plan hands the caller a PLAIN
    string containing that text. Nothing here is markup -- the string is
    exactly the server's text, so the DOM glue's textContent render is inert
    by construction."""
    r = _plan(plan_results, "refused_hostile")
    assert r["kind"] == "refused"
    assert r["message"] == HOSTILE_REFUSED["message"]
    assert isinstance(r["message"], str)


def test_a_422_invalid_is_invalid_with_the_gate_message(plan_results):
    """kind "invalid" for the gate's 422 (api.py maps Invalid -- the
    blocking diagnostics -- to 422, not 400): the server's "blocked:" text,
    the draft kept."""
    r = _plan(plan_results, "invalid")
    assert r["kind"] == "invalid"
    assert r["message"] == INVALID["message"]


def test_a_400_malformed_body_is_invalid_carrying_the_server_error(plan_results):
    """The route's malformed gate answers 400 {error: "<text>"} (NO kind
    key, captured): a shape the pane must never produce, so it is "invalid"
    with the server's own text as the message (kept, like every non-saved
    outcome)."""
    r = _plan(plan_results, "bad_request")
    assert r["kind"] == "invalid"
    assert r["message"] == BAD_REQUEST_400["error"]


def test_a_403_read_only_names_no_write(plan_results):
    """A read-only server answers 403 {kind:"refused", error:"...--no-write..."}
    (api.py's top check, captured): kind "forbidden", the message names
    `--no-write` so the pane can tell the author to relaunch writable."""
    r = _plan(plan_results, "forbidden_read_only")
    assert r["kind"] == "forbidden"
    assert "--no-write" in r["message"]
    assert r["message"] == READ_ONLY_403["error"]


def test_a_403_stale_token_names_the_token_and_the_relaunch(plan_results):
    """The seam's token 403 is a text/plain body (server.py `_deny`,
    captured -- NOT JSON): kind "forbidden" with a safe generic message
    naming `--no-write` and the token, so the pane's one line covers both
    causes the author can act on (relaunch)."""
    r = _plan(plan_results, "forbidden_token_text")
    assert r["kind"] == "forbidden"
    assert "--no-write" in r["message"]
    assert "token" in r["message"]
    assert isinstance(r["message"], str)


def test_a_403_with_no_body_at_all_is_still_forbidden(plan_results):
    """No body to read (an empty 403): still "forbidden", still a plain
    string naming both causes. No crash, no undefined."""
    r = _plan(plan_results, "forbidden_empty")
    assert r["kind"] == "forbidden"
    assert isinstance(r["message"], str) and r["message"] != ""


def test_a_failed_transport_is_error_never_a_raw_dump(plan_results):
    """The caller catches the fetch rejection and hands {status:0,
    body:{error}}: kind "error", a generic "did not reach the server" line
    with the transport's own text appended after cleaning (no status on it --
    there was none). The draft stays; this is a transient, not a refusal."""
    r = _plan(plan_results, "transport")
    assert r["kind"] == "error"
    assert "did not reach the server" in r["message"]
    assert "Failed to fetch" in r["message"]


@pytest.mark.parametrize(
    "name, needle",
    [
        ("method", "405"),
        ("content_type", "415"),
        ("boom_html", "500"),
        ("applied_garbage", "200"),
        ("no_status", ""),
    ],
)
def test_every_unnamed_status_is_a_generic_error_with_the_status(plan_results, name, needle):
    """405/415/500/200-with-junk/anything: one generic safe message naming
    the status, NEVER the raw body verbatim (the 415/500 bodies are
    text/plain HTML the seam `--no-write` deny never shows; the pane must not
    paint them). The draft is kept by the caller on every "error"."""
    r = _plan(plan_results, name)
    assert r["kind"] == "error"
    if needle:
        assert needle in r["message"]
    for raw in (
        "expected application/json",
        "Internal Server Error",
        "<html>",
        "method not allowed",
    ):
        assert raw not in r["message"], f"raw server body text leaked into the message: {raw!r}"


def test_every_outcome_carries_a_plain_string_message(plan_results):
    """Every kind -- saved, conflict, refused, invalid, forbidden, error --
    carries `message` as a non-empty plain string: the pane renders it with
    textContent and has no per-kind special case to write."""
    for name in PLAN_CASES:
        r = _plan(plan_results, name)
        assert isinstance(r.get("message"), str), f"{name}: {r!r}"
        assert r["message"] != "", f"{name}: empty message"
        assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in r["message"]), name


# A tip that moved: rows T-a/T-b/T-c exist now (T-b done, others open);
# T-gone no longer names a row; T-keep rides untouched in the current list.
CURRENT = {
    "revision": "rev-2",
    "rows": [
        {"taskId": "T-c", "state": "open", "text": "Third."},
        {"taskId": "T-a", "state": "open", "text": "First."},
        {"taskId": "T-b", "state": "done", "text": "Second."},
    ],
}

CONFLICT_CASES = {
    "mixed": {
        "revision": "rev-1",
        "pendingTicks": [["T-a", "done"], ["T-gone", "done"], ["T-c", "open"]],
        "current": CURRENT,
    },
    "all_gone": {
        "revision": "rev-1",
        "pendingTicks": [["T-x", "done"], ["T-y", "dropped"]],
        "current": CURRENT,
    },
    "clean": {
        "revision": "rev-1",
        "pendingTicks": [],
        "current": CURRENT,
    },
    "proto": {
        "revision": "rev-1",
        "pendingTicks": [["__proto__", "done"], ["T-a", "done"]],
        "current": {
            "revision": "rev-2",
            "rows": [{"taskId": "T-a", "state": "open", "text": "First."}],
        },
    },
    "no_current_revision": {
        "revision": "rev-1",
        "pendingTicks": [["T-a", "done"]],
        "current": {"rows": [{"taskId": "T-a", "state": "open", "text": "First."}]},
    },
}


@pytest.fixture(scope="module")
def conflict_results(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("conflict"), "conflict", CONFLICT_CASES)


def _choices(conflict_results, name):
    r = conflict_results["cases"][name]["choices"]
    assert "threw" not in r, r
    return r["result"]


def _describe(conflict_results, name):
    r = conflict_results["cases"][name]["describe"]
    assert "threw" not in r, r
    return r["result"]


def test_keep_theirs_is_a_plain_discard(plan_results, conflict_results):
    """Q3(a): keep-theirs = drop my draft and look at the current list. The
    choice is {discard:true} -- no ticks, no revision, nothing to save."""
    c = _choices(conflict_results, "mixed")
    assert c["keepTheirs"] == {"discard": True}


def test_keep_mine_restamps_the_surviving_ticks_on_the_current_revision(conflict_results):
    """Q3(a) keep-mine: re-stamp MY draft against the current revision and
    let me save again. It carries the current revision and ONLY my pending
    pairs that still name a row there, in MY order; the ids that vanished
    come back as `dropped`, NOT silently, and are NOT in ticks."""
    c = _choices(conflict_results, "mixed")
    km = c["keepMine"]
    assert km["revision"] == "rev-2"
    assert km["ticks"] == [["T-a", "done"], ["T-c", "open"]]
    assert km["dropped"] == ["T-gone"]


def test_keep_mine_touches_no_row_i_did_not_tick(conflict_results):
    """Pin the NO-MERGE rule (plan R1/Q3: "nothing that merges"): T-b is
    done on the current tip and NOT in my draft -- keep-mine's ticks must not
    grow a T-b entry, and no row of the current list can appear in ticks
    unless I named it."""
    c = _choices(conflict_results, "mixed")
    ticked = [pair[0] for pair in c["keepMine"]["ticks"]]
    assert "T-b" not in ticked
    assert set(ticked) <= {"T-a", "T-gone", "T-c"}
    assert c["keepMine"]["ticks"]  # my surviving pair is still there
    gone = _choices(conflict_results, "all_gone")
    assert gone["keepMine"]["ticks"] == []
    assert gone["keepMine"]["dropped"] == ["T-x", "T-y"]
    assert gone["keepMine"]["revision"] == "rev-2"


def test_copy_out_is_a_pasteable_plain_text_listing(conflict_results):
    """Q3(a) copy-it-out: a plain multi-line string -- one `taskId: state`
    line per PENDING tick (all of them, including vanished rows) -- plus a
    header line naming the revision the draft was made at and the current
    one, so the author can paste it into a note. Plain text, no markup."""
    c = _choices(conflict_results, "mixed")
    text = c["copyOut"]["text"]
    assert isinstance(text, str)
    lines = text.split("\n")
    assert "rev-1" in lines[0] and "rev-2" in lines[0], lines[0]
    assert "T-a: done" in text
    assert "T-gone: done" in text
    assert "T-c: open" in text
    assert "T-b" not in text  # not mine to copy: I never ticked it


def test_the_three_choices_are_exactly_the_ratified_three(conflict_results):
    """The conflict panel offers keep-mine / keep-theirs / copy-it-out and
    NOTHING that merges (Q3 ratified (a), plan §7): the result object's own
    shape is the pin -- three outcomes, no fourth key."""
    c = _choices(conflict_results, "mixed")
    assert set(c) == {"keepTheirs", "keepMine", "copyOut"}


def test_a_missing_current_revision_yields_no_restamp(conflict_results):
    """A `current` with no usable revision cannot be re-stamped against:
    keepMine.revision is the empty string, which buildSaveRequest refuses to
    post -- the refusal chain stays closed without a special case."""
    c = _choices(conflict_results, "no_current_revision")
    assert c["keepMine"]["revision"] == ""
    assert c["keepMine"]["ticks"] == [["T-a", "done"]]


def test_describe_shows_the_current_list_against_the_ticks(conflict_results):
    """Q3(a): "show the current tip's list against the ticks". Rows come in
    the CURRENT list's order; each names my pending state (`mine`, null if I
    never touched it), the current state (`theirs`), and whether they
    differ."""
    rows = _describe(conflict_results, "mixed")
    assert [row["taskId"] for row in rows] == ["T-c", "T-a", "T-b", "T-gone"]
    by = {row["taskId"]: row for row in rows}
    assert by["T-a"] == {"taskId": "T-a", "mine": "done", "theirs": "open", "differs": True}
    assert by["T-c"] == {"taskId": "T-c", "mine": "open", "theirs": "open", "differs": False}
    assert by["T-b"] == {"taskId": "T-b", "mine": None, "theirs": "done", "differs": False}


def test_describe_appends_my_ticks_that_no_longer_name_a_row(conflict_results):
    """A pending tick whose row vanished from the current tip is APPENDED
    (theirs null, differs true) after the current rows -- the author sees
    exactly which of their ticks have no target, never a silently dropped
    tick (the Q3 pane rule tick-pane.js's applyDraft models)."""
    rows = _describe(conflict_results, "mixed")
    tail = rows[-1]
    assert tail == {"taskId": "T-gone", "mine": "done", "theirs": None, "differs": True}
    gone_rows = _describe(conflict_results, "all_gone")
    assert [row["taskId"] for row in gone_rows] == [
        "T-c", "T-a", "T-b", "T-x", "T-y",
    ]
    assert all(row["theirs"] is None for row in gone_rows[3:])


def test_describe_of_an_untouched_draft_shows_the_clean_current_list(conflict_results):
    """With no pending ticks the describe is the current list itself: every
    row mine:null, differs:false -- a panel opened on a conflict it cannot
    show as a diff shows a plain list, not an empty screen."""
    rows = _describe(conflict_results, "clean")
    assert [row["taskId"] for row in rows] == ["T-c", "T-a", "T-b"]
    assert all(row["mine"] is None and row["differs"] is False for row in rows)


def test_hostile_ids_are_data_in_the_conflict_math(conflict_results):
    """`__proto__` as a task id is an ordinary key in this math (Map/Set
    semantics, the tick-pane.js rule): it matches only a current row of the
    same literal text, and a pending `__proto__` with no such row is dropped
    -- the prototype chain is never consulted."""
    c = _choices(conflict_results, "proto")
    assert c["keepMine"]["ticks"] == [["T-a", "done"]]
    assert c["keepMine"]["dropped"] == ["__proto__"]
    assert "__proto__: done" in c["copyOut"]["text"]
    rows = _describe(conflict_results, "proto")
    assert [row["taskId"] for row in rows] == ["T-a", "__proto__"]


# -- source pins: the module is pure, self-contained, and served-clean -------

INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*[:=]""", re.IGNORECASE)
DYNAMIC_CODE = re.compile(r"\b(eval|new\s+Function|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"])")
JS_IMPORT = re.compile(r"""(?:from|import)\s*\(?\s*['"]([^'"]+)['"]""")


def _strip_js_comments(text: str) -> str:
    """The string-aware comment stripper from tests/test_serve_static.py: the
    purity scan runs on code, not prose."""
    out = []
    i = 0
    n = len(text)
    in_string = None
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in "'\"`":
            in_string = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            if text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                end = text.find("*/", i + 2)
                i = n if end == -1 else end + 2
                out.append(" ")
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _save_code() -> str:
    with open(TICK_SAVE_JS, encoding="utf-8") as fh:
        return _strip_js_comments(fh.read())


def test_the_module_lands_in_the_served_static_dir():
    """test_serve_static.py's js_files() lists static/*.js at collection
    time, so the new file is picked up by its inline-handler / dynamic-code /
    ES2020 parse checks automatically; this pins the file is where the
    response-injection can find it."""
    listing = [n for n in os.listdir(STATIC) if n.endswith(".js")]
    assert "tick-save.js" in listing, "the file is not in the served static dir"


def test_the_module_is_pure_no_dom_no_network_no_storage_no_token():
    """4c-2a is the pure half: NO DOM, no network, no storage, and NO token
    -- the seam owns the token header (W5b.4c-2b's glue adds it to the
    fetch), and the module importing the string of its name would be the
    seam leaking in."""
    code = _save_code()
    for forbidden in (
        "document", "window", "fetch", "XMLHttpRequest", "eval",
        "innerHTML", "sessionStorage", "localStorage", "globalThis",
        "X-Refdes-Token", "Origin",
    ):
        assert forbidden not in code, f"tick-save.js touches {forbidden!r}"
    for name in (
        "buildSaveRequest", "planSaveResponse", "conflictChoices", "describeConflict",
    ):
        assert f"export function {name}" in code


def test_the_module_imports_nothing():
    """One self-contained module (the tick-pane/tick-drafts posture): no
    import graph, no shared mutable memory -- it computes over plain data."""
    code = _save_code()
    assert JS_IMPORT.findall(code) == [], "tick-save.js must be self-contained"


def test_the_module_passes_the_served_js_rules():
    """The text checks tests/test_serve_static.py runs over every served
    .js: no inline handler, no eval/new Function, no javascript: URL."""
    code = _save_code()
    assert not INLINE_HANDLER.search(code), "an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(code), "no eval/new Function in the editor"
    assert "javascript:" not in code


def test_the_module_runs_under_node_with_no_page_globals_defined(tmp_path):
    """Purity by execution, not only by scan: the harness imported the module
    in the scenario groups above with NO document/window/sessionStorage/
    localStorage defined, and ran every export. This pins all four exports
    are functions (the import itself is the page-globals proof)."""
    results = _run(tmp_path, "build", CAPTURED_BUILD)
    assert results["exports"] == {
        "buildSaveRequest": "function",
        "planSaveResponse": "function",
        "conflictChoices": "function",
        "describeConflict": "function",
    }
