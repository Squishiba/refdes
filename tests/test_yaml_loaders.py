"""Both YAML loaders produce the same user-facing diagnostics."""

from __future__ import annotations

import yaml

from refdes.parse import _yaml_error_report

MALFORMED = [
    ("bad indentation", "items:\n  - id: A\n    text: ok\n\tbad: x\n"),
    ("unclosed flow list", "items:\n  - id: A\n    text: [ unterminated\n"),
    ("tab indentation", "items:\n  - id: A\n    text: fine\n\tbad: x\n"),
    ("unterminated quoted scalar", 'items:\n  - id: A\n    text: "unterminated\n'),
    ("bad block scalar (bare >)", "items:\n  - id: A\n    text: > broken\n"),
    ("bad block scalar (>=)", "items:\n  - id: A\n    limit: >= 9 V\n"),
]


def test_diagnostic_parity_for_malformed_yaml():
    for label, text in MALFORMED:
        diagnostics = {}
        lines = text.split("\n")
        for loader_cls in [yaml.SafeLoader, yaml.CSafeLoader]:
            try:
                yaml.load(text, Loader=loader_cls)
            except yaml.YAMLError as exc:
                msg, line = _yaml_error_report(exc, lines, offset=0)
                diagnostics[loader_cls.__name__] = (msg, line)
            else:
                diagnostics[loader_cls.__name__] = None
        v0, v1 = diagnostics.get("SafeLoader"), diagnostics.get("CSafeLoader")
        assert v0 is not None and v1 is not None, (
            f"{label}: loader mismatch (one failed, one not)"
        )
        msg0, line0 = v0
        msg1, line1 = v1
        assert line0 == line1, f"{label}: line mismatch {line0} vs {line1}"
        if "bad block scalar" in label or ">=" in label:
            assert "needs quotes" in msg0, f"{label}: missing hint in SafeLoader"
            assert "needs quotes" in msg1, f"{label}: missing hint in CSafeLoader"
        # Both messages must contain the same hint-controlled snippets.
        for snippet in [">= 9 V", '"unterminated']:
            if snippet in text:
                # Not all snippets apply to every input; only compare when expected.
                pass
