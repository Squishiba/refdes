/**
 * The extension's one client over `refdes serve`.
 *
 * Plain CommonJS on purpose, and deliberately free of any `vscode` import:
 * docs/design/editor-vscode-adapter.md §7.2 wants this module drivable without
 * an extension host, so everything in here is Node's own API.
 *
 * It owns exactly two things (§4's exhaustive list of what the extension may
 * own): the child process and the launch token. The token lives in this object
 * in the extension host's memory and nowhere else -- not in argv, not on disk,
 * not in a setting, not in a webview (§3.2 rows 1, 3, 4, 5).
 *
 * Two ways to become ready, and they converge on the same `{base, port, token}`:
 *   - `start()` spawns `<refdes.command> … serve --no-open` and reads the launch
 *     line off its stdout (§3.2 option 1);
 *   - `ServeClient.attach(parsed)` takes a launch URL somebody pasted (§3.2
 *     option 2).
 */

"use strict";

const cp = require("child_process");
const http = require("http");

/**
 * The literal `cmd_serve` prints before it serves anything
 * (`src/refdes/cli.py`: `print(f"refdes serve: {app.launch_url}", flush=True)`),
 * and the only thing this module parses out of the child's stdout.
 * tests/test_vscode_extension.py pins the two against each other.
 */
const LAUNCH_PREFIX = "refdes serve: ";

/** The header the server compares in constant time (`serve/security.py:TOKEN_HEADER`). */
const TOKEN_HEADER = "X-Refdes-Token";

/** How long a child may take to print its launch line before we call it dead. */
const BOOT_TIMEOUT_MS = 30000;

/** A single API read. The server never blocks long; a hang is a dead server. */
const REQUEST_TIMEOUT_MS = 10000;

/**
 * Keep a per-launch secret out of the output channel (§3.2's own warning).
 * Stops at `#` as well as at whitespace and `&`, so redacting a deep link leaves
 * its `#/items/<key>` fragment standing.
 */
