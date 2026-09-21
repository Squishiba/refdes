"""Loopback security for `refdes serve` (docs/design/browser-editor.md, Security).

Local-only is a boundary, not permission to skip checks:

* the server binds IPv4 `127.0.0.1` on an ephemeral port only;
* every request's `Host` must be exactly `127.0.0.1:<port>` or
  `localhost:<port>` (blocks DNS rebinding that reaches loopback);
* a per-launch token of 256 random bits gates reads *and* writes -- `/api/`
  takes it in the `X-Refdes-Token` header, the navigable surfaces (preview,
  editor shell) take it as a `SameSite=Strict` cookie set by the launch URL;
* every mutation must carry an `Origin` exactly matching the accepted Host;
* every response carries a restrictive CSP and no permissive CORS headers.

Nothing here touches the project.
"""

from __future__ import annotations

import hmac
import secrets

TOKEN_BYTES = 32  # 256 bits
TOKEN_HEADER = "X-Refdes-Token"
LOOPBACK_ADDRESS = "127.0.0.1"


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def tokens_equal(supplied: str | None, expected: str) -> bool:
    """Constant-time comparison; a missing token never matches."""
    if not supplied:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def cookie_name(port: int) -> str:
    # Cookies are not isolated by port, so two servers on localhost would
    # otherwise overwrite each other's session.
    return f"refdes_token_{port}"


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({f"{LOOPBACK_ADDRESS}:{port}", f"localhost:{port}"})


def allowed_origins(port: int) -> frozenset[str]:
    return frozenset({f"http://{LOOPBACK_ADDRESS}:{port}", f"http://localhost:{port}"})


def host_ok(host_header: str | None, port: int) -> bool:
    return host_header is not None and host_header in allowed_hosts(port)


def origin_ok(origin_header: str | None, host_header: str | None, port: int) -> bool:
    """A mutation's Origin must be one of the two accepted origins *and* agree
    with the Host it arrived on (`http://127.0.0.1:p` with `Host: localhost:p`
    is a mismatched pair and is rejected). Missing and `null` never pass."""
    if not origin_header or origin_header == "null":
        return False
    if origin_header not in allowed_origins(port):
        return False
    return origin_header == f"http://{host_header}"


# The editor: packaged same-origin scripts and styles only -- no inline script,
# no remote code, no plugins, no framing by other origins. `frame-src 'self'`
# lets it embed the preview.
EDITOR_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

# The rendered preview is the ordinary site: it carries inline styles and a
# JSON data block, so style-src allows 'unsafe-inline', but nothing remote may
# load and only the editor shell (same origin) may frame it.
PREVIEW_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "frame-ancestors 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


def security_headers(csp: str) -> dict[str, str]:
    return {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    }


def safe_relative_parts(url_path: str) -> list[str] | None:
    """Split a URL path (already unquoted, no query) into safe path segments,
    or None if any segment could escape or name something other than a plain
    file: empty/`.`/`..` segments, backslashes, drive or alternate-data-stream
    colons, NUL, and reserved Windows device names."""
    parts = [p for p in url_path.split("/") if p != ""]
    for part in parts:
        if part in (".", "..") or "\\" in part or ":" in part or "\x00" in part:
            return None
        stem = part.split(".", 1)[0].rstrip(" ").upper()
        if stem in _WINDOWS_RESERVED:
            return None
        if part != part.rstrip(" ."):
            return None
    return parts


_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
