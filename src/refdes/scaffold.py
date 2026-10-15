"""`refdes init`, `refdes new <type>`, and `refdes standard add-preset` /
`remove-preset` -- project scaffolding and standard-library selection
(docs/design/standard-library.md §3, §6, §8, §12).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from . import build as build_mod
from . import parse as parse_mod
from . import standards, textio
from .build import _format_required_when
from .configcheck import check_duplicate_keys
from .model import ItemType, SchemaError, destination_refusal
from .parse import yaml_safe_load_checked
from .schema import PROJECT_SETTINGS_NAME, load_project


class Refused(Exception):
    """A `refdes-project.yaml` this command had to rewrite and could not.

    Distinct from the `SchemaError`s these two preset commands raise for a
    bad request (an unknown preset, one not selected): those are decided
    before anything is touched and mean "you named the wrong thing", while
    this is the write the user asked for that the filesystem declined. It
    carries `(read-only tree?)` in the destination-naming shape
    (`model.destination_refusal`) and exits 2, the code both commands already
    use for "your config is not what you asked for it to be" -- see
    docs/cli-reference.md.
    """


def _vscode_schema_path(target_dir: str) -> str:
    """This project's own `.refdes/schema.json`, in the form `yaml.schemas`
    wants it: absolute, with forward slashes even on Windows."""
    return os.path.abspath(
        os.path.join(target_dir, ".refdes", "schema.json")
    ).replace("\\", "/")


def _vscode_settings_text(target_dir: str) -> str:
    """`.vscode/settings.json` content wiring `yaml.schemas` to this project's
    own `.refdes/schema.json`, keyed by an absolute path rather than the bare
    relative `./.refdes/schema.json` every project used to write identically.

    `redhat.vscode-yaml` does not reliably scope a relative schema path to the
    workspace folder that declared it, so two refdes projects open in the same
    VS Code session (a multi-root workspace, or just switching folders without
    a full reload) could end up validating one project's files against the
    other's schema -- a false rejection, not a near-miss, since the two
    schemas can differ arbitrarily (finding 9). An absolute path names one
    specific file unambiguously regardless of how many folders are open.

    The cost of that correctness is that the file names one machine, which is
    why writing it also puts it in `.gitignore` (see
    `_ensure_gitignore_entries`) and why an existing one is never silently
    skipped (see `vscode_settings_note`).
    """
    settings = {"yaml.schemas": {_vscode_schema_path(target_dir): ["items/**/*.yaml"]}}
    return json.dumps(settings, indent=2) + "\n"


# What `init` makes the project's .gitignore ignore: one entry per file that
# must not be committed, each stated the way this repo's own .gitignore states
# its reasoning -- the path named, the reason in a comment above it, the
# surrounding directory left alone. `init` writes one of them itself, and the
# rest are left behind by other commands (`build`, `check`, `fetch`, `serve`) in
# a project that has already been created -- which is why they are all wanted on
# every `init`, including one that wrote no editor settings. `.vscode/` as a
# whole must NOT be ignored (a project's `tasks.json`/`extensions.json` are
# shareable -- this repo commits its own) and neither must `.refdes/`, which
# holds the project's own record: the ID ledger, the citation lockfile, seals
# and board manifests all belong in git. So the patterns name the one file or
# the one subdirectory.
#
# No leading slash on any pattern, deliberately. Every one of them contains a
# slash away from its end, so git reads it as relative to the directory holding
# the `.gitignore` (gitignore(5): "if there is a separator at the beginning or
# middle of the pattern, then the pattern is relative to the directory level of
# the particular .gitignore file itself"). That is what a `.gitignore` `init`
# writes at the project root needs whether the project IS the repository root
# or one subdirectory of a larger repository -- verified with `git
# check-ignore -v` in both layouts. A leading `/` would anchor it the same way
# but would also read as a claim about a repository root we may not be in.


@dataclass(frozen=True)
class _GitignoreEntry:
    """One ignore pattern `init` ensures, with the comment block above it and
    the patterns that already cover it."""

    pattern: str
    covers: frozenset[str]
    block: str


def _covers(pattern: str, *whole_dirs: str) -> frozenset[str]:
    """The patterns that already state a position on `pattern`, in all the
    forms git accepts for the same intent.

    `whole_dirs` are directories whose own ignore covers everything inside
    them, so a project that ignores `.refdes/` has already said its piece about
    a file in there.

    A literal set, deliberately not a walk of git's pattern language -- and
    not the whole answer either. Inside a git repository git itself is asked
    what its patterns say (see `_git_ignore_verdict`), because git is last
    match wins and only git knows which line wins; this set is the fallback
    for the non-repository case, where `init` runs in directories that are
    not git repositories at all. It is over-approximative by design --
    naming a spelling it misses appends a line that is at worst redundant,
    while naming one it should not has `init` out-rank the project's own
    pattern, so every form listed must genuinely cover every path in
    `pattern`'s intent: the exact spellings, the basename spelling (git
    matches a slashless pattern at any depth), and the one-level globs
    (`.vscode/*` and `.vscode/**` each match the file inside the directory).
    """
    forms = {pattern, "/" + pattern, "**/" + pattern}
    stem = pattern.rstrip("/")
    if "/" in stem:
        parent, _, base = stem.rpartition("/")
        forms.add(base)
        if pattern.endswith("/"):
            forms.add(base + "/")
        for spelling in (parent, parent + "/"):
            for prefix in ("", "/", "**/"):
                forms |= {prefix + spelling + "/*", prefix + spelling + "/**"}
    for directory in whole_dirs:
        for spelling in (directory, directory + "/"):
            forms |= {spelling, "/" + spelling, "**/" + spelling}
    return frozenset(forms)


_VSCODE_SETTINGS_GITIGNORE = _GitignoreEntry(
    pattern=".vscode/settings.json",
    covers=_covers(".vscode/settings.json", ".vscode"),
    block=(
        "# Written by `refdes init`. The yaml.schemas path in this file is an\n"
        "# absolute path into one checkout, so a committed copy hands every other\n"
        "# clone a schema that resolves to nothing -- silently, in both tools.\n"
        "# Editor settings you mean to share belong in a file you write yourself.\n"
        ".vscode/settings.json\n"
    ),
)

_COPIES_GITIGNORE = _GitignoreEntry(
    pattern=".refdes/copies/",
    covers=_covers(".refdes/copies/", ".refdes"),
    block=(
        "# Written by `refdes init`. Kept local copies of datasheet bytes, one\n"
        "# per citation with `keep_copy: true`, and manufacturer datasheets are\n"
        "# generally copyrighted -- re-fetch them rather than commit them. The\n"
        "# rest of `.refdes/` is this project's own record (the ID ledger, the\n"
        "# citation lockfile, seals) and does belong in git, which is why this\n"
        "# names the one directory rather than `.refdes/` as a whole.\n"
        ".refdes/copies/\n"
    ),
)

_SCHEMA_JSON_GITIGNORE = _GitignoreEntry(
    pattern=".refdes/schema.json",
    covers=_covers(".refdes/schema.json", ".refdes"),
    block=(
        "# Written by `refdes init`. The merged JSON Schema is regenerated by\n"
        "# every command that loads the project, so a committed copy can only\n"
        "# ever disagree with the project config -- silently, in the editor.\n"
        ".refdes/schema.json\n"
    ),
)

_SEALING_OPTIN_GITIGNORE = _GitignoreEntry(
    pattern=".refdes/sealing-optin.json",
    covers=_covers(".refdes/sealing-optin.json", ".refdes"),
    block=(
        "# Written by `refdes init`. Which opt-back-in note the project has\n"
        "# already heard is per-checkout state, rewritten by `check`/`build`;\n"
        "# a committed copy can only disagree with the config -- silently, by\n"
        "# swallowing the note in someone else's clone (run-6a F10).\n"
        ".refdes/sealing-optin.json\n"
    ),
)

_PROJECT_WRITE_LOCK_GITIGNORE = _GitignoreEntry(
    pattern=".refdes-write.lock",
    covers=_covers(".refdes-write.lock"),
    block=(
        "# Shared project write lock for refdes CLI and serve. Empty and\n"
        "# per-machine; leave it in place while any refdes process may run.\n"
        ".refdes-write.lock\n"
    ),
)

# These entries do not depend on anything else `init` does: the files are
# written by project commands whatever happened here, so their ignore is
# written on every init. The `.vscode` entry is only
# wanted when `init` actually wrote that file (see `_write_vscode_settings`).
_REFDES_GITIGNORE = (
    _COPIES_GITIGNORE,
    _SCHEMA_JSON_GITIGNORE,
    _SEALING_OPTIN_GITIGNORE,
    _PROJECT_WRITE_LOCK_GITIGNORE,
)


_OWN_GITIGNORE_MATCH = re.compile(r"^(.*):(\d+):(.*)$")


def _git_ignore_verdict(
    target_dir: str,
    entry: _GitignoreEntry,
    cache: dict[str, Any] | None = None,
) -> bool | None:
    """git's own answer to "does this project's `.gitignore` already state a
    position on `entry.pattern`" -- True for yes, False for git's no, `None`
    for "git cannot be asked" (the caller then consults the text itself).

    `check-ignore -v` is the question, and it is the only tool that answers
    git's real pattern language: globs, basename spellings, and -- the case
    that made this necessary -- a `!.vscode/*` negation whose tracked file
    init's appended ignore line would silently out-rank, since git takes the
    *last* match. The pattern's parent directory is asked in the same
    question: a `!` on the directory (`.vscode/` then `!.vscode/`) is an
    intent about everything inside it, and the file's own path matches
    nothing in that shape.

    Only the project's own `.gitignore` counts as a yes. git resolves
    `.git/info/exclude`, a global `core.excludesFile`, and any parent
    directory's `.gitignore` ahead of it (and a file's negation of a
    parent-project pattern is that project's business, not a position this
    project's file has taken), so a winning match from anywhere else means
    git's yes is unavailable here. It is not a git no, though: the report
    names only the *winning* match, so a deeper nested `.gitignore`
    out-voting a line the project's own file did state is invisible in this
    output -- which is why a git no never vetoes the caller's own-text
    check, and why init still appends for info/exclude, global, and
    parent-only positions (none of those appear as lines of the project's
    own text).

    `--no-index` so the answer is the pattern chain alone, never an artifact
    of what happens to be staged in this checkout.

    `cache` is a per-`init`-call dict: the toplevel lookup is the same for
    every entry, and one init's passes (writability preflight, then append)
    ask the same questions -- the entries name disjoint paths, so no entry's
    answer can change between the two passes."""
    git = shutil.which("git")
    if git is None:
        return None
    if cache is not None and entry.pattern in cache:
        return cache[entry.pattern]
    paths = [entry.pattern]
    stem = entry.pattern.rstrip("/")
    parent = stem.rpartition("/")[0]
    if parent:
        paths.append(parent)
    try:
        if cache is not None and "toplevel" in cache:
            top_path = cache["toplevel"]
            if top_path is None:
                return None
        else:
            top = subprocess.run(
                [
                    git,
                    "-c",
                    # core.quotePath=false: git octal-quotes non-ASCII bytes
                    # in reported paths by default ("caf\\303\\251/.gitignore"),
                    # which matches no computed path and silently loses the
                    # verdict for a project directory with a non-ASCII name.
                    "core.quotePath=false",
                    "-C",
                    target_dir,
                    "rev-parse",
                    "--show-toplevel",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="surrogateescape",
                timeout=15,
                check=False,
            )
            top_path = top.stdout.strip() if top.returncode == 0 else None
            if cache is not None:
                cache["toplevel"] = top_path
            if top_path is None:
                return None
        probe = subprocess.run(
            [
                git,
                "-c",
                "core.quotePath=false",
                "-C",
                target_dir,
                "check-ignore",
                "-v",
                "--no-index",
                "--",
                *paths,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode == 1:
        verdict = False
    elif probe.returncode != 0:
        verdict = None
    else:
        own = os.path.relpath(
            os.path.join(target_dir, ".gitignore"), top_path
        ).replace(os.sep, "/")
        # and the same path through realpath, for platforms whose temp dirs
        # reach the repository through a symlink (git reports the toplevel
        # resolved).
        own_real = os.path.relpath(
            os.path.realpath(os.path.join(target_dir, ".gitignore")),
            os.path.realpath(top_path),
        ).replace(os.sep, "/")
        verdict = False
        for line in probe.stdout.splitlines():
            match = _OWN_GITIGNORE_MATCH.match(line.split("\t", 1)[0])
            if match is not None and match.group(1) in (own, own_real):
                verdict = True
                break
    if cache is not None:
        cache[entry.pattern] = verdict
    return verdict


def _gitignore_addresses(
    target_dir: str,
    text: str,
    entry: _GitignoreEntry,
    verdict_cache: dict[str, Any] | None = None,
) -> bool:
    """Whether the project's `.gitignore` already states its position on
    `entry.pattern` -- an ignore pattern or an explicit `!` negation.

    A negation counts: whoever wrote `!` + that pattern means to track the file,
    and git takes the *last* matching pattern, so appending ours would quietly
    out-rank a deliberate choice. Comments and blank lines do not.

    Inside a git repository a yes from git itself is authoritative (see
    `_git_ignore_verdict`); git's no and git's silence both fall through to
    the literal `_covers` spellings of the project's own text, because
    `check-ignore -v` names only the winning pattern and a deeper nested
    `.gitignore` out-voting one of the project's own lines is invisible in
    that report."""
    if _git_ignore_verdict(target_dir, entry, verdict_cache):
        return True
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lstrip("!") in entry.covers:
            return True
    return False


def _gitignore_patterns(text: str) -> list[str]:
    """The ignore patterns (not comments) written in `text`, in order."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def read_existing_gitignore(target_dir: str) -> str | None:
    """Read the project's `.gitignore` -- or refuse before `init` touches
    anything (DIAG-TRACE-006). Returns `None` when there is no `.gitignore`
    yet.

    Three shapes used to escape as tracebacks out of init: binary bytes
    (`UnicodeDecodeError` on the read), a file the process cannot read
    (`PermissionError`), and a *directory* named `.gitignore`
    (`IsADirectoryError` on the write). The first two died before anything
    was written, ugly but survivable; the third died *after*
    `refdes-project.yaml` and `.vscode/settings.json` were on disk, leaving
    a half-created project whose orphaned config then made every retry
    refuse to overwrite it. Here all three raise `SchemaError` instead,
    which `main()` prints as a named, exit-2 refusal, and they raise before
    any file is created: `init` does not begin writing until the file it
    will have to append to is proven readable text, absent, or a clean
    refusal.

    `cmd_init` keeps the returned text for the announcement diff
    (`added_gitignore_patterns`) -- within that call the preflight and the
    announcement's pre-read are one read. `scaffold.init` calls this too,
    under `_refuse_unwritable_gitignore`, as its own preflight for direct
    library callers, and `_ensure_gitignore_entries` reads the file again
    when it actually appends: a project init runs once and the file is
    small, so the refusal ordering is what matters here, not the read
    count.
    """
    path = os.path.join(target_dir, ".gitignore")
    if os.path.lexists(path) and not os.path.isfile(path):
        raise SchemaError(
            f"{path} exists but is not a regular file -- refdes init refuses "
            "to start rather than write a project around it; remove or "
            "rename it and run init again"
        )
    if not os.path.isfile(path):
        return None
    try:
        return textio.read_text(path)
    except UnicodeDecodeError as exc:
        raise SchemaError(
            f"cannot read {path}: not valid UTF-8 text at byte {exc.start} "
            f"({exc.reason}) -- .gitignore must be plain text; convert or "
            "remove it and run init again"
        ) from None
    except OSError as exc:
        raise SchemaError(
            f"cannot read {path}: {exc.strerror or exc} -- make .gitignore "
            "readable, or remove it, and run init again"
        ) from None