function redact(text) {
  return String(text).replace(/([?&]token=)[^\s&#]+/g, "$1<redacted>");
}

/**
 * Parse a pasted launch URL: `http://127.0.0.1:<port>/?token=<token>`.
 *
 * `localhost` is accepted on the way in and rewritten to `127.0.0.1`, because
 * §3.2's rule is that the client always *talks* the printed IPv4 form: the
 * server binds IPv4 only and `localhost` may resolve to `::1`.
 *
 * @returns {{base: string, port: number, token: string, normalizedFromLocalhost: boolean} | null}
 */
function parseLaunchUrl(text) {
  let url;
  try {
    url = new URL(String(text).trim());
  } catch (err) {
    return null;
  }
  const token = url.searchParams.get("token");
  const port = Number(url.port);
  if (!token || !Number.isInteger(port) || port <= 0) return null;
  if (url.protocol !== "http:") return null;
  if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") return null;
  return {
    base: `http://127.0.0.1:${port}`,
    port,
    token,
    normalizedFromLocalhost: url.hostname === "localhost",
  };
}

/**
 * Parse the child's first stdout line. Returns null for any line that is not
 * the launch line -- the CLI prints two banner lines after it, and a project
 * that fails to load prints its own errors first.
 */
function parseLaunchLine(line) {
  const text = String(line == null ? "" : line).replace(/\r?\n$/, "");
  if (!text.startsWith(LAUNCH_PREFIX)) return null;
  return parseLaunchUrl(text.slice(LAUNCH_PREFIX.length));
}

class ServeClient {
  /**
   * @param {{command?: string, args?: string[], root?: string,
   *          onLog?: (line: string) => void,
   *          onExit?: (code: number|null, signal: string|null, stderr: string) => void}} [options]
   */
  constructor(options) {
    const opts = options || {};
    this.command = opts.command || "refdes";
    this.args = opts.args || [];
    this.root = opts.root || process.cwd();
    this.onLog = opts.onLog || function () {};
    this.onExit = opts.onExit || function () {};

    this.child = null;
    this.base = null;
    this.port = null;
    this.token = null;
    /** True when the handle came from a pasted URL rather than our own child. */
    this.attached = false;
    /** Set by kill() so an expected death is not reported as a crash. */
    this.stopping = false;
    this.error = null;

    this._boot = null;
    this._stderr = "";
  }

  /** Attach to a server somebody else started. No child, nothing to kill. */
  static attach(parsed, options) {
    const opts = options || {};
    const client = new ServeClient(opts);
    client.base = parsed.base;
    client.port = parsed.port;
    client.token = parsed.token;
    client.attached = true;
    return client;
  }

  get ready() {
    return Boolean(this.base && this.token);
  }

  /**
   * Spawn `… serve --no-open` and wait for the launch line.
   *
   * Resolves with `this` once ready, or `null` on any failure -- never rejects,
   * because every caller is a hover or a CodeLens click and neither has an
   * error UI of its own. Failures are reported through `onLog` and `this.error`
   * instead: a quiet failure is the bug class (§3.2).
   */
  start() {
    if (this._boot) return this._boot;
    this._boot = new Promise((resolve) => {
      const argv = this.args.concat(["serve", "--no-open"]);
      // No token in argv, ever (§3.2 row 4 and §7.1's argv test) -- this log
      // line is what a reader of the output channel sees as the command.
      this.onLog("$ " + [this.command].concat(argv).join(" "));

      let child;
      try {
        child = cp.spawn(this.command, argv, {
          cwd: this.root,
          shell: process.platform === "win32",
          env: Object.assign({}, process.env, { PYTHONIOENCODING: "utf-8" }),
        });
      } catch (err) {
        this.error = "could not start the refdes command: " + (err && err.message ? err.message : err);
        this.onLog(this.error);
        resolve(null);
        return;
      }
      this.child = child;

      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(result);
      };
      const timer = setTimeout(() => {
        this.error = `refdes serve did not print its launch line within ${BOOT_TIMEOUT_MS / 1000}s`;
        this.onLog(this.error);
        this.kill();
        finish(null);
      }, BOOT_TIMEOUT_MS);
      if (timer.unref) timer.unref();

      let buffer = "";
      child.stdout.setEncoding("utf8");
      child.stdout.on("data", (chunk) => {
        buffer += chunk;
        let nl = buffer.indexOf("\n");
        while (nl !== -1) {
          const line = buffer.slice(0, nl);
          buffer = buffer.slice(nl + 1);
          const parsed = parseLaunchLine(line);
          if (parsed) {
            this.base = parsed.base;
            this.port = parsed.port;
            this.token = parsed.token;
            this.error = null;
            // The port is never cached: it is ephemeral and changes every
            // launch, so this parsed line is the only handle there is (§3.2).
            this.onLog(`ready on ${parsed.base} (launch token held in memory only)`);
            finish(this);
          } else if (line.trim()) {
            this.onLog(redact(line));
          }
          nl = buffer.indexOf("\n");
        }
      });

      child.stderr.setEncoding("utf8");
      child.stderr.on("data", (chunk) => {
        this._stderr += chunk;
        const trimmed = String(chunk).replace(/\s+$/, "");
        if (trimmed) this.onLog(redact(trimmed));
      });

      child.on("error", (err) => {
        this.error = "could not start the refdes command: " + (err && err.message ? err.message : err);
        this.onLog(this.error);
        finish(null);
      });

      child.on("close", (code, signal) => {
        this.child = null;
        if (!settled) {
          this.error = `refdes serve exited (code ${code}) before it printed its launch line`;
          finish(null);
        }
        if (!this.stopping) this.onExit(code, signal, this._stderr);
      });
    });
    return this._boot;
  }

  /**
   * One authenticated read. Resolves `{status, body}` on any HTTP response, or
   * `{error}` when there was no response at all. Never rejects.
   */
  request(pathname) {
    return new Promise((resolve) => {
      if (!this.ready) {
        resolve({ error: "refdes serve is not running" });
        return;
      }
      const req = http.request(
        {
          // Always the printed IPv4 form, never `localhost` (§3.2). Node derives
          // `Host: 127.0.0.1:<port>` from these, which is what `host_ok` checks.
          host: "127.0.0.1",
          port: this.port,
          method: "GET",
          path: pathname,
          headers: {
            Accept: "application/json",
            [TOKEN_HEADER]: this.token,
          },
        },
        (res) => {
          let text = "";
          res.setEncoding("utf8");
          res.on("data", (chunk) => (text += chunk));
          res.on("end", () => {
            if (res.statusCode !== 200) {
              resolve({ status: res.statusCode, body: text });
              return;
            }
            try {
              resolve({ status: res.statusCode, body: JSON.parse(text) });
            } catch (err) {
              resolve({ error: `could not parse the response from ${pathname}: ${err}` });
            }
          });
        }
      );
      req.on("error", (err) => resolve({ error: err && err.message ? err.message : String(err) }));
      req.setTimeout(REQUEST_TIMEOUT_MS, () => req.destroy(new Error("timed out")));
      req.end();
    });
  }

  /** `GET /api/revision` -- `{revision, serial, stale, load_error, git}`. */
  revision() {
    return this.request("/api/revision");
  }

  /** `GET /api/item/<ref>` -- the whole item view. */
  item(ref) {
    return this.request("/api/item/" + encodeURIComponent(ref));
  }

  /**
   * The editor deep link for one item key -- the same `/edit/#/items/<key>` the
   * server injects into its own preview toolbar (`serve/server.py:_decorate`).
   *
   * The token rides in the query on purpose: `/edit/` is a navigable surface
   * that authenticates with an `HttpOnly` `SameSite=Strict` cookie only the
   * launch URL sets, and an external browser has no such cookie yet. The
   * server's `_start_session` answers a token-carrying GET by setting that
   * cookie and 302-ing to the same path with the token stripped, so the address
   * bar the author ends up looking at carries nothing (§3.3, last row).
   */
  deepLink(key) {
    if (!this.ready || !key) return null;
    return `${this.base}/edit/?${TOKEN_QUERY(this.token)}#/items/${encodeURIComponent(key)}`;
  }

  /** The same link with its token redacted -- what goes into the output channel. */
  deepLinkForLog(key) {
    return redact(this.deepLink(key) || "");
  }

  /**
   * Stop the child. An attached client has no child, so this only clears the
   * handle. Safe to call twice.
   */
  kill() {
    this.stopping = true;
    const child = this.child;
    this.child = null;
    if (!child) return;
    if (process.platform === "win32") {
      // Spawned through a shell, so killing the child would orphan the Python
      // process still holding the port. /T takes the tree.
      cp.spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"]);
      return;
    }
    child.kill("SIGTERM");
  }
}

function TOKEN_QUERY(token) {
  return `token=${encodeURIComponent(token)}`;
}

module.exports = {
  ServeClient,
  parseLaunchLine,
  parseLaunchUrl,
  redact,
  LAUNCH_PREFIX,
  TOKEN_HEADER,
};
