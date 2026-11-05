"""docs context ask (DC-3): one fixed prompt per reference card, to a local model.

The model is a READING AID and nothing else: it explains the cited code or
command in plain words, points out what a reader could misread, and says
whether the sentence matches the server-known facts. It never drafts,
rewrites, or suggests documentation prose -- ``build_messages`` is the one
place the prompt text lives, and its system message states that rule.

Only the server builds prompts: the user message carries facts the server
resolved itself (the block's text, the ref, the card's cited lines, help
text, anchor/heading), never anything the browser sends. The transport is
urllib only, over a base_url that must be loopback -- the host is checked
before any socket is opened, so a non-loopback url can never leak a prompt
to the network.

Stdlib only. Not a shipped package: imported by ``server.py``.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
from urllib.request import Request, urlopen

DEFAULT_LLM_URL = "http://127.0.0.1:8080/v1"

# The model answers with these words and nothing else; the three questions
# are fixed instructions, chosen by name, never by browser-supplied text.
SYSTEM_PROMPT = (
    "You are a reading aid for a human reviewing a documentation page. "
    "You never write, rewrite, or suggest documentation prose: you explain "
    "what the cited code ref, file ref, command, or link points at, point "
    "out what a reader could misread, and say whether the sentence matches "
    "the facts you were given. Quote facts back by line number (for code) "
    "or by the exact command text (for commands); never invent a fact that "
    "is not in the given material. If the facts are not enough information "
    "to answer, say so plainly instead of guessing. Answer in at most 150 "
    "words."
)

_QUESTION_INSTRUCTIONS = {
    "explain": (
        "Question: explain this reference in plain words -- what the cited "
        "line, command, or link actually is, using only the facts given "
        "below. Cite the line number (code) or the exact command text."
    ),
    "misread": (
        "Question: what could a reader misread about this sentence and its "
        "reference? Name the specific reading the quoted facts make wrong, "
        "citing the line number (code) or the exact command text."
    ),
    "match": (
        "Question: does the sentence say what the cited facts show? Answer "
        "match, or name the mismatch, citing the line number (code) or the "
        "exact command text."
    ),
}

_LOOPBACK_NAME = "localhost"


class LlmError(Exception):
    """Kind of transport failure: unreachable | timeout | bad_response."""

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


def require_loopback(base_url: str) -> str:
    """Return base_url if it is a plain http url to the loopback interface;
    raise ValueError before any socket is opened otherwise.

    Only the literal name ``localhost`` and IP literals that
    ``ipaddress.ip_address`` reports as loopback are accepted -- a name
    like ``127.evil.com`` resolves wherever its owner points it, so
    prefix-matching a ``127.`` string is not a loopback rule. The host
    is taken from the url's authority, so a userinfo trick
    (``http://127.0.0.1@evil.com/``) reads as ``evil.com`` and is
    refused. Scheme must be ``http``: this is a plaintext local
    endpoint, not a general url fetcher."""
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme != "http":
        raise ValueError(f"llm url must be a plain http url: {base_url!r}")
    host = parts.hostname
    if host is None:
        raise ValueError(f"llm url has no host: {base_url!r}")
    host = host.lower()
    if host == _LOOPBACK_NAME:
        return base_url
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(
            f"llm url host must be the literal localhost or a loopback ip "
            f"literal (127.0.0.0/8, ::1), not a name: {base_url!r}"
        ) from None
    if address.is_loopback:
        return base_url
    raise ValueError(
        f"llm url must be loopback (127.0.0.0/8, ::1, localhost): {base_url!r}"
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect is a second url. The prompt carries the page's code and
    help text; it must never be resent somewhere the guard did not vet,
    so redirects are refused rather than followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LlmError(
            "bad_response",
            f"the llm sent a redirect ({code}) to {newurl!r}: prompts are never resent to a second url",
        )


_DEFAULT_URLOPEN = urllib.request.urlopen
_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _urlopen(request, timeout: float):
    # Tests stub the request by patching this module's `urlopen`; the real
    # path (the unpatched default) goes through an opener that refuses
    # redirects. A stubbed transport is used as given.
    send = _OPENER.open if urlopen is _DEFAULT_URLOPEN else urlopen
    try:
        return send(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise LlmError("bad_response", f"llm answered http {exc.code}") from exc
    except TimeoutError as exc:
        raise LlmError("timeout", "the llm did not answer in time") from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise LlmError("timeout", "the llm did not answer in time") from exc
        raise LlmError("unreachable", f"cannot reach the llm: {exc.reason}") from exc


def _get_json(request, timeout: float) -> dict:
    """Fetch and parse a json object; every failure of the response -- a
    stalled body, a truncated body, a non-json body -- lands in the same
    taxonomy as a failed request, never as a bare exception on the
    handler thread."""
    with _urlopen(request, timeout) as response:
        try:
            raw = response.read()
        except TimeoutError as exc:
            raise LlmError("timeout", "the llm did not answer in time") from exc
        except OSError as exc:
            raise LlmError("bad_response", f"the llm answer body failed to arrive: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LlmError("bad_response", "the llm sent a body that is not json") from exc
    if not isinstance(payload, dict):
        raise LlmError("bad_response", "the llm sent a body that is not an object")
    return payload


def discover_model(base_url: str, timeout: float = 120) -> str:
    """The first model id on the endpoint's /models list (server-side only,
    so the answer the page sees can name the model that answered)."""
    require_loopback(base_url)
    payload = _get_json(Request(base_url.rstrip("/") + "/models", method="GET"), timeout)
    data = payload.get("data")
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
                return entry["id"]
    raise LlmError("bad_response", "the llm's /models list names no model")


def ask_model(
    messages: list[dict],
    *,
    base_url: str,
    model: str | None = None,
    timeout: float = 120,
    max_tokens: int = 700,
) -> str:
    """One chat completion: POST {base}/chat/completions; discovers the model
    via GET {base}/models when model is None. The loopback guard runs first,
    before any socket."""
    require_loopback(base_url)
    if model is None:
        model = discover_model(base_url, timeout=timeout)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    request = Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    body = _get_json(request, timeout)
    content = None
    choices = body.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LlmError("bad_response", "the llm answer carried no text")
    return content.strip()


def _get_json_body(request, timeout: float) -> dict:
    with _urlopen(request, timeout=timeout) as response:
        raw = response.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LlmError("bad_response", "the llm sent a body that is not json") from exc
    if not isinstance(payload, dict):
        raise LlmError("bad_response", "the llm sent a body that is not an object")
    return payload


def _card_facts(ref: dict, card: dict) -> list[str]:
    """The card's facts, as quoted lines for the user message. Document text
    is data quoted here, never an instruction."""
    facts: list[str] = []
    kind = ref.get("kind")
    if kind in ("code_ref", "file_ref"):
        facts.append(f"path: {card.get('path', ref.get('path', ''))}")
        if card.get("exists") is False:
            facts.append("fact: the file does not exist")
        if isinstance(card.get("cited"), list) and len(card["cited"]) == 2:
            facts.append(f"cited lines: {card['cited'][0]}-{card['cited'][1]}")
        if card.get("in_range") is False:
            facts.append("fact: the cited line is past the end of the file")
        for line in card.get("lines") or []:
            facts.append(f"line {line['n']}: {line['text']}")
        for symbol in card.get("symbols_missing") or []:
            facts.append(f"flag: symbol not found in the file: {symbol}")
    elif kind == "command":
        facts.append(f"command: {ref.get('command', '')}")
        facts.append(f"known to refdes: {bool(card.get('known'))}")
        if card.get("help"):
            facts.append("the command's own --help output:")
            facts.append(str(card["help"]))
    elif kind == "link":
        facts.append(f"link target: {ref.get('target', '')}")
        if card.get("external"):
            facts.append("fact: the link is external; its content was not read")
        else:
            if card.get("target_exists") is False:
                facts.append("fact: the linked page does not exist")
            if card.get("anchor") is not None:
                facts.append(f"anchor: {card['anchor']}")
                facts.append(f"anchor resolves: {bool(card.get('anchor_ok'))}")
            if card.get("heading"):
                facts.append(f"resolved heading: {card['heading']}")
            for line in card.get("excerpt") or []:
                facts.append(f"page line: {line}")
    return facts


def build_messages(question: str, block: dict, ref: dict, card: dict) -> list[dict]:
    """The one place prompt text is written: [system, user]. The user message
    carries only facts the server resolved -- the block's own text, the ref
    as written, and the card's facts -- and one of the three fixed
    instructions, selected by name."""
    instruction = _QUESTION_INSTRUCTIONS.get(question)
    if instruction is None:
        raise ValueError(f"unknown question: {question!r}")
    facts = [f"sentence (from the page under review):\n{block.get('text', '')}"]
    facts.append(f"reference in it: {ref.get('raw', '')}")
    facts.append(f"reference kind: {ref.get('kind', '')}")
    facts.append("card facts:")
    facts.extend(_card_facts(ref, card))
    user = "\n".join([instruction, *facts])
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