def _refuse_unwritable_gitignore(
    target_dir: str,
    entries: list[_GitignoreEntry],
    verdict_cache: dict[str, Any] | None = None,
) -> None:
    """Refuse an existing `.gitignore` that cannot be appended to, BEFORE
    `init` writes anything (DIAG-TRACE-006, review follow-up).

    The read-only-but-readable shape -- a mode-0444 file with valid UTF-8
    text -- passed the first preflight: the read worked, init wrote
    `refdes-project.yaml` and `.vscode/settings.json`, and only then did
    `_ensure_gitignore_entries`' own write die of `PermissionError`, the
    same half-created project the directory shape left. So `init` asks
    `os.access(..., W_OK)` up front instead of finding out at the write.

    The refusal is conditional on having something to write: an existing
    `.gitignore` that already states the project's position on every
    wanted path (an ignore or a deliberate `!`) needs no append, and a
    read-only file holding exactly that is not a reason to refuse -- that
    project inits. Only a read-only file that is *missing* an entry
    cannot receive it, and that init refuses with nothing written.

    What this cannot promise: a `chmod` concurrent with init, landing
    between this check and the append, still surfaces as a write-time
    traceback -- no check can close that, because init's two files could
    not be written atomically even with a perfect check. The guarantee is
    that an obstacle present when init starts is named before anything is
    created, not that the filesystem holds still mid-command.
    """
    text = read_existing_gitignore(target_dir)
    if text is None:
        return
    if any(
        not _gitignore_addresses(target_dir, text, entry, verdict_cache)
        for entry in entries
    ):
        path = os.path.join(target_dir, ".gitignore")
        if not os.access(path, os.W_OK):
            raise SchemaError(
                f"cannot append to {path}: file is not writable -- make "
                ".gitignore writable, or remove it, and run init again"
            )


