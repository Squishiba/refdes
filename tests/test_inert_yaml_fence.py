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

import json

import pytest

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

REQUIREMENT = (
    "---\n"
    "id: REQ-PWR-001\n"
    "type: requirement\n"
    "status: active\n"
    "---\n\nThe requirement.\n"
)


def _log(checks_block: str, body_fence: str = "", front_extra: str = "") -> str:
    """A log item; `checks_block` is a `checks:`-shaped block for the front
    matter (empty for none) and `body_fence` a fenced block for the body."""
    front = f"checks:\n{checks_block}" if checks_block else ""
    front += front_extra
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
    (items / "req.md").write_text(REQUIREMENT, encoding="utf-8")
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


# ------------------------------------------ R10-F1: a declared link verb

VERB_FENCE = "```yaml\nsatisfies: [REQ-PWR-001]\n```\n"


def _index(capsys, root) -> dict:
    """Run `refdes index` and return the parsed JSON document."""
    cli_mod.main(["-c", str(root / "refdes-project.yaml"), "index"])
    return json.loads(capsys.readouterr().out)


def test_link_verb_fence_warns(tmp_path, capsys):
    """R10-F1: `satisfies:` as a body fence is inert (`index` shows
    `links: {}`) and was silent. It now warns, naming the verb and the
    front-matter fix -- verbs are front-matter keys too (docs/links.md,
    "Declaring links"). Sabotage: match only `spec.fields` and the verb
    fence prints nothing."""
    root = _project(tmp_path, _log("", VERB_FENCE))
    code, out = _check(capsys, root)
    fence_lines = [l for l in out.splitlines() if "front matter" in l]
    assert len(fence_lines) == 1
    assert "'satisfies'" in fence_lines[0]
    assert "link" in fence_lines[0]
    assert code == 0


def test_link_verb_fence_is_inert(tmp_path, capsys):
    """The fence's verb never lands: the item's links stay empty. Sabotage:
    make body fences parse as links and this no longer shows `{}`."""
    root = _project(tmp_path, _log("", VERB_FENCE))
    doc = _index(capsys, root)
    log_item = next(i for i in doc["items"] if i["id"] == "LOG-A-001")
    assert log_item["links"] == {}


def test_link_verb_front_matter_lands(tmp_path, capsys):
    """The warning's remedy, verified by following it: `satisfies:` in the
    front matter resolves -- the link is in the index, coverage sees it, and
    the inert-fence warning is gone."""
    root = _project(tmp_path, _log("", "", front_extra="satisfies: [REQ-PWR-001]\n"))
    _, out = _check(capsys, root)
    assert "front matter" not in out
    doc = _index(capsys, root)
    log_item = next(i for i in doc["items"] if i["id"] == "LOG-A-001")
    assert any("REQ-PWR-001" in t for t in log_item["links"]["satisfies"])
    # A `proposed` log claims, it does not satisfy (docs/coverage.md).
    assert doc["coverage"]["REQ-PWR-001"]["claimed_by"] == ["LOG-A-001"]


def test_verb_of_another_type_does_not_fire(tmp_path, capsys):
    """`refines` is a `requirement` verb, not a `log` one (verified against
    `Project.types['log'].links`) -- a fence naming it is example code, not
    this item's inert link. Sabotage: match verbs of every type."""
    alien = "```yaml\nrefines: [REQ-PWR-001]\n```\n"
    root = _project(tmp_path, _log(VALID_CHECKS, alien))
    _, out = _check(capsys, root)
    assert "front matter" not in out


# --------------------------------------- R10-F2: the id/type front matter

def test_type_id_fence_warns(tmp_path, capsys):
    """R10-F2: `type:`/`id:` in a body fence are inert (the item's type and
    id come from the real front matter) and were silent. They are
    front-matter keys (parse.py's RESERVED), so they warn the same way.
    Sabotage: match only fields and links and this prints nothing."""
    fence = "```yaml\ntype: log\nid: LOG-A-001\n```\n"
    root = _project(tmp_path, _log(VALID_CHECKS, fence))
    _, out = _check(capsys, root)
    fence_lines = [l for l in out.splitlines() if "front matter" in l]
    assert len(fence_lines) == 1
    assert "'type'" in fence_lines[0] and "'id'" in fence_lines[0]
    assert "key" in fence_lines[0]


# ------------------------------------------ R10-F3: the blockquoted fence

def test_blockquote_fence_warns(tmp_path, capsys):
    """R10-F3: a `> ```yaml ` fence renders as a real code block (the build
    emits `<blockquote><pre><code class="language-yaml">`) and warned
    nothing. The scanner strips blockquote markers line-wise first; the
    warning still points at the fence's own line. Sabotage: scan the raw
    body only and `> ` disqualifies the fence."""
    fence = (
        "> ```yaml\n"
        "> checks:\n"
        ">   - value: P_dens\n"
        ">     against: BND-THM-001\n"
        "> ```\n"
    )
    root = _project(tmp_path, _log("", fence))
    _, out = _check(capsys, root)
    line = next(l for l in out.splitlines() if "front matter" in l)
    assert "'checks'" in line
    reported = int(line.split("items/log.md:")[1].split(" ")[0])
    text = (tmp_path / "items" / "log.md").read_text(encoding="utf-8")
    fence_line = next(
        i + 1 for i, l in enumerate(text.splitlines())
        if l.strip().lstrip("> ") == "```yaml"
    )
    assert reported == fence_line


# ------------------------------------- R10-F4: a fence escaped by a fence

