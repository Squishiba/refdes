"""`state: "ok"` on a hash-only remote citation is a record, not a check.

Finding F2 of `in-prog-logs/remote-fetch-exercise.md`. A remote citation pinned
with `keep_copy: false` has its sha256 recorded and its bytes nowhere on the
machine, so nothing offline can compare the two: `check`, `build` and
`build --require-citations` all exit 0 on a lockfile whose pinned digest is
wrong, and only `refdes check --refresh` — which re-downloads — reports the
drift and exits 1. The offline silence is by design; what was wrong was the
sentence describing it. The `state` table called `"ok"` "Resolved — hash on
file", next to an `audit` row that reads `ok  hash-only  cited by CMP-PWR-001`,
and "hash on file" is a claim about a comparison that never happened. `audit`
is the command a release reviewer runs, so the wording is the diagnostic.

These tests pin the doc's half of that, which is where the old text lived
(`grep -rn "hash on file" src/ tests/ docs/` had exactly one hit, and it was
this table). The runtime half is asserted by
`tests/test_citations.py::test_cli_check_refresh_detects_drift`, which is the
only path that can catch a wrong hash-only pin.

The test reads the file rather than importing a constant on purpose: the claim
is about the words a human reads, so a constant that no page quotes would not
satisfy it.
"""

from __future__ import annotations

import os

from helpers import REPO

OUTPUT_DOC = os.path.join(REPO, "docs", "output.md")
CLI_DOC = os.path.join(REPO, "docs", "cli-reference.md")


def _text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _ok_row() -> str:
    """The table row for `state == "ok"`, as one line."""
    rows = [line for line in _text(OUTPUT_DOC).splitlines() if line.startswith('| `"ok"`')]
    assert len(rows) == 1, rows
    return rows[0]


def test_the_ok_row_no_longer_claims_a_hash_is_on_file():
    """The exact sentence the finding quotes. Left in place it is a false claim
    on the page a reader consults to decide what a dashboard built on this JSON
    is asserting."""
    assert "hash on file" not in _text(OUTPUT_DOC)


def test_the_ok_row_says_a_hash_only_pin_is_recorded_not_verified():
    row = _ok_row()
    assert "recorded, not verified" in row, row
    # and it says *why*, so the row is not merely vaguer than it was: there is
    # no local copy of a hash-only citation for a hash to be on
    assert "no bytes here to compare" in row, row


def test_the_ok_row_points_at_the_one_command_that_can_check_it():
    assert "refdes check --refresh" in _ok_row()


def test_the_sentence_under_the_table_no_longer_says_ok_means_the_hash_is_right():
    """The row was not the only overstatement: the paragraph below it read
    "`state == "ok"` alone is the claim that the sha256 is right", which is the
    same claim in the reader's own words, and would have survived a fix to the
    table alone."""
    body = " ".join(_text(OUTPUT_DOC).split())
    assert "the claim that the sha256 is right" not in body
    assert "the claim that the recorded sha256 is the right one" in body
    # ...and the limit of that claim is stated where a hash-only reader hits it
    assert (
        "for a `hash-only` remote citation it is a claim about the lockfile, "
        "not about today's upstream" in body
    )


def test_the_audit_reference_says_the_same_thing_about_a_hash_only_row():
    """`docs/cli-reference.md` is where the two columns of a `refdes audit`
    citation line are defined, and its gloss of `state` is what a reader of the
    command's own output goes by. It must not leave the old claim standing in a
    second place."""
    body = _text(CLI_DOC)
    assert "hash on file" not in body
    gloss = [
        line
        for line in body.splitlines()
        if "wrong sha256 for one is found by" in line or "check --refresh` and by nothing offline" in line
    ]
    assert gloss, "the audit section no longer says what a hash-only `ok` means"