def _ensure_gitignore_entries(
    target_dir: str,
    entries: list[_GitignoreEntry],
    verdict_cache: dict[str, Any] | None = None,
) -> None:
    """Make sure the project's `.gitignore` ignores each entry's path,
    creating `.gitignore` when the project has none.

    Append-only and idempotent: `.gitignore` is hand-authored and hand-commented
    like refdes-project.yaml, so nothing outside the appended blocks moves, and
    when some existing pattern already covers a path nothing is written for that
    path at all. Each block takes the file's own line ending (textio's
    `append_ending` rule), so a CRLF gitignore does not grow an LF island.
    """
    path = os.path.join(target_dir, ".gitignore")
    if not os.path.isfile(path):
        textio.write_text(path, _joined_blocks(entries, textio.LF))
        return
    existing = textio.read_text(path)
    missing = [
        entry
        for entry in entries
        if not _gitignore_addresses(target_dir, existing, entry, verdict_cache)
    ]
    if not missing:
        return
    ending = textio.append_ending(existing)
    gap = ending if existing.strip() else ""
    textio.write_text(path, existing + gap + _joined_blocks(missing, ending))


def _joined_blocks(entries: list[_GitignoreEntry], ending: str) -> str:
    """The comment blocks of `entries`, one blank line apart, on `ending`'s line
    endings."""
    parts = [entries[0].block.replace("\n", ending)]
    parts += [ending + entry.block.replace("\n", ending) for entry in entries[1:]]
    return "".join(parts)


