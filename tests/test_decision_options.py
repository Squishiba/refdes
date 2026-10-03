"""A `decision.options:` entry is a mapping, and a list of strings is a build error.

The repro, on a project with the bundled `hardware@3` standard:

    items/d.yaml
      - id: DEC-X-001
        title: Which regulator topology for the 3V3 rail
        status: proposed
        options:
          - Linear regulator          # meant as a name; the panel wants a mapping
          - Switching regulator

`refdes check` reported `1 items, 0 errors, 0 warnings` and exited 0, and then
`refdes build` died inside the render with
`jinja2.exceptions.UndefinedError: 'str object' has no attribute 'get'`
(`item.html.j2`, the options-considered panel), exit 1, with a raw Jinja2
traceback in place of a diagnostic. Not a regression: it reproduces on the
commit before the one this was found on.

The shape is the schema's own, read from `refdes schema` rather than from
memory: `decision.fields.options` is an array of objects with `name`, `verdict`
and `because`, `additionalProperties: false`, and no required key -- which is
exactly what the panel reads (`opt.get('name')`, `opt.get('verdict')` falling
back to `considered`, `opt.get('because')` optional). So a mapping with only a
`name:` is a valid option and stays legal here; what is not legal is an entry
that is not a mapping at all, because nothing can render it.

The validator already refused the two neighbouring mistakes and simply had no
branch for this one: a scalar `options:` is refused at load time
(`parse._reject_scalar_collection`, `options` being in
`NON_SCALAR_FIELD_TYPES`), and a non-mapping entry under `checks:` is refused
by name (`run_checks`: "each checks: entry needs 'value' and 'against'"). The
fix is the missing branch, in the same posture and at the same granularity --
one error per bad entry, on the item, naming the field and what a valid option
looks like.

The two templates that render the panel also skip a non-mapping entry. That is
a guard, not the fix: `refdes build` renders a project it has diagnosed (see
the run-5 note on a half-written `_site/`), so without it the traceback comes
back the moment the item page is rendered -- and the diagnostic, which is the
part a user can act on, never gets printed.
"""

from __future__ import annotations

from conftest import write_project_config

from refdes import cli as cli_mod

# The bundled standard, not a hand-rolled schema: the bug is about the real
# `decision` type's `options:` field, and this is the project the repro ran.
CONFIG = (
    "site: { title: Decision options, out: _site }\n"
    "standard: { base: hardware, version: 3 }\n"
)

STRING_OPTIONS = (
    "defaults: { type: decision, prefix: DEC }\n"
    "items:\n"
    "  - id: DEC-X-001\n"
    "    title: Which regulator topology for the 3V3 rail\n"
    "    status: proposed\n"
    "    options:\n"
    "      - Linear regulator\n"
    "      - Switching regulator\n"
)

MAPPING_OPTIONS = (
    "defaults: { type: decision, prefix: DEC }\n"
    "items:\n"
    "  - id: DEC-X-001\n"
    "    title: Which regulator topology for the 3V3 rail\n"
    "    status: proposed\n"
    "    options:\n"
    "      - name: Linear regulator\n"
    "        verdict: rejected\n"
    "        because: Dissipates 10.4 W at full load.\n"
    "      - name: Switching regulator\n"
    "        verdict: chosen\n"
    "        because: 93 % efficiency at half load.\n"
)

NAME_ONLY_OPTIONS = (
    "defaults: { type: decision, prefix: DEC }\n"
    "items:\n"
    "  - id: DEC-X-001\n"
    "    title: Which regulator topology for the 3V3 rail\n"
    "    status: proposed\n"
    "    options:\n"
    "      - name: Linear regulator\n"
)

SCALAR_OPTIONS = (
    "defaults: { type: decision, prefix: DEC }\n"
    "items:\n"
    "  - id: DEC-X-001\n"
    "    title: Which regulator topology for the 3V3 rail\n"
    "    status: proposed\n"
    "    options: Linear regulator or switching regulator\n"
)

STRING_CHECKS = (
    "defaults: { type: decision, prefix: DEC }\n"
    "items:\n"
    "  - id: DEC-X-001\n"
    "    title: Which regulator topology for the 3V3 rail\n"
    "    status: proposed\n"
    "    checks:\n"
    "      - P_diss\n"
    "      - BND-THM-001\n"
)


def _project(tmp_path, item_yaml: str):
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "d.yaml").write_text(item_yaml, encoding="utf-8")
    return tmp_path


