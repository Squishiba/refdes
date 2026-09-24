"""Static checks on the served editor (docs/design/browser-editor.md, Security
and "No Node build step"): the shell is packaged plain ES modules under a CSP of
`script-src 'self'`, so anything inline is both a CSP violation and a hole.

No browser here, so these are text checks over the files the server serves:
no inline script or inline event handler anywhere in the shell, no `eval` or
`new Function`, and every module the shell loads (directly or by import) exists.
"""

from __future__ import annotations

import os
import re

import pytest

STATIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "refdes", "serve", "static"
)

INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*[:=]""", re.IGNORECASE)
DYNAMIC_CODE = re.compile(r"\b(eval|new\s+Function|setTimeout\s*\(\s*['\"]|setInterval\s*\(\s*['\"])")
JS_IMPORT = re.compile(r"""from\s+['"]([^'"]+\.js)['"]""")
HTML_ASSET = re.compile(r"""(?:src|href)\s*=\s*["']/edit/static/([^"']+)["']""")
SCRIPT_WITHOUT_SRC = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)


def js_files():
    return sorted(n for n in os.listdir(STATIC) if n.endswith(".js"))


@pytest.mark.parametrize("name", js_files())
def test_no_inline_handlers_or_dynamic_code_in_served_js(name):
    with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
        text = fh.read()
    assert not INLINE_HANDLER.search(text), f"{name}: an inline event handler is a CSP violation"
    assert not DYNAMIC_CODE.search(text), f"{name}: no eval/new Function in the editor"
    assert "javascript:" not in text


def test_the_shell_has_no_inline_script_or_handler():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert not SCRIPT_WITHOUT_SRC.search(html), "index.html may only load scripts by src"
    assert not INLINE_HANDLER.search(html)
    assert "javascript:" not in html


def test_every_asset_the_shell_loads_exists():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    named = set(HTML_ASSET.findall(html))
    assert named, "index.html should reference its own static assets"
    for name in named:
        assert os.path.isfile(os.path.join(STATIC, name)), f"index.html loads a missing file: {name}"


def test_every_module_import_resolves():
    """The import graph, walked from what index.html loads: a typo'd module name
    is a blank page in the browser and nothing else would notice."""
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        entry = {n for n in HTML_ASSET.findall(fh.read()) if n.endswith(".js")}
    # preview.js is an entry too: injected into preview pages by the server's
    # decoration rather than referenced by index.html.
    entry.add("preview.js")
    assert entry
    seen = set()
    while entry:
        name = entry.pop()
        if name in seen:
            continue
        seen.add(name)
        path = os.path.join(STATIC, name)
        assert os.path.isfile(path), f"the editor imports a module that does not exist: {name}"
        with open(path, encoding="utf-8") as fh:
            for target in JS_IMPORT.findall(fh.read()):
                if target.startswith("./"):
                    entry.add(target[2:])
                else:
                    entry.add(target)


def test_served_js_parses_as_es2020_modules():
    """No Node here, so the cheapest real check: every module's braces, parens
    and brackets balance and no `const`/`let` is declared twice in the same
    top-level scope -- the class of mistake that turns a module into a blank
    page with one console line."""
    for name in js_files():
        with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
            text = fh.read()
        depth = {"(": ")", "[": "]", "{": "}"}
        stack = []
        in_string = None
        escaped = False
        for ch in text:
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_string:
                    in_string = None
                continue
            if ch in "'\"`":
                in_string = ch
            elif ch in depth:
                stack.append(depth[ch])
            elif stack and ch in ")]}":
                assert stack.pop() == ch, f"{name}: unbalanced {ch}"
        assert not stack, f"{name}: unclosed {stack}"
        top = re.findall(r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", text, re.MULTILINE)
        assert len(top) == len(set(top)), f"{name}: duplicate top-level declaration in {name}"


# ------------------------------------------------------------ link pickers


def test_the_link_picker_is_wired_into_the_editor():
    """Slice 2's UI has to actually reach the page: links.js must exist, be
    imported by editor.js (the import-graph walk above proves it resolves),
    and the save path must know the two link ops. A picker nothing imports
    is a picker nobody sees."""
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "from './links.js'" in editor
    assert "createLinksSection" in editor
    assert "'add_link'" in editor and "'remove_link'" in editor
    assert os.path.isfile(os.path.join(STATIC, "links.js"))


def test_the_link_draft_rides_the_one_draft_mechanism():
    """Link adds/removes are draft ops in the same draft as fields and the
    body -- the design forbids a second draft mechanism."""
    with open(os.path.join(STATIC, "drafts.js"), encoding="utf-8") as fh:
        drafts = fh.read()
    assert "links: { add: {}, remove: {} }" in drafts
    assert "draftLinkAdd" in drafts and "draftLinkRemove" in drafts
    # and the picker sends handles, never a composite it invented itself
    with open(os.path.join(STATIC, "links.js"), encoding="utf-8") as fh:
        picker = fh.read()
    assert "draftLinkAdd(handle, verb, row.handle || row.id)" in picker
    # the picker never builds a DISPLAY-ID@key composite itself: the service
    # owns that spelling, so the client must not even look like it does
    assert "@${" not in picker


# ------------------------------------------------------------- creation UI


def test_the_new_item_form_is_wired_into_the_shell():
    """Slice 3's UI has to actually reach the page: create.js must exist, be
    imported by app.js, be routed at #/new, and be offered by the nav. A form
    nothing routes to is a form nobody sees."""
    assert os.path.isfile(os.path.join(STATIC, "create.js"))
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as fh:
        app = fh.read()
    assert "from './create.js'" in app
    assert "#/new" in app
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert 'href="#/new"' in html


def test_the_create_form_asks_the_server_and_never_mints():
    """The id the form shows is the server's pure plan (preview reserves
    nothing), submission goes to the one create endpoint, and the client never
    builds a composite or a key -- the same posture as the link picker."""
    with open(os.path.join(STATIC, "create.js"), encoding="utf-8") as fh:
        create = fh.read()
    assert "/api/create/schema" in create
    assert "/api/create/preview" in create
    assert "/api/items/create" in create
    assert "@${" not in create


def test_the_field_controls_are_shared_not_duplicated():
    """editor.js and create.js must build field controls from the same code:
    the design says the create form reuses the editor's controls, and a second
    copy is exactly the drift the reuse was meant to prevent."""
    assert os.path.isfile(os.path.join(STATIC, "controls.js"))
    for name in ("editor.js", "create.js"):
        with open(os.path.join(STATIC, name), encoding="utf-8") as fh:
            text = fh.read()
        assert "from './controls.js'" in text, f"{name} must use the shared controls"
        assert "fieldControlNode" in text
    with open(os.path.join(STATIC, "controls.js"), encoding="utf-8") as fh:
        controls = fh.read()
    assert "export function fieldControlNode" in controls


# ------------------------------------------------- preview auto-reload (W1)


def test_the_preview_page_carries_a_self_reload_probe():
    """Thread workbench W1: a served preview page must ship the polling
    probe, and the probe must follow the house pattern -- poll
    /api/revision and reload when the serial moves, importing the shared
    api.js rather than inventing a second transport or a push channel."""
    assert os.path.isfile(os.path.join(STATIC, "preview.js"))
    with open(os.path.join(STATIC, "preview.js"), encoding="utf-8") as fh:
        preview = fh.read()
    assert "from './api.js'" in preview
    assert "/api/revision" in preview
    assert "location.reload()" in preview
    assert "refdes-serial" in preview


def test_the_server_injects_the_probe_into_preview_responses():
    """The probe is decoration: the server injects the serial it rendered
    and the probe script into the HTTP response, like the toolbar."""
    server = os.path.join(
        os.path.dirname(STATIC), "server.py"
    )
    with open(server, encoding="utf-8") as fh:
        text = fh.read()
    assert 'name="refdes-serial"' in text
    assert "/edit/static/preview.js" in text


def test_the_item_view_offers_a_link_to_its_preview_page():
    """Thread workbench W1: from /edit/ the author can open the item's own
    /preview/ page -- the link is built from the server-provided `page`,
    never a slug the client guesses."""
    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "Open preview" in item
    assert "/preview/${encodeURIComponent(item.page)}" in item
    assert "'_blank'" in item


# ------------------------------------------------- rebuild focus preservation


def test_the_rebuild_updates_controls_instead_of_replacing_them():
    """The focus-loss fix (in-prog-logs/browser-editor-edit-ui.md, "Focus is
    lost"): a revision-triggered re-render must carry controls over by field
    identity instead of tearing them down. Static checks: the pure update
    helpers exist in update.js (focus and selection captured and restored),
    item.js wires them around the re-render, and the controls carry a stable
    data-edit-key so identity survives the rebuild."""
    assert os.path.isfile(os.path.join(STATIC, "update.js"))
    with open(os.path.join(STATIC, "update.js"), encoding="utf-8") as fh:
        update = fh.read()
    for fn in (
        "export function captureFocus",
        "export function restoreFocus",
        "export function collectControls",
    ):
        assert fn in update, f"update.js is missing {fn}"
    assert "data-edit-key" in update
    # the caret travels too, not just focus
    assert "selectionStart" in update and "setSelectionRange" in update

    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "from './update.js'" in item
    assert "captureFocus(container)" in item
    # focus is captured before the container is cleared and restored after
    # the whole view (including the preview section) is rebuilt
    assert item.index("captureFocus(container)") < item.index("restoreFocus(container, focus)")
    assert item.index("restoreFocus(container, focus)") > item.rindex("container.textContent = ''")
    # controls are carried into the new render by field identity
    assert "controls.get(`field:${name}`)" in item
    assert "editor.bodyControl(item.body, controls.get('body'))" in item


def test_a_carried_over_control_is_rebound_not_double_bound():
    """Reusing a control node across a re-render is only correct if the old
    change handler is detached first (otherwise one keystroke writes the
    draft twice through two closures) and the value is written only when it
    differs (otherwise a rebuild fights the author's typing)."""
    with open(os.path.join(STATIC, "controls.js"), encoding="utf-8") as fh:
        controls = fh.read()
    assert "export function applyControl" in controls
    assert "removeEventListener" in controls
    assert "if (node.value !== shown)" in controls
    with open(os.path.join(STATIC, "editor.js"), encoding="utf-8") as fh:
        editor = fh.read()
    assert "from './controls.js'" in editor and "applyControl" in editor
    # the body textarea follows the same in-place rule
    assert "if (area.value !== shown)" in editor
    assert "area.removeEventListener" in editor


def test_a_sealed_log_offers_the_amend_flow():
    """"Amend this sealed log" links to a pre-filled create form: the
    correction is a new entry, so the affordance must exist on the sealed
    item and must route to creation, not pretend to edit the sealed entry."""
    with open(os.path.join(STATIC, "item.js"), encoding="utf-8") as fh:
        item = fh.read()
    assert "Amend this sealed log" in item
    assert "#/new?type=" in item
    assert "amends=" in item