def added_gitignore_patterns(before: str | None, after: str) -> list[str]:
    """Which ignore patterns a `.gitignore` write added, given its text before
    (`None` when there was no file) and after. Pure, so `cmd_init` can announce
    exactly what appeared without `init` having to report anything -- and an
    announcement that stays true when `init` appended nothing."""
    prior = set(_gitignore_patterns(before)) if before is not None else set()
    return [p for p in _gitignore_patterns(after) if p not in prior]


def _write_vscode_settings(target_dir: str) -> bool:
    """Write `.vscode/settings.json`, unless one is already there -- a file the
    author wrote is not `init`'s to overwrite, and merging into one is not
    safe either: `.vscode/settings.json` is JSONC (VS Code accepts comments,
    and comments in a real settings file are the norm, this repo's own among
    them), so `json.loads` cannot read the common case.

    Returns True when this call wrote the file -- which is exactly when the
    machine-specific absolute path inside it is `init`'s responsibility, and
    so the only case that gets the `.gitignore` entry. A settings file that
    was already there may already be tracked, where a gitignore line would do
    nothing but promise. (The `.refdes/` entries are wanted either way -- see
    `_ensure_gitignore_entries` -- which is why this return value no longer
    decides whether `.gitignore` gets written at all.)
    """
    settings_path = os.path.join(target_dir, ".vscode", "settings.json")
    if os.path.isfile(settings_path):
        return False
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    textio.write_text(settings_path, _vscode_settings_text(target_dir))
    return True


