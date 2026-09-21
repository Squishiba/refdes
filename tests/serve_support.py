"""Shared fixtures for the `refdes serve` browser-editor tests.

A small keyed project (requirements, decisions, tests, an append-only log,
two boards) plus a minimal HTTP client that speaks to a live `EditorApp`
the way the browser does -- token cookie for pages, token header for the API.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
from urllib.parse import urlsplit

from conftest import write_project_config

from refdes import cli as cli_mod

SERVE_SCHEMA = """\
site:
  title: "Serve test"
id:
  width: 3
boards:
  board-a:
    label: "Board A"
  board-b:
    label: "Board B"
link_types:
  satisfies: { inverse: satisfied_by, label: Satisfies }
  verifies: { inverse: verified_by, label: Verifies }
types:
  requirement:
    prefix: REQ
    coverable: true
    fields:
      text: { type: text, required: true }
      tags: { type: list }
      status: { type: enum, choices: [draft, approved] }
  decision:
    prefix: DEC
    fields:
      title: { type: text, required: true }
      status: { type: enum, choices: [proposed, accepted] }
    links:
      satisfies: [requirement]
  test:
    prefix: TST
    fields:
      title: { type: text, required: true }
    links:
      verifies: [requirement]
  log:
    prefix: LOG
    append_only: true
    fields:
      summary: { type: text, required: true }
"""

REQ_FILE = """\
# Requirements for the project. This comment must survive edits.
defaults: { type: requirement, board: board-a }
items:
  - id: REQ-001
    text: The rail shall supply 3.3 V.   # trailing comment
    tags: [power, rail]
    status: approved
  # a comment between items
  - id: REQ-002
    text: The board shall boot within 2 s.
    tags: [boot]
    board: board-b
  - id: REQ-003
    text: Nothing addresses this yet.
"""

DEC_FILE = """\
defaults: { type: decision, board: board-a }
items:
  - id: DEC-001
    title: Use the buck regulator.
    status: accepted
    satisfies: [REQ-001]
  - id: DEC-002
    title: Unsettled boot approach.
    status: proposed
    satisfies: [REQ-002]
"""

TST_FILE = """\
defaults: { type: test, board: board-a }
items:
  - id: TST-001
    title: Measure the rail.
    verifies: [REQ-001]
"""

LOG_FILE = """\
defaults: { type: log, board: board-a }
items:
  - id: LOG-001
    summary: Started the rail work.
"""

NOTES_MD = """\
---
id: REQ-010
type: requirement
board: board-a
text: A markdown requirement.
---

Body prose before a rule.

---

More body after a literal horizontal rule.
"""


def make_project(tmp_path, *, mint_keys: bool = True):
    """Write the fixture project under tmp_path and return its config path.
    With `mint_keys`, one ordinary writable check mints every key first, so the
    project starts in the state a real one is in."""
    write_project_config(tmp_path, SERVE_SCHEMA)
    items = tmp_path / "items"
    items.mkdir(exist_ok=True)
    for name, text in {
        "reqs.yaml": REQ_FILE,
        "decs.yaml": DEC_FILE,
        "tests.yaml": TST_FILE,
        "log.yaml": LOG_FILE,
    }.items():
        (items / name).write_text(text, encoding="utf-8")
    (items / "notes.md").write_text(NOTES_MD, encoding="utf-8")
    config = str(tmp_path / "refdes-project.yaml")
    if mint_keys:
        cli_mod.main(["-c", config, "check"])
    return config


class Client:
    """One HTTP conversation with a live EditorApp."""

    def __init__(self, app):
        self.app = app
        self.port = app.port

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        cookie: bool = False,
        token: bool = False,
        host: str | None = None,
    ):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            hdrs = {"Host": host or f"127.0.0.1:{self.port}"}
            if cookie:
                from refdes.serve import security

                hdrs["Cookie"] = f"{security.cookie_name(self.port)}={self.app.token}"
            if token:
                hdrs["X-Refdes-Token"] = self.app.token
            hdrs.update(headers or {})
            conn.request(method, path, body=body, headers=hdrs)
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
        finally:
            conn.close()

    def page(self, path: str, **kw):
        return self.request("GET", path, cookie=True, **kw)

    def api_get(self, path: str, **kw):
        status, _headers, data = self.request("GET", path, token=True, **kw)
        return status, _decode(data)

    def api_post(self, path: str, payload, *, origin: str | None = "default", **kw):
        hdrs = {"Content-Type": "application/json"}
        if origin == "default":
            origin = f"http://127.0.0.1:{self.port}"
        if origin is not None:
            hdrs["Origin"] = origin
        hdrs.update(kw.pop("headers", {}))
        status, _headers, data = self.request(
            "POST", path, token=True, body=json.dumps(payload).encode("utf-8"), headers=hdrs, **kw
        )
        return status, _decode(data)


def _decode(data: bytes):
    if not data:
        return None
    try:
        return json.loads(data)
    except ValueError:
        return data.decode("utf-8", "replace")  # a plain-text refusal


def snapshot_tree(root) -> dict[str, str]:
    """relpath -> sha256 of bytes for every file under root."""
    files = {}
    for dirpath, _dirs, names in os.walk(str(root)):
        for name in names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, str(root)).replace("\\", "/")
            with open(path, "rb") as fh:
                files[rel] = hashlib.sha256(fh.read()).hexdigest()
    return files


def path_of(url: str) -> str:
    parts = urlsplit(url)
    return parts.path + (("?" + parts.query) if parts.query else "")
