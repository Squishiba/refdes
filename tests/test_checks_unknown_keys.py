"""An unknown key inside a `checks:` entry is a diagnostic, not silence.

Run-5 F7. On a project with the bundled `hardware@3` standard:

    checks:
      - rule: P_dens stays inside the packaging limit
        value: P_dens
        against: BND-PWR-001
        exrta: typo of extra

`refdes check` printed `2 items, 0 errors, 1 warnings` (the 1 warning being
the project's own coverage notice) and exited 0. Neither unknown key was
mentioned. The schema the tool writes for the editor says otherwise --
`.refdes/schema.json` declares that sub-mapping with `additionalProperties:
false` and `required: [value, against]` (`schema_json.py:70-81`), which is
what makes an unknown key light up in the editor the moment it is typed
(`docs/design/standard-library.md` §12) while the CLI, which is the thing CI
runs, says nothing. So the published schema and the enforced schema disagreed.

Severity follows the rule the docs already state for an unknown key one level
up, at the item's own front matter (`docs/authoring.md:267-292`, repeated at
`docs/troubleshooting.md:103-109`, implemented at `parse.py:965-992`):

* a key whose spelling is **close** to one that is legal is a build **error**
  naming the key it thinks you meant -- a misspelled key is that key's value
  going nowhere, and a warning is not something a green build can be trusted
  to have caught;
* a key with **nothing close** to it stays a **warning**, and the value is
  kept: forward-compatible metadata, a field a future version will declare,
  deliberate extra data. There is no typo to correct there.

`exrta` and `rule` are the second case -- neither is close to `value` or
`against` -- which is also what the report itself contrasts the gap against
("Top-level unknown fields *are* warned about"). The first case is reachable
here too, because an entry that has lost its `value:` or `against:` key
outright is refused by `run_checks`' existing shape error before this branch
ever sees it: what reaches it is an *extra* key beside a valid pair, and
`values:`/`agaiist:` are the misspellings of that pair.
"""

from __future__ import annotations

import traceback

import pytest
from conftest import write_project_config

from refdes import cli as cli_mod

CONFIG = (
    "site: { title: Checks unknown keys, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

BOUND = (
    "---\n"
    "id: BND-PWR-001\n"
    "type: bound\n"
    "title: Peak density bound\n"
    'limit: "<= 600 mW/in^2"\n'
    "status: active\n"
    "---\n\nThe bound.\n"
)


def _decision(checks_yaml: str) -> str:
    return (
        "---\n"
        "id: DEC-PWR-001\n"
        "type: decision\n"
        "title: Which regulator topology for the 3V3 rail\n"
        "status: proposed\n"
        "checks:\n"
        f"{checks_yaml}"
        "---\n\n"
        "```calc\nP_dens = 0.4 W/in^2\n```\n\nThe topology.\n"
    )


EXTRA_KEYS = (
    "  - rule: P_dens stays inside the packaging limit\n"
    "    value: P_dens\n"
    "    against: BND-PWR-001\n"
    "    exrta: typo of extra\n"
)

NEAR_MISS = (
    "  - value: P_dens\n"
    "    against: BND-PWR-001\n"
    "    values: P_dens\n"
)

VALID = "  - value: P_dens\n    against: BND-PWR-001\n"

MISSING_VALUE = "  - against: BND-PWR-001\n"


def _project(tmp_path, checks_yaml: str):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bnd.md").write_text(BOUND, encoding="utf-8")
    (items / "dec.md").write_text(_decision(checks_yaml), encoding="utf-8")
    return tmp_path


def _check(root) -> int:
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])


# ------------------------------------------------------- the report's repro


def test_an_extra_key_in_a_checks_entry_is_warned_about(tmp_path, capsys):
    """F7 verbatim: the run was green and silent about both keys."""
    root = _project(tmp_path, EXTRA_KEYS)
    assert _check(root) == 0  # a warning, not an error -- see the docstring
    out = capsys.readouterr().out
    assert "unknown key 'exrta'" in out
    assert "unknown key 'rule'" in out
    assert "1 errors" not in out


def test_the_warning_says_what_the_entry_may_hold(tmp_path, capsys):
    """A warning that names the offending key but not the legal set sends the
    reader back to the file to guess; the top-level diagnostic it mirrors
    names what it expected."""
    root = _project(tmp_path, EXTRA_KEYS)
    _check(root)
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "unknown key 'exrta'" in line)
    assert "checks:" in line
    assert "'value'" in line and "'against'" in line


def test_a_near_miss_key_is_an_error(tmp_path, capsys):
    """The docs' first tier: `values:` is `value:` misspelled, and a value
    that goes nowhere is not something a warning can be trusted to catch."""
    root = _project(tmp_path, NEAR_MISS)
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "unknown key 'values'" in err
    assert "did you mean" in err and "'value'" in err


# ------------------------------------------------------------ what stays put


NON_STRING = "  - value: P_dens\n    against: BND-PWR-001\n    true: YAML reads a bool\n"


def test_a_non_string_key_crashes_where_it_already_did_not_in_the_new_loop(tmp_path):
    """YAML reads `true:` as the bool, not the string, and sorting that beside
    the entry's string keys raises. It already raised one step later, inside
    `compute_hashes`' `json.dumps(..., sort_keys=True)` -- verified against an
    unmodified source tree, so that crash is pre-existing and not this branch's
    to fix. What *is* this branch's: the unknown-key loop runs one step
    earlier, so it must not become the new crash site. Pinned by frame name.
    """
    root = _project(tmp_path, NON_STRING)
    with pytest.raises(TypeError) as exc:
        _check(root)
    frames = [f.name for f in traceback.extract_tb(exc.value.__traceback__)]
    assert "compute_hashes" in frames
    assert "run_checks" not in frames


def test_a_valid_checks_entry_draws_no_diagnostic(tmp_path, capsys):
    """The pair this cannot regress: `value` and `against` alone stay green,
    or every decision in every project with a check starts warning."""
    root = _project(tmp_path, VALID)
    assert _check(root) == 0
    assert "unknown key" not in capsys.readouterr().out


def test_a_missing_value_is_still_the_shape_error_alone(tmp_path, capsys):
    """An entry that lost `value:` outright is refused by the existing shape
    error, which `continue`s -- so the same keystroke is not also reported as
    an unknown key."""
    root = _project(tmp_path, MISSING_VALUE)
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "each checks: entry needs 'value' and 'against'" in err
    assert "unknown key" not in err