def vscode_settings_exists(target_dir: str) -> bool:
    """True when `refdes init` will find an existing `.vscode/settings.json`
    and leave it alone. The caller has to ask BEFORE init runs: afterwards the
    file is present either way, and nothing on disk distinguishes the file
    init wrote from the one it skipped."""
    return os.path.isfile(os.path.join(target_dir, ".vscode", "settings.json"))


def vscode_settings_note(target_dir: str) -> str:
    """The one-line note `refdes init` prints when it left an existing
    `.vscode/settings.json` alone. Without it the command exits 0 having
    silently not wired up schema completion, which is the state a newcomer
    with a workspace settings file already in place lands in (user-sim run 2,
    BUG 3). The absolute path is spelled out rather than left a `<path>`
    placeholder so the line is paste-ready into the file it names. Printed by
    the CLI -- this module does not print.
    """
    return (
        "note: .vscode/settings.json already exists; left it alone. Add "
        f'"yaml.schemas": {{"{_vscode_schema_path(target_dir)}": '
        '["items/**/*.yaml"]} yourself for schema completion.'
    )


def _init_yaml(base: str | None, version: int | None, presets: list[str]) -> str:
    if base is None:
        standard_block = "standard: none\n"
    else:
        preset_list = ", ".join(presets)
        standard_block = (
            "standard:\n"
            f"  base: {base}\n"
            f"  version: {version}\n"
            f"  presets: [{preset_list}]\n"
        )
    return (
        "site:\n"
        '  title: "New Project — Design Reference"\n'
        "  out: _site\n"
        "\n"
        f"{standard_block}"
        "\n"
        "id:\n"
        "  width: 3\n"
        "  ledger: .refdes/ids.yaml\n"
    )


