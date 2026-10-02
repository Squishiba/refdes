"""One markdown-it parser per build, not one per item.

Constructing a `MarkdownIt` costs about as much as parsing a body with it, so
when `_image_inputs_hash_value` built one per item it dominated the model build:
1602 constructions for a 1600-item corpus, measured at ~37% of `build.build()`
time on the corpus in `.scratch/mkperfproj.py` (the write-up is
`in-prog-logs/perf-cache-markdown-parser.md`, PR #78). Nothing else in the suite
can see this -- the rendered site is byte-identical either way, which is the
point of the change -- so what is pinned here is the construction count and the
identity of the shared instance.

Sabotage: replace the `_markdown_parser()` call in `_image_inputs_hash_value`
with a literal `MarkdownIt("gfm-like", {"html": False, "linkify": False})` and
the first test below reports 12 constructions for 12 items.
"""

from __future__ import annotations

import threading

from conftest import write_project_config

from refdes import build as build_mod
from refdes import parse
from refdes.schema import load_project

CONFIG = (
    "site: { title: T, out: _site }\n"
    "types:\n"
    "  decision: { prefix: DEC, fields: {} }\n"
)

ITEM_COUNT = 12
PNG = b"\x89PNG\r\n\x1a\n parser-cache bytes"


def _write_project(tmp_path) -> None:
    """A multi-item project whose bodies exercise the paths the shared parser
    is about: a GFM table, an image that resolves, a URL-scheme image (which
    contributes nothing), and an image inside a code fence (same)."""
    write_project_config(tmp_path, CONFIG)
    items = tmp_path / "items"
    items.mkdir()
    (items / "img.png").write_bytes(PNG)
    for n in range(1, ITEM_COUNT + 1):
        body = (
            f"Decision {n}: the rail shall hold.\n\n"
            "| corner | Vin | ripple |\n| --- | --- | --- |\n| hot | 12 V | 30 mV |\n\n"
            f"![curve](img.png)\n\n"
            "![upstream](https://example.com/datasheet.png)\n\n"
            "```text\n![fenced](img.png)\n```\n"
        )
        (items / f"dec-{n:03d}.md").write_text(
            f"---\nid: DEC-{n:03d}\ntype: decision\n---\n\n{body}", encoding="utf-8"
        )


def _load(tmp_path):
    _write_project(tmp_path)
    project = load_project(config_path=str(tmp_path / "refdes-project.yaml"))
    parse.load_items(project)
    return project


def _count_constructions(monkeypatch) -> list:
    """Every MarkdownIt this test causes, in order. Patching the name in
    `build` is what the factory itself looks up, so nothing escapes it."""
    made: list = []
    real = build_mod.MarkdownIt

    class CountingMarkdownIt(real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(build_mod, "MarkdownIt", CountingMarkdownIt)
    return made


def _cold_cache(monkeypatch) -> None:
    """Force the next construction to happen inside the test.

    The cache is thread-local and outlives a test, so with a warm cache every
    count below is 0 -- which would satisfy any "not too many parsers"
    assertion vacuously, including the sabotaged one.
    """
    monkeypatch.setattr(build_mod._MD_LOCAL, "markdown_it", None, raising=False)


def test_a_build_constructs_one_markdown_parser_not_one_per_item(tmp_path, monkeypatch):
    made = _count_constructions(monkeypatch)
    _cold_cache(monkeypatch)

    project = _load(tmp_path)
    build_mod.build(project)

    assert not project.errors, project.errors
    assert len(project.local_items) == ITEM_COUNT
    assert len(made) == 1, (
        f"one build over {ITEM_COUNT} items constructed {len(made)} markdown-it "
        "parsers; every caller must go through build._markdown_parser()"
    )


def test_the_hash_pass_and_the_render_pass_share_one_instance(tmp_path, monkeypatch):
    """Not just "few parsers": literally the same object. The hash pass and the
    render pass must agree on which images a body counts, which is the property
    `_markdown_parser`'s docstring calls load-bearing."""
    made = _count_constructions(monkeypatch)
    _cold_cache(monkeypatch)

    project = _load(tmp_path)
    build_mod.compute_hashes(project)
    assert len(made) == 1, made
    shared = build_mod._markdown_parser()

    build_mod.render_bodies(project)
    build_mod.render_pages(project)
    assert len(made) == 1, (
        f"the render pass built its own parser instead of reusing {shared!r}"
    )
    assert build_mod._markdown_parser() is shared


def test_a_build_does_not_reconfigure_the_shared_parser(tmp_path):
    """Sharing one mutable instance is only safe because nothing rewrites it.
    `configure`/`enable`/`disable`/`use` all would, and a build that did would
    corrupt every later item in the same thread."""
    md = build_mod._markdown_parser()
    before = (dict(md.options), _rule_chains(md))

    project = _load(tmp_path)
    build_mod.build(project)

    assert md.options == before[0]
    assert _rule_chains(md) == before[1]
    assert md.options["html"] is False, "raw markup must stay disabled"
    assert md.options["linkify"] is False


def _rule_chains(md):
    return {
        name: [(rule.name, rule.enabled) for rule in chain.ruler.__rules__]
        for name, chain in (
            ("core", md.core),
            ("block", md.block),
            ("inline", md.inline),
        )
    }


def test_each_thread_gets_its_own_parser():
    """`refdes serve` builds on more than one thread, so the shared instance is
    shared per thread rather than globally (see the comment on `_MD_LOCAL`)."""
    seen: dict[str, object] = {}

    def grab(name: str) -> None:
        seen[name] = build_mod._markdown_parser()

    threads = [
        threading.Thread(target=grab, args=(name,)) for name in ("a", "b", "c")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(parser) for parser in seen.values()}) == 3, seen
    assert build_mod._markdown_parser() is build_mod._markdown_parser()


def test_the_shared_parser_renders_what_the_per_item_one_did(tmp_path):
    """The configuration is load-bearing, not an artifact of the cache: tables
    and strikethrough from `gfm-like` must render, raw HTML and autolinked bare
    URLs must not. Repeated here through the shared instance so a change to the
    factory's literal has to fail this too."""
    project = _load(tmp_path)
    build_mod.build(project)

    html = project.item_by_id("DEC-001").body_html
    assert "<table>" in html and "<s>" not in html
    assert "https://example.com/datasheet.png" in html
    # the resolved image and the URL-scheme one; the fenced one stays literal text
    assert html.count("<img") == 2, html
    assert "![fenced](img.png)" in html
