"""AgentCoder pilot for PR #347 -- acceptance cases from the written contract.

Blind-designed from docs/design/inline-calc.md (esp. section 3), docs/math.md
("Inline calc"), and docs/design/keys.md, plus CLI probes on the origin/main
base.

Base-state note (probe, not assumption): the trigger/verify slice (sections
1-2) is already merged on the base (#333/#341), so the section-1/2 tests are
old-behavior controls, green on the base. The section-3 slice -- calc_hash
extension, cross-item/source() dependency scans over spans -- is what #347
adds: those tests are EXPECTED RED on this base and are marked EXPECTED-RED
in their docstrings. The `release_gate.inline_calc_results` rule is #345's
(not merged at this head, not #347's work): the gate pair below integrates
against it and skips until it lands (see GATE_INTEGRATION). Unresolved
oracles (exact tie boundary, gate message wording, span-ref display-half
refresh after rename) are deliberately not asserted.

Validated-copy note (adjusted at the #347 head, rebased on #351):
- the cross-item cases were authored with the reference inside an
  expression (``LOG-A.V_in * 2``). That shape is not the calc language --
  the evaluator resolves a cross-item reference only when the *whole*
  expression is one (``src/refdes/calc.py``, ``CROSS_REF_RE.match`` of the
  stripped RHS), and a fence line ``w = LOG-A.V_in * 2`` fails identically
  with ``unknown name 'LOG'`` (the slice-1 evaluator, unchanged by #347),
  so the span behaved exactly like the fence: parity, not a defect. The
  cases are adapted to the whole-RHS form the contract specifies
  (docs/math.md, "Inline calc": the RHS is the ordinary calc-line grammar
  "with the same restrictions"; docs/design/inline-calc.md section 3).
- the gate pair is skipped at this head (see GATE_INTEGRATION): the rule
  name is a configuration error until #345 merges. The exemption case was
  adapted at #345's head: the blind copy authored the stale result AFTER
  the capture, and #345's implemented exemption is deliberately narrow --
  a post-capture edit leaves the live item editable, so only a capture
  taken IN the stale state (digest matching, no later edit) is frozen.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import write_project_config

from refdes import cli as cli_mod
from refdes.model import RELEASE_GATE_DEFAULTS

# The gate pair below integrates against #345's `release_gate.inline_calc_results`
# rule, which does not exist at this head (not merged): the rule name is a
# configuration error here, so the pair skips -- not a #347 defect surface.
# The skip is CONDITIONAL (round-3/round-5 review, chunk 2): it tests for
# the RULE ITSELF in the rule registry (`RELEASE_GATE_DEFAULTS`,
# src/refdes/model.py) -- NOT for a module name: #345 adds no module, it
# extends `model.py`/`lifecycle.py`, so a `find_spec` for a hypothetical
# release_gate.py would stay true forever and the pair would skip silently
# forever. Testing registry membership, the pair starts running -- against
# the real rule -- the moment #345 lands in this checkout.
GATE_INTEGRATION = pytest.mark.skipif(
    "inline_calc_results" not in RELEASE_GATE_DEFAULTS,
    reason="integrates #347 spans against #345's release_gate.inline_calc_results"
    " rule (github issue/PR #345); runs automatically once #345 is merged",
)

FIXTURES = Path(__file__).parent / "fixtures" / "agentcoder347"

STD_CONFIG = (
    "site: { title: T, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
    "id: { width: 3, ledger: .refdes/ids.yaml }\n"
)

DIV = "0.8 V * (1 + 10 kohm/2.2 kohm)"  # computes 4.43636...


def setup(tmp_path, config=STD_CONFIG, items=None):
    cfg = write_project_config(tmp_path, config)
    root = tmp_path / "items" / "main"
    root.mkdir(parents=True, exist_ok=True)
    for name, text in (items or {}).items():
        (root / name).write_text(text, encoding="utf-8")
    return cfg


def cli(cfg, *argv):
    return cli_mod.main(["-c", str(cfg), *argv])


def out(capsys):
    captured = capsys.readouterr()
    return captured.out + captured.err


def log_item(item_id, body, extra_front="", type="log"):
    return (
        f"---\nid: {item_id}\ntype: {type}\nsummary: probe {item_id}\n"
        f"date: 2026-10-19\n{extra_front}---\n\n{body}\n"
    )


def item_files_bytes(root):
    root = Path(root)
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def baseline_items(tmp_path, name):
    text = (Path(tmp_path) / ".refdes" / "baselines" / f"{name}.yaml").read_text()
    return yaml.safe_load(text)["items"]


def audit_changed_ids(cfg, capsys):
    cli(cfg, "audit")
    text = out(capsys)
    section = text.split("Since last revision", 1)
    ids = []
    for line in section[1].splitlines():
        stripped = line.strip()
        # "(rev1, 2026-...):" is the section header; "(N unchanged)" and
        # the no-baseline note are the only "(" lines that end the listing.
        if stripped.startswith("(rev") and stripped.endswith("):"):
            continue
        if stripped.startswith(("changed", "added", "removed", "relabelled")):
            ids += stripped.split()[2:]
        elif stripped.startswith("("):
            break
    return ids


def edit_file(tmp_path, name, old, new):
    path = Path(tmp_path) / "items" / "main" / name
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {name}"
    path.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------- Case 1
# trigger, verification, precision windows, D1. Contract sections 1-2.
# Control: GREEN on base (slice 1 merged).


def test_trigger_windows_and_d1(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        items={
            "LOG-001.md": log_item(
                "LOG-001",
                f"`Vc := {DIV} | V = 4.436 V`\n\n"
                f"`Va := {DIV} | V = 4.4 V`\n\n"
                f"`Vb := {DIV} | V = 4.52 V`\n\n"
                "`Vz := 1234 = 1.2e3`\n\n"
                "`Vw := 1234 = 1.20e3`\n\n"
                "`V_cl = 0.8 V`\n\n"
                "``N := 2 * 3 = 99``\n",
            ),
            "LOG-002.md": log_item("LOG-002", "`Vd := 3 V * 2`"),
        },
    )
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 1  # missing result is an error, section 2 table
    # stale result: warning naming stored and recomputed quantities
    assert "inline calc Vb: stored result says 4.52 V, now computes 4.436 V" in text
    assert "inline calc Vw: stored result says 1.20e3, now computes 1234" in text
    assert "items/main/LOG-001.md" in text  # file:line posting
    # missing result: error at the span's line
    assert "inline calc Vd := 3 V * 2: stored result missing" in text
    assert "items/main/LOG-002.md" in text
    # in-window results, the ordinary span, and the double-backtick escape
    # hatch produce no inline-calc diagnostic at all
    for silent in ("inline calc Vc", "inline calc Va", "inline calc Vz",
                   "inline calc V_cl", "inline calc N"):
        assert silent not in text

    # D1: after key minting settles, verification never rewrites the source
    stable = item_files_bytes(tmp_path / "items")
    cli(cfg, "check")
    out(capsys)
    code = cli(cfg, "build")
    text = out(capsys)
    assert item_files_bytes(tmp_path / "items") == stable
    # build runs the same verification and shares the error floor
    assert code == 1
    assert "inline calc Vb" in text


# ---------------------------------------------------------------- Case 2
# honest display + item-wide scope/order. Contract section 1, math.md.
# Control: GREEN on base.


def test_stale_warning_never_shows_number_that_looks_accepted(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        config=STD_CONFIG + "sigfigs: 3\n",
        items={"LOG-001.md": log_item("LOG-001", "`R := 3.448 V = 3.5 V`")},
    )
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0  # stale is a warning, not an error
    assert "inline calc R: stored result says 3.5 V, now computes 3.448 V" in text
    # the formatted 3.45 sits inside the stored 3.5 window -- the warning
    # must show the raw value, never a number that looks accepted
    assert "computes 3.45 V" not in text


def test_scope_order_across_spans_and_fences(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        items={
            "LOG-001.md": log_item(
                "LOG-001",
                "`Vin := 12 V = 12 V`\n\n"
                "```calc\nP2 = Vin * 2 A | W\n```\n\n"
                "`V3 := Vin / 3 = 4 V`\n\n"
                "Rendered {{P2}} {{V3}}\n",
            )
        },
    )
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0, text
    cli(cfg, "build")
    out(capsys)
    page = (tmp_path / "_site" / "log-001.html").read_text(encoding="utf-8")
    assert "<code>24 W</code>" in page  # fence sees the inline name
    assert "<code>4 V</code>" in page  # span sees its own value
    # the span stays literal code on the page; it is not a calc-block target
    assert "Vin := 12 V = 12 V" in page
    assert "V3 := Vin / 3 = 4 V" in page


def test_duplicate_and_forward_use_errors(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        items={
            "LOG-001.md": log_item(
                "LOG-001", "`Vd := 1 V = 1 V`, dup: `Vd := 2 V = 2 V`"
            ),
            "LOG-002.md": log_item(
                "LOG-002", "`Q := A * 2 = 2 V`, later: `A := 1 V = 1 V`"
            ),
        },
    )
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 1
    assert "assigned twice" in text  # cites both lines (message carries line nos)
    assert "unknown name 'A'" in text  # forward use is the ordinary error


# ---------------------------------------------------------------- Case 3
# calc_hash probe and content hash. Contract section 3 rows 1-2.
# calc_hash probes: EXPECTED RED on base (calc_hash_for is fences-only).


def test_inline_only_item_has_calc_hash_probe(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        items={
            "LOG-A.md": log_item("LOG-A", "`N := 2 * 3 = 6`"),
            "LOG-B.md": log_item("LOG-B", "```calc\nV = 2 V\n```"),
        },
    )
    assert cli(cfg, "revision", "rev1") == 0
    out(capsys)
    items = baseline_items(tmp_path, "rev1")
    # section 3: "An inline-only item then has a calc_hash"
    assert items["LOG-A"].get("calc_hash"), (
        "EXPECTED-RED: inline-only item has no calc_hash (calc_hash_for is "
        "fences-only on this base; section 3 extends it to inline spans)"
    )
    assert items["LOG-B"].get("calc_hash")  # fence item, control


def test_result_only_edit_fixes_calc_hash_moves_content_hash(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        items={
            "LOG-A.md": log_item("LOG-A", "`N := 2 * 3 = 6`"),
            "LOG-B.md": log_item("LOG-B", "```calc\nV = 2 V\n```"),
        },
    )
    assert cli(cfg, "revision", "rev1") == 0
    out(capsys)
    rev1 = baseline_items(tmp_path, "rev1")
    assert rev1["LOG-A"].get("calc_hash"), "EXPECTED-RED: probe absent on base"

    # edit ONLY the stored result of A's span
    edit_file(tmp_path, "LOG-A.md", "= 6`", "= 5`")
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0  # stale is a warning
    assert "inline calc N: stored result says 5, now computes 6" in text
    # audit lists A as changed since rev1 (must run BEFORE stamping rev2)
    assert "LOG-A" in audit_changed_ids(cfg, capsys)
    assert cli(cfg, "revision", "rev2") == 0
    out(capsys)
    rev2 = baseline_items(tmp_path, "rev2")

    # calc_hash excludes the stored result: fixed by a result-only edit
    assert rev2["LOG-A"]["calc_hash"] == rev1["LOG-A"]["calc_hash"]
    # the content hash moves: a result correction is a real source edit
    assert rev2["LOG-A"]["hash"] != rev1["LOG-A"]["hash"]
    # no-inline churn control: the fence-only item is untouched
    assert rev2["LOG-B"]["hash"] == rev1["LOG-B"]["hash"]
    assert rev2["LOG-B"]["calc_hash"] == rev1["LOG-B"]["calc_hash"]

    # editing the RHS moves the probe
    edit_file(tmp_path, "LOG-A.md", "2 * 3", "2 * 4")
    assert cli(cfg, "revision", "rev3") == 0
    out(capsys)
    rev3 = baseline_items(tmp_path, "rev3")
    assert rev3["LOG-A"]["calc_hash"] != rev2["LOG-A"]["calc_hash"], (
        "EXPECTED-RED: inline RHS is not in calc_hash on this base"
    )


def test_mixed_item_probe_tracks_inline_rhs(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        items={
            "LOG-A.md": log_item(
                "LOG-A",
                "`Vi := 3 V = 3 V`\n\n```calc\nP = Vi * 2 A | W\n```\n",
            )
        },
    )
    assert cli(cfg, "revision", "rev1") == 0
    out(capsys)
    rev1 = baseline_items(tmp_path, "rev1")
    edit_file(tmp_path, "LOG-A.md", "= 3 V`\n\n", "= 3.5 V`\n\n")  # result only
    assert cli(cfg, "revision", "rev2") == 0
    out(capsys)
    rev2 = baseline_items(tmp_path, "rev2")
    assert rev2["LOG-A"]["calc_hash"] == rev1["LOG-A"]["calc_hash"]  # fixed
    assert rev2["LOG-A"]["hash"] != rev1["LOG-A"]["hash"]
    edit_file(tmp_path, "LOG-A.md", "Vi := 3 V = 3.5 V", "Vi := 4 V = 3.5 V")  # RHS edit
    assert cli(cfg, "revision", "rev3") == 0
    out(capsys)
    rev3 = baseline_items(tmp_path, "rev3")
    assert rev3["LOG-A"]["calc_hash"] != rev2["LOG-A"]["calc_hash"], (
        "EXPECTED-RED: inline RHS not in calc_hash on this base"
    )


def test_old_hash_format_baseline_reads_and_no_inline_churn(tmp_path, capsys):
    # Frozen fixture stamped by the origin/main CLI (hash_format 5, no inline
    # spans). Section 3: items without inline spans keep their old item hash;
    # the new format version must keep reading baselines stamped at 5.
    for name in ("refdes-project.yaml", "items", ".refdes"):
        src = FIXTURES / name
        dst = tmp_path / name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy(src, dst)
    cfg = tmp_path / "refdes-project.yaml"
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0, text
    assert cli(cfg, "revision", "rev2") == 0
    out(capsys)
    old = baseline_items(tmp_path, "hist")
    new = baseline_items(tmp_path, "rev2")
    for item_id in ("LOG-F", "CMP-P"):
        assert new[item_id]["hash"] == old[item_id]["hash"], (
            f"{item_id} churned: no-inline items must keep the old hash"
        )
    # the fence-only item keeps the block-only calc_hash value too
    assert new["LOG-F"]["calc_hash"] == old["LOG-F"]["calc_hash"]
    # and the stamped baseline is readable by the diff machinery
    assert audit_changed_ids(cfg, capsys) == []


# ---------------------------------------------------------------- Case 4
# cross-item reference used only in an inline span. Contract section 3 row 3.
# EXPECTED RED on base (span refs are not parsed; scan covers fences only).


CROSS_ITEMS = {
    "LOG-A.md": log_item("LOG-A", "```calc\nV_in = 12 V\n```"),
    "LOG-B.md": log_item("LOG-B", "`Vb := LOG-A.V_in = 12 V`"),
}


def test_cross_item_ref_in_span_evaluates(tmp_path, capsys):
    cfg = setup(tmp_path, items=dict(CROSS_ITEMS))
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0, (
        f"EXPECTED-RED: span-only cross-item ref fails on this base: {text}"
    )
    assert "inline calc" not in text


def test_upstream_change_marks_dependent(tmp_path, capsys):
    cfg = setup(tmp_path, items=dict(CROSS_ITEMS))
    assert cli(cfg, "check") == 0, "EXPECTED-RED: base errors the span ref"
    out(capsys)
    assert cli(cfg, "revision", "rev1") == 0
    out(capsys)
    before = item_files_bytes(tmp_path / "items" / "main" / "LOG-B.md")
    edit_file(tmp_path, "LOG-A.md", "V_in = 12 V", "V_in = 11 V")
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0
    assert "inline calc Vb: stored result says 12 V, now computes 11 V" in text
    # B's authored text is untouched
    assert item_files_bytes(tmp_path / "items" / "main" / "LOG-B.md") == before
    # ...yet the baseline diff lists B: the resolved value is a hash input
    changed = audit_changed_ids(cfg, capsys)
    assert "LOG-B" in changed, "EXPECTED-RED: span ref is no content-hash input"


def test_span_ref_expands_to_composite_key(tmp_path, capsys):
    # keys.md posture: structured refs are stored expanded as DISPLAY-ID@key;
    # section 3 extends the expansion pass to spans.
    cfg = setup(tmp_path, items=dict(CROSS_ITEMS))
    cli(cfg, "check")  # writable load expands bare refs to composites
    out(capsys)
    text = (tmp_path / "items" / "main" / "LOG-B.md").read_text(encoding="utf-8")
    assert "LOG-A@" in text, (
        "EXPECTED-RED: span ref not composite-expanded on this base "
        f"(file holds: {text!r})"
    )
    assert cli(cfg, "check") == 0
    out(capsys)


# ---------------------------------------------------------------- Case 5
# source() used only in an inline span. Contract section 3 row 4.
# EXPECTED RED on base (fetch discovers keys from fences only).

CSV = "key,value,note\neff,0.93,probe row\n"
SPAN_SRC = '`eff := source("analysis/pb.csv", "eff") | 1 = 0.93`'


def _source_project(tmp_path):
    return {
        "LOG-C.md": log_item(
            "LOG-C",
            SPAN_SRC,
            extra_front="citations:\n  - path: analysis/pb.csv\n",
        )
    }


def test_fetch_discovers_span_source_key(tmp_path, capsys):
    cfg = setup(tmp_path, items=_source_project(tmp_path))
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "pb.csv").write_text(CSV, encoding="utf-8")
    assert cli(cfg, "fetch") == 0
    out(capsys)
    lock = yaml.safe_load(
        (tmp_path / ".refdes" / "citations.yaml").read_text(encoding="utf-8")
    )
    entry = lock["citations"]["analysis/pb.csv"]
    assert "eff" in (entry.get("values") or {}), (
        "EXPECTED-RED: fetch pinned no source key from the span: "
        f"{entry!r}"
    )
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0, f"EXPECTED-RED: span source() has no locked value: {text}"
    assert "inline calc" not in text


def test_accepted_source_update_marks_item_changed(tmp_path, capsys):
    cfg = setup(tmp_path, items=_source_project(tmp_path))
    (tmp_path / "analysis").mkdir()
    csv_path = tmp_path / "analysis" / "pb.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    assert cli(cfg, "fetch") == 0
    out(capsys)
    assert cli(cfg, "check") == 0, "EXPECTED-RED: base cannot lock the span key"
    out(capsys)
    assert cli(cfg, "revision", "rev1") == 0
    out(capsys)
    csv_path.write_text(CSV.replace("0.93", "0.95"), encoding="utf-8")
    assert cli(cfg, "fetch", "--update") == 0
    out(capsys)
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0  # accepted value moves the computed result
    assert "inline calc eff: stored result says 0.93, now computes 0.95" in text, (
        "EXPECTED-RED: span source() not evaluated from the lockfile on base"
    )
    # the locked value is a content-hash input: text untouched, item changed
    assert "LOG-C" in audit_changed_ids(cfg, capsys), "EXPECTED-RED on base"


def test_span_source_without_same_item_citation_is_error(tmp_path, capsys):
    # the fence is a CONTROL: valid calc (`x = 1`) so exit 1 can only come
    # from the citation rule -- `x := 1 = 1` was invalid calc, and the CLI's
    # "expected an assignment of the form" error would let `code == 1` pass
    # on the wrong cause (round-5 review, chunk 2).
    files = {
        "LOG-C.md": log_item(
            "LOG-C",
            "```calc\nx = 1\n```",
            extra_front="citations:\n  - path: analysis/pb.csv\n",
        ),
        "LOG-D.md": log_item("LOG-D", SPAN_SRC),  # cites nothing
    }
    cfg = setup(tmp_path, items=files)
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis" / "pb.csv").write_text(CSV, encoding="utf-8")
    code = cli(cfg, "check")
    text = out(capsys)
    # the existing same-item citation rule is kept (contract: no new reader,
    # no new authorization) -- with the control fence valid, the only error
    # is that rule; name it, don't just count the exit code
    assert code == 1
    assert "inline calc eff" in text and "analysis/pb.csv" in text
    assert "does not cite 'analysis/pb.csv'" in text, text
    assert "expected an assignment" not in text, (
        "control fence must be valid calc: a syntax error lets code == 1 "
        "pass on the wrong cause"
    )


# ---------------------------------------------------------------- Case 6
# seals, captured history, release gate. Contract section 2 (gate), section 3
# row 5. (a)/(b) are controls, GREEN on base; the gate pair (c) is an
# INTEGRATION against #345's gate (not a #347-only defect) -- red on the old
# base because the rule name predates it.

NOTE_CONFIG = STD_CONFIG + (
    "types:\n"
    "  note:\n"
    "    extends: log\n"
    "    prefix: NOTE\n"
    "    label: Note\n"
    "    plural: Notes\n"
    "    append_only: true\n"
    "    sealing: build\n"
    "    include: [invalidate_body]\n"
    "    doc: probe type\n"
    "    fields: {}\n"
)


def test_sealed_span_literal_edit_fails_seal_untouched_source(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        config=NOTE_CONFIG,
        items={"NOTE-S.md": log_item("NOTE-S", "`Sn := 2 V + 1 V = 3 V`", type="note")},
    )
    assert cli(cfg, "build") == 0
    text = out(capsys)
    assert "ERROR" not in text  # first build is clean
    seal = yaml.safe_load((tmp_path / ".refdes" / "log-seal.yaml").read_text())
    assert "NOTE-S" in seal["sealed"]
    edit_file(tmp_path, "NOTE-S.md", "= 3 V", "= 3.5 V")
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 1
    assert "append-only" in text and "modified since it was sealed" in text  # existing seal check
    assert "inline calc Sn: stored result says 3.5 V, now computes 3 V" in text
    assert cli(cfg, "build") == 1
    out(capsys)
    # verification is read-only for sealed entries: bytes as authored
    text = (tmp_path / "items" / "main" / "NOTE-S.md").read_text(encoding="utf-8")
    assert "`Sn := 2 V + 1 V = 3.5 V`" in text  # stored, not rewritten
    seal2 = yaml.safe_load((tmp_path / ".refdes" / "log-seal.yaml").read_text())
    assert seal2["sealed"] == seal["sealed"]  # no auto-reseal


def test_captured_history_stale_edit_keeps_existing_signals(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        items={"LOG-V.md": log_item("LOG-V", "`Vv := 2 V + 2 V = 4 V`")},
    )
    assert cli(cfg, "history", "capture", "LOG-V") == 0
    out(capsys)
    edit_file(tmp_path, "LOG-V.md", "= 4 V", "= 5 V")
    code = cli(cfg, "check")
    text = out(capsys)
    assert code == 0
    # existing capture/edit signal survives the inline slice, and the stale
    # span warns inside a protected historical entry (contract section 2:
    # reported on every verification run; the text is not rewritten)
    assert "edited after captured" in text
    assert "inline calc Vv: stored result says 5 V, now computes 4 V" in text
    assert cli(cfg, "audit") == 0
    audit = out(capsys)
    assert "LOG-V" in audit.split("Entries edited after captured", 1)[1][:200]


# INTEGRATION, not a #347 defect surface: the release gate lives in #345;
# these two tests check #347's inline spans feed that pre-existing gate
# (contract section 2's gate row) -- red on the old base only because the
# rule name does not exist there at all.
GATE_CONFIG = STD_CONFIG + (
    "release_gate:\n"
    "  inline_calc_results: { release: true, revision: false }\n"
)


@GATE_INTEGRATION
def test_release_gate_fails_stale_editable_revision_passes(tmp_path, capsys):
    cfg = setup(
        tmp_path,
        config=GATE_CONFIG,
        items={"LOG-A.md": log_item("LOG-A", "`N := 2 * 3 = 6`")},
    )
    edit_file(tmp_path, "LOG-A.md", "= 6`", "= 5`")
    code = cli(cfg, "release", "relgate")
    text = out(capsys)
    assert "not a known rule" not in text, (
        "EXPECTED-RED: inline_calc_results is not a known gate rule on base"
    )
    assert code == 1, f"EXPECTED-RED on base: release returned {code}: {text}"
    assert not (tmp_path / ".refdes" / "baselines" / "relgate.yaml").exists()
    # revision half defaults false: the checkpoint stamps with warnings up
    assert cli(cfg, "revision", "revgate") == 0
    out(capsys)
    assert (tmp_path / ".refdes" / "baselines" / "revgate.yaml").exists()


@GATE_INTEGRATION
def test_release_gate_exempt_for_captured_history(tmp_path, capsys):
    # Adapted at the #345 head: the blind copy authored the stale result
    # AFTER the capture (an edit-after-capture), which #345's implemented
    # exemption is deliberately narrow about -- a post-capture edit leaves
    # the live item editable (`captured_edits` defaults off), so its stale
    # span stays a release offender. The frozen shape is a capture taken IN
    # the stale state with no later edit: digest matches the snapshot, the
    # item is not editable prose, the gate exempts it.
    cfg = setup(
        tmp_path,
        config=GATE_CONFIG,
        items={"LOG-V.md": log_item("LOG-V", "`Vv := 2 V + 2 V = 5 V`")},
    )
    assert cli(cfg, "history", "capture", "LOG-V") == 0
    out(capsys)
    code = cli(cfg, "release", "relgate2")
    text = out(capsys)
    assert "not a known rule" not in text, "EXPECTED-RED: rule absent on base"
    assert code == 0, (
        f"EXPECTED-RED on base: stale CAPTURED entry must be exempt from the "
        f"freshness gate (release returned {code}): {text}"
    )
    # warning stays visible even though the gate exempts it
    assert "inline calc Vv: stored result says 5 V, now computes 4 V" in text
