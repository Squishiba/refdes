"""`refdes serve`: a loopback-only local server for the browser editor.

docs/design/browser-editor.md is the design of record. Two deliberately
separate surfaces share one process and one loaded project:

* `/preview/` -- the ordinary rendered site, rebuilt into an OS temp directory
  (never `_site/`), with a server-only "Edit" toolbar injected into the HTTP
  response (never written into the rendered files);
* `/edit/` and `/api/` -- the editor application and its JSON API.

Python stays the only implementation of the schema, parser, validator, ids,
keys, links and seals; the browser is a thin client over plain ES modules
shipped in `static/`. Modules:

* `security` -- launch token, Host/Origin checks, response headers, CSP;
* `state`    -- project inputs, content revision, polling, git advisory;
* `preview`  -- the temp-dir rendered preview and its cleanup;
* `server`   -- the stdlib HTTP server and routing.
"""
