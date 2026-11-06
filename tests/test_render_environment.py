"""The Jinja Environment is built once per process, not per render (audit §3.3).

Every `render_site` call used to construct a fresh `Environment`, and Jinja
compiles every template the first time a given Environment loads it: 12
compiles, ~150 ms, per build and per `serve` preview rebuild. Reusing one
Environment per (template dir, compile options) keeps the compiled templates
for the life of the process; the keying is what makes that safe for a caller
that renders against a different template tree.
"""

from __future__ import annotations

import shutil

import jinja2
from conftest import write_project_config
from helpers import _build_at

from refdes import render as render_mod

CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n  decision: { prefix: DEC, fields: {} }\n"
)


def _pages_project(tmp_path):
    write_project_config(tmp_path, CONFIG)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "a.md").write_text("# A\n\nText.\n", encoding="utf-8")
    return _build_at(tmp_path)


def _counting_compiles(monkeypatch):
    counter = {"n": 0}
    real = jinja2.Environment._compile

    def counting(self, source, filename):
        counter["n"] += 1
        return real(self, source, filename)

    monkeypatch.setattr(jinja2.Environment, "_compile", counting)
    return counter


def test_render_site_reuses_one_environment(tmp_path, monkeypatch):
    """A warm process pays the 12 template compiles once, not per render."""
    project = _pages_project(tmp_path)
    counter = _counting_compiles(monkeypatch)

    render_mod._ENVIRONMENTS.clear()
    render_mod.render_site(project)
    first = counter["n"]
    counter["n"] = 0
    render_mod.render_site(project)

    assert first >= 2, first  # the pages this project renders, compiled
    assert counter["n"] == 0, counter["n"]


def test_environment_is_keyed_by_template_dir(tmp_path, monkeypatch):
    """A second template tree gets its own Environment, not the cached one."""
    other = tmp_path / "templates"
    shutil.copytree(render_mod.TEMPLATE_DIR, other)

    render_mod._ENVIRONMENTS.clear()
    env_a = render_mod._environment()
    monkeypatch.setattr(render_mod, "TEMPLATE_DIR", str(other))
    env_b = render_mod._environment()

    assert env_a is not env_b
    assert env_a.get_template("page.html.j2") is not env_b.get_template(
        "page.html.j2"
    )
    assert len(render_mod._ENVIRONMENTS) == 2


def test_template_edit_is_visible_to_the_next_render(tmp_path, monkeypatch):
    """The shared Environment must stay as fresh as the per-call one was:
    a template edited on disk recompiles on the next render."""
    project = _pages_project(tmp_path)
    other = tmp_path / "templates"
    shutil.copytree(render_mod.TEMPLATE_DIR, other)
    monkeypatch.setattr(render_mod, "TEMPLATE_DIR", str(other))

    html_a = render_mod.render_site(project)
    with open(f"{html_a}/a.html", encoding="utf-8") as fh:
        page = fh.read()

    sheet = other / "assets" / "style.css"
    sheet.write_text(
        sheet.read_text(encoding="utf-8") + "\n/* audit-a marker */\n",
        encoding="utf-8",
    )
    base = other / "base.html.j2"
    base.write_text(
        base.read_text(encoding="utf-8").replace("</head>", "<!-- audit-a -->\n</head>", 1),
        encoding="utf-8",
    )
    html_b = render_mod.render_site(project)
    with open(f"{html_b}/a.html", encoding="utf-8") as fh:
        page_b = fh.read()

    assert "audit-a" not in page
    assert "audit-a" in page_b