def init(
    target_dir: str,
    standard: str | None = "hardware",
    presets: list[str] | None = None,
    write_vscode_settings: bool = True,
) -> str:
    """Write a minimal `refdes-project.yaml` that points at the standard rather than
    copying it (docs/design/standard-library.md §3) -- no `types:`,
    `link_types:`, or `sets:` key anywhere in the file; that absence
    is the point. `standard=None` writes `standard: none`, the explicit
    escape hatch. `<version>` is never written as the literal string
    "latest": resolved here, once, to the concrete integer the installed
    tool currently ships as newest.

    Also writes `.vscode/settings.json` for schema completion, and makes sure
    the project's `.gitignore` covers the three files that must not be
    committed: `.vscode/settings.json` (the schema path in it is absolute and
    machine-specific), `.refdes/copies/` (kept datasheet bytes, generally
    copyrighted) and `.refdes/schema.json` (regenerated by every command that
    loads the project). The last two were a promise the docs made three times
    with nothing behind it -- `git add -A` in a fresh `init` project staged a
    6 MB datasheet and a 1696-line generated schema. An existing
    `.vscode/settings.json` is left exactly as it is and no gitignore entry is
    added for it.

    Both outcomes are announced by the caller, which is the only printer here:
    `cmd_init` asks `vscode_settings_exists` before calling this and prints
    `wrote .vscode/settings.json` when init wrote it and `vscode_settings_note`
    when it did not, so neither the write nor the skip is silent. The return
    value stays the config path alone -- this function reports nothing about
    the second file, and `cmd_init` diffs `.gitignore` itself for the third
    (`added_gitignore_patterns`).

    Returns the path written. Raises SchemaError if refdes-project.yaml already
    exists at the target, if `presets` is given with `standard=None`
    (every preset's types target base types, so presets require a base), or
    if a `.gitignore` is in the way -- unreadable, malformed, not a regular
    file (see `read_existing_gitignore`), or existing-but-not-appended-to
    while still missing a wanted entry (see `_refuse_unwritable_gitignore`).
    Every `.gitignore` check runs here, before anything is created, so a
    refused init leaves the directory exactly as it found it.
    """
    presets = presets or []
    if standard is None and presets:
        raise SchemaError(
            "presets require a base standard; set standard.base or drop presets:"
        )

    config_path = os.path.join(target_dir, "refdes-project.yaml")
    if os.path.exists(config_path):
        raise SchemaError(f"{config_path} already exists -- refdes init refuses to overwrite it")

    version: int | None = None
    if standard is not None:
        version = standards.latest_version(standard)
        available = standards.available_presets(standard, version)
        for preset_name in presets:
            if preset_name not in available:
                import difflib

                close = difflib.get_close_matches(preset_name, available, n=1, cutoff=0.5)
                hint = f" Did you mean {close[0]!r}?" if close else ""
                raise SchemaError(
                    f"preset {preset_name!r} does not exist for {standard}@{version} "
                    f"(available: {available}).{hint}"
                )

    # The wanted entries are assembled BEFORE the first write, because the
    # `.gitignore` preflight below has to know whether there is anything to
    # append. The `.refdes/` entries always: those files are written by
    # `build`, `check`, `fetch` and the rest whatever happened with the
    # editor files, so a project that skipped schema completion is exactly
    # the one still holding a multi-megabyte datasheet copy. The `.vscode`
    # entry only when we will write that file ourselves -- and whether we
    # will is knowable now, from the same predicate `_write_vscode_settings`
    # checks, rather than only from its return value after the fact.
    wants_vscode_entry = write_vscode_settings and not vscode_settings_exists(target_dir)
    wanted: list[_GitignoreEntry] = (
        [_VSCODE_SETTINGS_GITIGNORE] if wants_vscode_entry else []
    ) + list(_REFDES_GITIGNORE)
    # One git-verdict cache for the whole call: the preflight below and the
    # append pass above ask identical questions (the entries name disjoint
    # paths, so nothing init writes between them answers any of them
    # differently), and each answer is a `git` process.
    verdict_cache: dict[str, Any] = {}
    _refuse_unwritable_gitignore(target_dir, wanted, verdict_cache)

    os.makedirs(target_dir, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(_init_yaml(standard, version, presets))

    if wants_vscode_entry:
        _write_vscode_settings(target_dir)
    _ensure_gitignore_entries(target_dir, wanted, verdict_cache)

    return config_path


# --------------------------------------------------------------- refdes new


def _field_hint(fname: str, fspec) -> str:
    if fspec.type == "enum":
        return "choices: " + ", ".join(fspec.choices or [])
    return fspec.type


def _item_field_line(fname: str, fspec) -> str:
    """One field's line in a `refdes new` skeleton (shared by the single-item
    and --list forms): a required field with a declared `default:` is written
    with that default, a required field with none gets an empty placeholder,
    an optional field is written commented-out, with the same choices:/type
    hint the schema's own `description` carries."""
    hint = _field_hint(fname, fspec)
    if fspec.default is not None:
        return f"{fname}: {fspec.default}  # {hint}"
    if fspec.required:
        return f"{fname}:  # required -- {hint}"
    cond = ""
    if fspec.required_when:
        cond = f"; required when {_format_required_when(fspec.required_when)}"
    return f"# {fname}:  # {hint}{cond}"


def _item_link_line(lname: str, targets) -> str:
    """One link's commented-out line in a `new` skeleton, naming its allowed
    target types the same way the schema's description does."""
    target_desc = ", ".join(targets) if targets else "any"
    return f"# {lname}: []  # target: {target_desc}"


def new_item_text(type_name: str, spec: ItemType) -> str:
    """Scaffold one item's front matter for `type_name`, generated from the
    identical resolved `ItemType` the JSON Schema (schema_json.py) and
    `items.json` (render.py) both read -- not a second, hand-maintained
    template per type that could drift from either (docs/design/
    standard-library.md §12's closing section).
    """
    lines = ["---", "id:", f"type: {type_name}"]
    for fname, fspec in spec.fields.items():
        lines.append(_item_field_line(fname, fspec))
    for lname, targets in spec.links.items():
        lines.append(_item_link_line(lname, targets))
    lines.append("---")
    lines.append("")
    # body: is reserved, not a field, so it never shows up in the loop above
    # -- without this, a type whose entire content lives there (hardware@3's
    # requirement/bound) scaffolds with no hint that anything more is needed.
    if spec.body_required:
        lines.append("<!-- required: the content itself goes here. -->")
    else:
        lines.append("<!-- optional body. -->")
    lines.append("")
    return "\n".join(lines)


def initial_field_values(spec: ItemType, values: dict) -> dict:
    """The field set a created item starts with -- the identical set
    `new_item_text` scaffolds, resolved to values: an author-supplied value
    wins, a field with a declared `default:` falls back to that default (the
    same rule `_item_field_line` writes the default into a skeleton), and
    anything else is left out for the schema's own required/optional checks
    to judge. Shared so the editor's create path and `refdes new` can never
    disagree about which fields an item of this type starts with."""
    out: dict = {}
    for fname, fspec in spec.fields.items():
        if fname in values:
            out[fname] = values[fname]
        elif fspec.default is not None:
            out[fname] = fspec.default
    return out


def new_list_text(type_name: str, spec: ItemType) -> str:
    """Scaffold a list file for `type_name` for `refdes new <type> --list`:
    a `defaults:` block carrying the items' shared type and the status
    field's declared default (omitted entirely when the type declares no
    status field), then one empty entry.

    The file takes the mapping form a list file must have (`defaults:` plus
    an `items:` key) rather than the bare top-level list in the design's
    sketch, so redirecting the output straight into place can't produce a
    file `parse_list_file` rejects. The per-entry fields are exactly what
    `new_item_text` scaffolds for the same type; `type:` and a defaulted
    `status:` live in `defaults:` instead of every entry, and an entry's own
    value wins (the layout's "one status edit" property -- candidate parts
    §6.1/§6.4).
    """
    lines = ["---", "defaults:", f"  type: {type_name}"]
    status = spec.fields.get("status")
    if status is not None and status.default is not None:
        lines.append(f"  status: {status.default}")
    lines.append("")
    lines.append("items:")
    lines.append("  - id:")
    for fname, fspec in spec.fields.items():
        if fname == "status" and status is not None and status.default is not None:
            continue  # already in the defaults: block above
        lines.append(f"    {_item_field_line(fname, fspec)}")
    for lname, targets in spec.links.items():
        lines.append(f"    {_item_link_line(lname, targets)}")
    if spec.body_required:
        lines.append("    # body:  # required: the content itself goes here.")
    else:
        lines.append("    # body:  # optional body.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------- standard.presets


_PRESETS_RE = re.compile(r"(presets:\s*)\[([^\]]*)\]")


def _edit_presets_list(raw_text: str, mutate) -> str:
    """A minimal, comment-preserving text edit of `standard.presets: [...]`
    -- refdes-project.yaml is hand-authored and hand-commented, unlike the tool's
    own machine-owned lockfiles, so this never re-serializes the whole file
    (which would silently drop every comment). Only supports the flow-style
    list `refdes init` itself always writes; a block-style list is left for
    the author to edit by hand."""
    match = _PRESETS_RE.search(raw_text)
    if match is None:
        raise SchemaError(
            "could not find a 'presets: [...]' list to edit in refdes-project.yaml -- "
            "if standard.presets: is written in block-list style, edit it by hand"
        )
    current = [p.strip() for p in match.group(2).split(",") if p.strip()]
    new_list = mutate(current)
    new_span = f"{match.group(1)}[{', '.join(new_list)}]"
    return raw_text[: match.start()] + new_span + raw_text[match.end() :]


def _config_write_target(config_path: str) -> str:
    """Where the atomic preset write should actually land for ``config_path``.

    ``textio.atomic_write_text`` swaps a same-directory temp into place with
    ``os.replace``, and ``rename`` replaces the *symlink itself* rather than
    following it -- unlike the truncate-on-open ``write_text`` it replaced,
    which wrote through the link. A project that keeps ``refdes-project.yaml``
    as a symlink (e.g. to ``actual-project.yaml``) would therefore lose the
    link and leave the file behind it untouched. Resolving to the link's
    target keeps both halves of the old behavior: the symlink stays a symlink,
    and the bytes land in the real file. For an ordinary (non-symlink) config
    this is just its absolute path -- same basename, same directory, same mode
    -- so the write is unchanged (add/remove-preset, WRITE-ATOMIC-003 review).
    """
    return os.path.realpath(config_path)


def _read_settings(config_path: str) -> tuple[dict[str, Any], str]:
    """`refdes-project.yaml` as `(mapping, raw text)`, refusing a repeated key.

    The same rule `load_project` applies, and through the same detector: a
    repeat here would mean `_edit_presets_list` appended a preset to the text of
    a `presets:` the loader is not even reading, so the write would land in a
    block this project does not resolve. The loader is not on this path --
    `add_preset`/`remove_preset` read the file to edit a span of it -- so
    without this the one command that *writes* the config would be the one
    command that never said the config was ambiguous.

    The raw text comes back alongside the mapping because the edit is a
    comment-preserving span edit of it, never a re-serialization.
    """
    raw_text = textio.read_text(config_path)
    loaded, duplicates = yaml_safe_load_checked(raw_text)
    check_duplicate_keys(duplicates, PROJECT_SETTINGS_NAME)
    return loaded or {}, raw_text


def _read_standard_cfg(raw: dict[str, Any]) -> dict[str, Any]:
    standard_cfg = raw.get("standard")
    if not isinstance(standard_cfg, dict):
        raise SchemaError(
            "standard.presets: requires a base standard -- this project has no "
            "standard: block (or uses standard: none) to add or remove a preset "
            "from"
        )
    return standard_cfg


def add_preset(project_root: str, preset_name: str) -> None:
    """Validate `preset_name` exists at the project's pinned version, then
    append it to `standard.presets:`. On the next load its types, links,
    and sets simply join the merged schema -- no migration step, no
    re-running init (docs/design/standard-library.md §8)."""
    config_path = os.path.join(project_root, PROJECT_SETTINGS_NAME)
    # textio both ways. The read was text mode, so a CRLF config arrived here
    # already folded to LF, and the write was text mode, so the platform
    # translated it again -- adding one preset to an LF config rewrote the
    # whole file to CRLF on Windows, and adding one to a CRLF config rewrote it
    # to LF on Linux. `_edit_presets_list` is a comment-preserving span edit on
    # the raw text precisely so nothing outside `presets: [...]` moves. The
    # write goes through `atomic_write_text`: a truncate-on-open that fails
    # mid-write (ENOSPC) used to leave a half-written config behind while the
    # refusal below claimed the presets line was "exactly as it was" -- the
    # same-directory temp plus rename means the refusal is now true. It writes
    # to the resolved target so a symlinked `refdes-project.yaml` keeps being a
    # symlink and the change lands in the file behind it (`rename` would
    # otherwise replace the link itself).
    raw, raw_text = _read_settings(config_path)
    standard_cfg = _read_standard_cfg(raw)

    base, version = standard_cfg.get("base"), standard_cfg.get("version")
    available = standards.available_presets(base, version)
    if preset_name not in available:
        import difflib

        close = difflib.get_close_matches(preset_name, available, n=1, cutoff=0.5)
        hint = f" Did you mean {close[0]!r}?" if close else ""
        raise SchemaError(
            f"preset {preset_name!r} does not exist for {base}@{version} "
            f"(available: {available}).{hint}"
        )
    current = standard_cfg.get("presets") or []
    if preset_name in current:
        raise SchemaError(f"preset {preset_name!r} is already selected")

    new_text = _edit_presets_list(raw_text, lambda lst: lst + [preset_name])
    try:
        textio.atomic_write_text(_config_write_target(config_path), new_text)
    except OSError as exc:
        raise Refused(
            destination_refusal(
                "refdes-project.yaml",
                f"so {preset_name!r} was not added and standard.presets: is "
                "exactly as it was. Make the tree writable and run it again.",
            )
        ) from exc


def remove_preset(project_root: str, preset_name: str) -> list:
    """Remove `preset_name` from `standard.presets:`, reporting what that
    breaks BEFORE writing the change: every type, link, and set the
    preset provided disappears from the merged schema on the next load, so
    an item still using one of them needs to be seen now, not discovered on
    the next unrelated build (docs/design/standard-library.md §8).

    Returns the diagnostics a build against the post-removal config would
    produce. The config is still edited even if that list is non-empty --
    this command's whole job is to surface the consequence, not to block an
    author who has already decided to accept it.
    """
    config_path = os.path.join(project_root, PROJECT_SETTINGS_NAME)
    raw, raw_text = _read_settings(config_path)
    standard_cfg = _read_standard_cfg(raw)
    current = standard_cfg.get("presets") or []
    if preset_name not in current:
        raise SchemaError(
            f"preset {preset_name!r} is not currently selected "
            f"(standard.presets: {current})"
        )

    new_text = _edit_presets_list(raw_text, lambda lst: [p for p in lst if p != preset_name])

    # Simulate the removal via a scratch copy in the same directory, so the
    # report reflects the post-removal state before the real file is touched.
    # Outside the try, deliberately: a refusal here means the copy was never
    # written, so the `finally` has nothing to clean up and must not be
    # reached -- and nothing has been changed either way, so the same refusal
    # answers for both this write and the real one below. The copy is written
    # atomically (same-directory temp, rename on success, temp unlinked on
    # failure), so a mid-write ENOSPC takes its partial file with it: the
    # "Nothing changed." below stays true, with no truncated `.scratch` or
    # temp left in the project root.
    scratch_path = config_path + ".scratch"
    try:
        textio.atomic_write_text(scratch_path, new_text)
    except OSError as exc:
        raise Refused(
            destination_refusal(
                "refdes-project.yaml",
                f"so {preset_name!r} is still selected, and the check of what "
                "its removal would break never ran. Nothing changed. Make the "
                "tree writable and run it again.",
            )
        ) from exc
    try:
        project = load_project(config_path=scratch_path)
        parse_mod.load_items(project, require_ids=False)
        build_mod.build(project, seal_write=False, reseal=False)
        diagnostics = list(project.diagnostics)
    finally:
        os.remove(scratch_path)

    # Last, so the scratch copy is already gone when this is refused and the
    # refusal leaves no litter behind. Atomic for the same reason as the other
    # two writes here: a truncate that failed mid-write used to destroy the
    # config while this refusal said "Nothing changed." As in `add_preset` it
    # writes the resolved target, so a symlinked config keeps being a symlink
    # and the removal lands in the real file behind it.
    try:
        textio.atomic_write_text(_config_write_target(config_path), new_text)
    except OSError as exc:
        raise Refused(
            destination_refusal(
                "refdes-project.yaml",
                f"so {preset_name!r} is still selected. Nothing changed. Make "
                "the tree writable and run it again.",
            )
        ) from exc

    return diagnostics
