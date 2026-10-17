"""A ```yaml fence in an item body declaring a field of its type is inert.

Finding R9-F1 (user-sim run 9): following `docs/checks.md`'s "Declaring a
check" example -- a ```calc fence and a ```yaml `checks:` fence sitting
adjacently in an item's body -- an author writes the bound check as a body
fence. It renders as literal text on the page, the bound check silently never
runs, and `refdes check` reports 0 errors. The front-matter spelling works and
reports the violation.

The diagnostic (build.declares_inert_keys / validate_items): when an item
body contains a ```yaml (or ```yml) fence whose content parses as a mapping
naming a field its own type declares (at minimum `checks`), warn naming the
key and the fix. It stays narrow: a yaml fence of example code with no
declared field key does not fire, a fence whose key is not a field of *this*
type does not fire, and a non-mapping fence does not fire. The body's
rendering is unchanged.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import cli as cli_mod

CONFIG = (
    "site: { title: Inert yaml fence, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

BOUND = (
    "---\n"
    "id: BND-THM-001\n"
    "type: bound\n"
    'limit: "<= 0.15 W/in^2"\n'
    "status: active\n"
    "---\n\nThe bound.\n"
)


def _log(checks_block: str, body_fence: str = "") -> str:
    """A log item; `checks_block` is a `checks:`-shaped block for the front
    matter (empty for none) and `body_fence` a fenced block for the body."""
    front = f"checks:\n{checks_block}" if checks_block else ""
    body = "```calc\nP_dens = 0.2 W/in^2\n```\n"
    if body_fence:
        body = body + "\n" + body_fence + "\n"
    return (
        "---\n"
        "id: LOG-A-001\n"
        "type: log\n"
        "summary: Thermal analysis\n"
        f"{front}"
        "---\n\n"
        "Computed density:\n\n"
        f"{body}"
    )


INERT_FENCE = (
    "```yaml\n"
    "checks:\n"
    "  - value: P_dens\n"
    "    against: BND-THM-001\n"
    "```\n"
)
VALID_CHECKS = "  - value: P_dens\n    against: BND-THM-001\n"


def _project(tmp_path, log_text: str):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bnd.md").write_text(BOUND, encoding="utf-8")
    (items / "log.md").write_text(log_text, encoding="utf-8")
    return tmp_path


def _check(capsys, root) -> tuple[int, str]:
    """Run `refdes check` and return (exit code, every diagnostic line it
    printed): warnings land on stdout, errors on stderr -- a test that reads
    only one stream silently tests half the output."""
    code = cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# --------------------------------------------------------------- the repro

def test_inert_yaml_fence_warns(tmp_path, capsys):
    """The R9-F1 repro: `checks:` as a body fence is inert -- `check` used to
    report 0 errors. It now warns, naming the key and the fix. Sabotage:
    revert the `declares_inert_keys` call in `validate_items` and this fails
    (no warning line at all)."""
    root = _project(tmp_path, _log("", INERT_FENCE))
    code, out = _check(capsys, root)
    fence_lines = [l for l in out.splitlines() if "front matter" in l]
    assert len(fence_lines) == 1
    assert "'checks'" in fence_lines[0]
    # The check is inert, so it is a warning, not a violation error.
    assert code == 0
    assert "0 errors" in out


def test_warning_names_the_fence_line(tmp_path, capsys):
    """The warning points at the fence, not the item's front matter -- the
    author is reading the body where the fence sits. Sabotage: report at
    `item.source_line` unconditionally and the reported line is the front
    matter, not the fence."""
    root = _project(tmp_path, _log("", INERT_FENCE))
    _, out = _check(capsys, root)
    line = next(l for l in out.splitlines() if "front matter" in l)
    reported = int(line.split("items/log.md:")[1].split(" ")[0])
    text = (tmp_path / "items" / "log.md").read_text(encoding="utf-8")
    fence_line = next(
        i + 1 for i, l in enumerate(text.splitlines()) if l.strip() == "```yaml"
    )
    assert reported == fence_line


def test_yaml_fence_without_field_key_does_not_fire(tmp_path, capsys):
    """A yaml fence of genuine example code -- no key that is a field of the
    item's type -- stays silent. Sabotage: drop the `str(key) in field_names`
    guard in `declares_inert_keys` and this fires."""
    benign = "```yaml\nexample_key:\n  nested: 1\n```\n"
    root = _project(tmp_path, _log(VALID_CHECKS, benign))
    _, out = _check(capsys, root)
    assert "example_key" not in out
    assert "front matter" not in out


def test_key_not_a_field_of_this_type_does_not_fire(tmp_path, capsys):
    """`limit` is a `bound` field, not a `log` field -- a log body fence naming
    `limit:` is example code, not this item's inert front matter. Sabotage:
    match against every declared field of every type and this fires."""
    alien = "```yaml\nlimit: \"<= 1 W/in^2\"\n```\n"
    root = _project(tmp_path, _log(VALID_CHECKS, alien))
    _, out = _check(capsys, root)
    assert "front matter" not in out


def test_non_mapping_yaml_fence_does_not_fire(tmp_path, capsys):
    """A yaml fence that parses to a list is not an inert mapping. Sabotage:
    drop the `isinstance(parsed, dict)` guard and this fires."""
    listing = "```yaml\n- a list\n- not a mapping\n```\n"
    root = _project(tmp_path, _log(VALID_CHECKS, listing))
    _, out = _check(capsys, root)
    assert "front matter" not in out


def test_yml_fence_also_fires(tmp_path, capsys):
    """The ```yml spelling is the same trap. Sabotage: match only ```yaml."""
    fence = INERT_FENCE.replace("```yaml", "```yml", 1)
    root = _project(tmp_path, _log("", fence))
    _, out = _check(capsys, root)
    assert "front matter" in out


# ---------------------------------------------- front matter still runs

def test_front_matter_checks_still_run(tmp_path, capsys):
    """The correct shape: `checks:` in front matter runs the check and reports
    the violation, with no inert-fence warning. Sabotage: a regression that
    stops front-matter checks from running fails the violation assertion."""
    root = _project(tmp_path, _log(VALID_CHECKS, ""))
    code, out = _check(capsys, root)
    assert code == 1
    assert "P_dens violates BND-THM-001" in out
    assert "front matter" not in out
