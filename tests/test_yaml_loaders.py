"""YAML diagnostics must be byte-identical: C loader uses pure-Python fallback on error."""

from __future__ import annotations

import yaml

from refdes.parse import _PurePythonLineLoader, _yaml_error_report, yaml_safe_load

MALFORMED = [
    ("bad indentation", "items:\n  - id: A\n    text: ok\n\tbad: x\n"),
    ("unclosed flow list", "items:\n  - id: A\n    text: [ unterminated\n"),
    ("tab indentation", "items:\n  - id: A\n    text: fine\n\tbad: x\n"),
    ("unterminated quoted scalar", 'items:\n  - id: A\n    text: "unterminated\n'),
    ("bad block scalar (>=)", "items:\n  - id: A\n    limit: >= 9 V\n"),
    ("double mapping key", "items:\n  - id: A\n    text: a: b: c\n"),
]

def test_diagnostic_parity_for_malformed_yaml():
    for label, text in MALFORMED:
        lines = text.split("\n")
        # Direct pure-Python load (always pure-python exception)
        try:
            yaml.load(text, Loader=_PurePythonLineLoader)
        except yaml.YAMLError as exc_py:
            msg_py, line_py = _yaml_error_report(exc_py, lines, offset=0)
        else:
            msg_py = line_py = None  # Should never succeed for malformed input

        # Our shared helper (retries pure-Python on C error)
        try:
            yaml_safe_load(text)
        except yaml.YAMLError as exc_refdes:
            msg_refdes, line_refdes = _yaml_error_report(exc_refdes, lines, offset=0)
        else:
            msg_refdes = line_refdes = None

        assert msg_refdes is not None, f"{label}: refdes helper did not raise"
        assert msg_py is not None, f"{label}: pure-python loader did not raise"
        assert msg_refdes == msg_py, (
            f"{label}: message mismatch\nrefdes: {msg_refdes!r}\npure: {msg_py!r}"
        )
        assert line_refdes == line_py, f"{label}: line mismatch {line_refdes} vs {line_py}"
        # The caret excerpt must be present in the message when the pure-Python loader includes it.
        # Since our retry reports the pure-Python exception, it should include the same excerpt.
        assert msg_refdes.startswith(str(msg_py)) or msg_refdes == msg_py