def test_nested_yaml_fence_in_outer_fence_is_silent(tmp_path, capsys):
    """R10-F4: a ```yaml example *inside* an outer ```text fence is example
    code and warned -- with the nonsense remedy. The scanner must consume a
    fence's content as literal text: a nested opener is never a fence of
    its own. Sabotage: scan yaml fences independently of the outer fence
    and 'status' fires."""
    escaped = "```text\n```yaml\nstatus: draft\n```\n```\n"
    root = _project(tmp_path, _log(VALID_CHECKS, escaped))
    _, out = _check(capsys, root)
    assert "front matter" not in out


def test_yaml_fence_inside_an_unterminated_text_fence_is_silent(tmp_path, capsys):
    """Same trap, other nesting: a fence opened by the outer `text` fence
    that the document never closes swallows the rest of the body, so the
    yaml opener inside it is literal text. Sabotage: the pre-fix regex
    matched the nested opener."""
    escaped = "```text\nsee the example:\n\n```yaml\nstatus: draft\n```\n"
    root = _project(tmp_path, _log(VALID_CHECKS, escaped))
    _, out = _check(capsys, root)
    assert "front matter" not in out


# ------------------------------------------- R10: the run-10 spelling table

FIRE = "checks:\n  - value: P_dens\n    against: BND-THM-001\n"

REGRESSION_SPELLINGS = [
    # (label, body, expected inert key names -- [] means must stay silent)
    ("plain yaml fence", "```yaml\n" + FIRE + "```\n", ["checks"]),
    ("yml fence", "```yml\n" + FIRE + "```\n", ["checks"]),
    ("YAML fence", "```YAML\n" + FIRE + "```\n", ["checks"]),
    ("fence attributes", '```yaml title="demo"\n' + FIRE + "```\n", ["checks"]),
    ("tilde fence", "~~~yaml\n" + FIRE + "~~~\n", ["checks"]),
    (
        "indented in a list item",
        "- note:\n  ```yaml\n  checks:\n    - value: P_dens\n      against: BND-THM-001\n  ```\n",
        ["checks"],
    ),
    (
        "4-space indented",
        "    ```yaml\n    checks:\n      - value: P_dens\n        against: BND-THM-001\n    ```\n",
        ["checks"],
    ),
    (
        "two fences, two warnings",
        "```yaml\nsummary: one\n```\n\ntext\n\n```yaml\nstatus: draft\n```\n",
        ["summary", "status"],
    ),
    (
        "one fence, two keys",
        "```yaml\nsummary: one\nstatus: draft\n```\n",
        ["summary", "status"],
    ),
    ("link verb", VERB_FENCE, ["satisfies"]),
    ("type and id", "```yaml\ntype: log\nid: LOG-A-001\n```\n", ["type", "id"]),
    (
        "blockquote fence",
        "> ```yaml\n> checks:\n>   - value: P_dens\n>     against: BND-THM-001\n> ```\n",
        ["checks"],
    ),
    ("escaped in text fence", "```text\n```yaml\nstatus: draft\n```\n```\n", []),
    ("other type's field", "```yaml\npart_number: \"123\"\n```\n", []),
    ("other type's verb", "```yaml\nrefines: [REQ-PWR-001]\n```\n", []),
    ("list fence", "```yaml\n- a list\n- not a mapping\n```\n", []),
    ("scalar fence", "```yaml\njust a scalar\n```\n", []),
    ("unparseable fence", "```yaml\nkey: [unclosed\n  bad: : :\n```\n", []),
]


@pytest.mark.parametrize(
    "label,body,expected",
    REGRESSION_SPELLINGS,
    ids=[case[0] for case in REGRESSION_SPELLINGS],
)
def test_run10_spelling_table(tmp_path, capsys, label, body, expected):
    """Every spelling user-sim run 10 swept (report section 1) keeps its
    verdict: the firing shapes fire naming exactly these keys, the silent
    shapes stay silent."""
    root = _project(tmp_path, _log(VALID_CHECKS, body))
    _, out = _check(capsys, root)
    fence_lines = [l for l in out.splitlines() if "front matter" in l]
    if not expected:
        assert fence_lines == []
        return
    names = ", ".join(l.split("declares ")[1].split(" --")[0] for l in fence_lines)
    for name in expected:
        assert f"'{name}'" in names


def test_other_types_own_shapes_fire(tmp_path, capsys):
    """Run 10 fired the same warning on a component's `checks:` fence and a
    bound's `limit:` fence; both still fire, each at its own type.
    Sabotage: hardcode the scan to `log` and these go silent."""
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "bnd.md").write_text(
        BOUND.replace("---\n\nThe bound.\n", "---\n\nBound:\n\n```yaml\nlimit: \"<= 1 W/in^2\"\n```\n"),
        encoding="utf-8",
    )
    (items / "cmp.md").write_text(
        "---\nid: CMP-A-001\ntype: component\ntitle: Part\n---\n\n" + INERT_FENCE,
        encoding="utf-8",
    )
    _, out = _check(capsys, tmp_path)
    lines = [l for l in out.splitlines() if "front matter" in l]
    assert len(lines) == 2
    assert any("bnd.md" in l and "'limit'" in l and "type 'bound'" in l for l in lines)
    assert any("cmp.md" in l and "'checks'" in l and "type 'component'" in l for l in lines)


def test_list_file_body_fires(tmp_path, capsys):
    """The list-file spelling (run 10): a fence in a `body: |` block warns,
    at the item's source line (a list item has no fence-mappable body).
    Sabotage: require a `body_line` and the list-file warning disappears."""
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "logs.yaml").write_text(
        "defaults:\n  type: log\n  prefix: LOG\n"
        "items:\n  - id: LOG-L-001\n    summary: Entry\n"
        "    body: |\n      ```yaml\n      summary: dup\n      ```\n",
        encoding="utf-8",
    )
    _, out = _check(capsys, tmp_path)
    assert any("items/logs.yaml" in l and "'summary'" in l for l in out.splitlines())