def _check(root) -> int:
    return cli_mod.main(["-c", str(root / "refdes-project.yaml"), "check"])


def _build(root) -> int:
    return cli_mod.main([
        "-c", str(root / "refdes-project.yaml"), "build", "-o", str(root / "_site"),
    ])


# --------------------------------------------------------------- the exact repro


def test_a_list_of_strings_options_is_a_check_error(tmp_path, capsys):
    """B1 verbatim. Before the fix this printed `1 items, 0 errors, 0 warnings`
    and exited 0, leaving the crash for `build` to find."""
    root = _project(tmp_path, STRING_OPTIONS)
    assert _check(root) == 1
    err = capsys.readouterr().err
    # Item-granular like its neighbours: the item's own line and id, and the
    # index of the entry that is not an option.
    assert "items/d.yaml:3" in err
    assert "DEC-X-001" in err
    assert "options[0]" in err
    # Names the field, says what was wrong, and shows a valid option.
    assert "'Linear regulator' is not an option" in err
    assert "a mapping with a 'name'" in err
    assert "'verdict'" in err and "'because'" in err


def test_every_bad_entry_is_reported_not_just_the_first(tmp_path, capsys):
    """One error per entry, like the `citations:` branch it sits beside: an
    author with two wrong entries fixes two, not one per build."""
    root = _project(tmp_path, STRING_OPTIONS)
    assert _check(root) == 1
    captured = capsys.readouterr()
    assert "options[0]" in captured.err and "options[1]" in captured.err
    assert "2 errors" in captured.out


# ------------------------------------------------------------- the valid shapes


def test_a_list_of_option_mappings_builds_green(tmp_path, capsys):
    """The other half of the pair, and the reason the error is a good one: the
    same options written the way the schema declares them check with no
    diagnostics at all."""
    root = _project(tmp_path, MAPPING_OPTIONS)
    assert _check(root) == 0
    assert "0 errors" in capsys.readouterr().out


def test_an_option_with_only_a_name_is_still_valid(tmp_path, capsys):
    """`verdict:` and `because:` are optional -- the panel defaults them
    (`considered`, and no `.because` paragraph), and the JSON schema declares
    no required key. A name-only option is a legitimate half-written entry,
    not a shape error."""
    root = _project(tmp_path, NAME_ONLY_OPTIONS)
    assert _check(root) == 0
    assert "0 errors" in capsys.readouterr().out


def test_the_valid_options_still_render_their_panel(tmp_path, capsys):
    """The render guard must not eat the good entries: the panel is the only
    place an option's name and verdict ever appear."""
    root = _project(tmp_path, MAPPING_OPTIONS)
    assert _build(root) == 0
    capsys.readouterr()
    html = (root / "_site" / "dec-x-001.html").read_text(encoding="utf-8")
    assert "Linear regulator" in html
    assert "Switching regulator" in html
    assert "verdict-rejected" in html


# ------------------------------------------------- the neighbouring checks, intact


def test_the_scalar_form_of_options_still_fires_its_own_error(tmp_path, capsys):
    """`options: Linear regulator or switching regulator` was already refused,
    at load, by `_reject_scalar_collection` -- and it stays that one error. The
    new branch deliberately skips a non-list value rather than reporting the
    same keystroke twice."""
    root = _project(tmp_path, SCALAR_OPTIONS)
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "field 'options' is a options field" in err
    assert "is not an option" not in err


def test_a_list_of_strings_checks_is_still_rejected(tmp_path, capsys):
    """`checks:` has refused a non-mapping entry by name for a while, and the
    new `options:` branch sits beside it rather than replacing it -- this is
    the pre-existing behaviour, pinned so a sweep at "collection fields" can't
    take it with it."""
    root = _project(tmp_path, STRING_CHECKS)
    assert _check(root) == 1
    err = capsys.readouterr().err
    assert "each checks: entry needs 'value' and 'against'" in err
    assert "DEC-X-001" in err


# ------------------------------------------------------------------------ build


def test_build_reports_the_bad_option_and_prints_no_traceback(tmp_path, capsys):
    """The crash itself. Before the fix `build` exited 1 with a Jinja2
    `UndefinedError: 'str object' has no attribute 'get'` traceback and no
    diagnostic; now it exits 1 with the same error `check` gives, and the site
    renders."""
    root = _project(tmp_path, STRING_OPTIONS)
    assert _build(root) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "is not an option" in captured.err
    assert "Traceback" not in output
    assert "UndefinedError" not in output
    assert "build completed with errors" in captured.err
