"""`refdes init`, `refdes new <type>`, and `refdes standard add-preset` /
`remove-preset` -- project scaffolding and standard-library selection
(docs/design/standard-library.md §3, §6, §8, §12).
"""

from __future__ import annotations

import json
import os
import re
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
    the literal spellings that cover it where git cannot be asked (see
    `_gitignore_addresses`: inside a repository git answers first)."""

    pattern: str
    covers: frozenset[str]
    block: str


def _covers(pattern: str, *whole_dirs: str) -> frozenset[str]:
    """The patterns that already state a position on `pattern`, in all the
    forms git accepts for the same intent.

    `whole_dirs` are directories whose own ignore covers everything inside
    them, so a project that ignores `.refdes/` has already said its piece about
    a file in there.

    A small literal set on purpose rather than a walk of git's pattern
    language: inside a repository git itself answers the coverage question
    (see `_gitignore_addresses`, which asks it first), and this is what
    answers in a plain directory -- where nothing is ignored in the first
    place -- and for a git that cannot be run.
    """
    forms = {pattern, "/" + pattern, "**/" + pattern}
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


_GIT_TIMEOUT_SECONDS = 10


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str] | None:
    """Run `git` and hand back the completed process, or None when git
    cannot answer at all: not installed, too old to know the flag, not a
    repository, a timeout, a decode the console chose for us. Callers treat
    None as "git has no opinion", which is exactly the state a plain
    directory is in, and answer from the literal set there instead -- init
    must never crash over a git it cannot talk to (DOC-REMEDY-018 review)."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None


def _repo_toplevel(target_dir: str) -> str | None:
    """The root of the git repository `target_dir` lives in, or None when
    there is no repository (the probe is `rev-parse --show-toplevel`, not
    `check-ignore`: in a non-repository `check-ignore` exits 1, the same
    code it uses for "not ignored", so it cannot tell the two apart)."""
    proc = _git(["rev-parse", "--show-toplevel"], target_dir)
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _check_ignore_verdict(toplevel: str, relpath: str) -> bool | None:
    """Git's own answer for one repository-relative path, asked with
    `check-ignore --no-index -v` from the repository root: True when a
    pattern wins -- an ignore, *or* an explicit `!` naming the path, which
    git reports with exit 0 and the negated pattern on stdout -- False when
    nothing matches, None when git could not be asked.

    A winning match of either polarity is the project having stated its
    position: an ignore covers the path, and a negation means the author
    chose to track it -- appending ours after that wins by git's
    last-match rule, which is the whole of DOC-REMEDY-018. This function
    is deliberately never allowed to second-guess the answer with the
    literal set: inside a repository git IS the matcher, and a spelling we
    would not have recognized (`.vscode/*` + `!.vscode/*`, a bare
    `settings.json`) must read as covering exactly when git says it does.

    `--no-index` because the file is not in the index (init has not
    written it, and in the preflight nothing has been created yet);
    a path absent from disk is matched by the patterns all the same."""
    proc = _git(["check-ignore", "--no-index", "-v", "--", relpath], toplevel)
    if proc is None:
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def _git_covers(target_dir: str, entry: _GitignoreEntry) -> bool | None:
    """Git's verdict on one entry, in the repository `target_dir` lives in,
    or None when git has none.

    The entry is probed as a path relative to the repository root (realpath
    on both sides: a symlinked temp directory, `/var` behind `/private/var`,
    is the same tree to git as to us), with the trailing slash a directory
    entry carries kept -- git matches a directory-only pattern like
    `.refdes/copies/` against `.refdes/copies/`, and against nothing else.
    When the path itself matches nothing, its parent directory is asked
    too: a project that wrote `!.vscode/` stated its intent about the
    directory's contents, and a negation on the directory is invisible to
    a probe of the file path alone (git's own `!dir/` rule)."""
    toplevel = _repo_toplevel(target_dir)
    if toplevel is None:
        return None
    root = os.path.realpath(toplevel)
    base = os.path.realpath(target_dir)
    try:
        rel = os.path.relpath(
            os.path.join(base, *entry.pattern.strip("/").split("/")), root
        )
    except ValueError:
        return None  # e.g. Windows: target on a different drive than the root
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None  # the entry is not inside the repository git answered for
    rel = rel.replace(os.sep, "/")
    probe = rel + "/" if entry.pattern.endswith("/") else rel
    verdict = _check_ignore_verdict(root, probe)
    if verdict is None:
        return None
    if verdict:
        return True
    parent, _, _ = probe.rstrip("/").rpartition("/")
    if not parent:
        return False  # an entry at the repository root has no parent to ask
    # Asked WITHOUT the trailing slash: a `!dir/` negation wins on the
    # directory path (`check-ignore .vscode` exits 0 naming `!.vscode/`),
    # while the same probe spelled `vscode/` exits 1 -- the shape this
    # probe exists for, verified against git in .scratch/p018-redo/.
    return _check_ignore_verdict(root, parent)


#: Git's `check-ignore -v` line: `source:linenumber:pattern<TAB>pathname`
#: (gitignore(5)-documented format). The source is matched lazily and the
#: pattern greedily, which parses the realistic shapes -- a negated pattern
#: containing colons, a pathname containing tabs -- correctly; a line the
#: regex cannot read is answered as "no opinion", never as a guess.
_CHECK_IGNORE_SOURCE = re.compile(r"^(.*?):(\d+):(.*)\t(.*)$")


def _check_ignore_ignored(toplevel: str, relpath: str) -> bool | None:
    """Git's *ignored* answer for one repository-relative path: True only
    when an ignore pattern wins; False when nothing matches or when the
    winner is a `!` negation -- the author chose to track the path.

    This is `_check_ignore_verdict`'s sibling for the question the verdict
    cannot answer: an exit-0 match of either polarity is "the project
    stated its position" (right for the append decision, where a negation
    means do not out-rank it), but a tracking position is not "gitignored"
    -- reading it as one is the false paren R11-F2 reported. The winning
    pattern is read from the `-v` source line; a negation is quoted by git
    as a whole (`"!foo bar"` for a pattern with a space), so the quotes
    come off before the `!` test. The exit codes and the `--no-index`
    reasoning are the sibling's."""
    proc = _git(["check-ignore", "--no-index", "-v", "--", relpath], toplevel)
    if proc is None:
        return None
    if proc.returncode == 1:
        return False
    if proc.returncode != 0:
        return None
    match = _CHECK_IGNORE_SOURCE.match(proc.stdout.split("\n", 1)[0])
    if match is None:
        return None
    pattern = match.group(3)
    if pattern.startswith('"') and pattern.endswith('"'):
        pattern = pattern[1:-1]
    return not pattern.startswith("!")


def _git_ignores(target_dir: str, entry: _GitignoreEntry) -> bool | None:
    """Git's *ignored* verdict on one entry -- the path probe of
    `_git_covers`, the `_check_ignore_ignored` answer -- or None when git
    has none. The parent directory is asked when the file path matches
    nothing: there a winning `dir/` ignore ignores the contents (the file
    probe reads it as a match all the same on a path that exists as a
    directory, and the parent read is the belt for the not-on-disk probe),
    and a winning `!dir/` negation tracks them. Same realpath, same
    trailing-slash, same repository-must-contain-the-entry rules."""
    toplevel = _repo_toplevel(target_dir)
    if toplevel is None:
        return None
    root = os.path.realpath(toplevel)
    base = os.path.realpath(target_dir)
    try:
        rel = os.path.relpath(
            os.path.join(base, *entry.pattern.strip("/").split("/")), root
        )
    except ValueError:
        return None  # e.g. Windows: target on a different drive than the root
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None  # the entry is not inside the repository git answered for
    rel = rel.replace(os.sep, "/")
    probe = rel + "/" if entry.pattern.endswith("/") else rel
    verdict = _check_ignore_ignored(root, probe)
    if verdict:
        return True
    parent, _, _ = probe.rstrip("/").rpartition("/")
    if not parent:
        return False if verdict is False else None
    parent_verdict = _check_ignore_ignored(root, parent)
    if parent_verdict is not None:
        return parent_verdict
    return verdict


def vscode_settings_ignored(target_dir: str) -> bool:
    """Whether `.vscode/settings.json` is *ignored* -- read by `cmd_init`
    to print a true paren (R11-F2). The distinction from
    `_gitignore_addresses` (which answers "stated a position", the append
    question) is the whole of this function: inside a repository git's
    ignored answer wins, and a `!` negation is NOT ignored; outside one
    (or with a git that cannot be asked) the literal set answers, a
    negated line not counting.

    No preflight here: this reads the `.gitignore` `init` has already
    written (the announcement runs after a successful init, whose
    preflight proved the file readable), and a file that went unreadable
    in between answers "not ignored" -- the honest fallback for an
    announcement, in the direction that over-warns, never the
    direction that hides a committable machine-specific path."""
    verdict = _git_ignores(target_dir, _VSCODE_SETTINGS_GITIGNORE)
    if verdict is not None:
        return verdict
    path = os.path.join(target_dir, ".gitignore")
    text = None
    if os.path.isfile(path):
        try:
            text = textio.read_text(path)
        except (OSError, UnicodeDecodeError):
            text = None
    if text is None:
        return False
    return _literal_ignores(text, _VSCODE_SETTINGS_GITIGNORE)


def _literal_addresses(text: str, entry: _GitignoreEntry) -> bool:
    """The literal answer: some pattern line in `text` spells out (in one of
    the forms `_covers` accepts) the entry's position -- an ignore pattern
    or an explicit `!` negation. Comments and blank lines do not.

    This is the whole answer outside a git repository -- there is nothing
    ignored in a plain directory in the first place, and no matcher to
    consult -- and the fallback for a git that cannot be run. Inside a
    repository git itself answers instead (see `_gitignore_addresses`);
    the set is deliberately NOT widened for git's pattern language
    (globs, character classes, basenames), because an approximation of
    git's matcher here is exactly what out-ranked authors' negations in
    DOC-REMEDY-018's first fix."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if stripped.lstrip("!") in entry.covers:
            return True
    return False


def _literal_ignores(text: str, entry: _GitignoreEntry) -> bool:
    """The literal *ignored* answer: a pattern line states an ignore of the
    entry's path. A `!` negation line states the opposite position and is
    not ignored -- the split R11-F2 is, with the same reasoning as
    `_check_ignore_ignored`'s git side. Outside a repository there is no
    matcher whose last-match rule a negation could lose to, so this reads
    the lines as written: an author who negates a pattern in a plain
    directory is not tracked by anything (git does not exist there), and
    the plain answer is what the announcement gets."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if not stripped.startswith("!") and stripped in entry.covers:
            return True
    return False


def _gitignore_addresses(target_dir: str, text: str, entry: _GitignoreEntry) -> bool:
    """Whether the project has already stated its position on
    `entry.pattern` -- an ignore pattern that covers the path, or an
    explicit `!` negation of it.

    Inside a git repository the question is git's, and git answers it:
    `check-ignore --no-index -v` decides, negation included, with the
    entry's parent directory asked as well for the `!dir/` shape. The
    literal set never overrides a repository git read as "nothing covers
    this" (the project's position on the exact path is then absent, and
    init appends), and a spelling the literal set does not know cannot
    hide a covering line git reads.

    Outside a repository -- and for a git that cannot be asked -- the
    literal set answers, unchanged from before: there is no matcher whose
    last-match rule we could out-rank, and today's spellings are today's
    behavior.
    """
    verdict = _git_covers(target_dir, entry)
    if verdict is not None:
        return verdict
    return _literal_addresses(text, entry)


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


def _refuse_unwritable_gitignore(target_dir: str, entries: list[_GitignoreEntry]) -> None:
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
    wanted path (an ignore or a deliberate `!` -- in a repository, with
    git as the judge, per `_gitignore_addresses`) needs no append, and a
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
    if any(not _gitignore_addresses(target_dir, text, entry) for entry in entries):
        path = os.path.join(target_dir, ".gitignore")
        if not os.access(path, os.W_OK):
            raise SchemaError(
                f"cannot append to {path}: file is not writable -- make "
                ".gitignore writable, or remove it, and run init again"
            )


def _ensure_gitignore_entries(target_dir: str, entries: list[_GitignoreEntry]) -> None:
    """Make sure the project's `.gitignore` ignores each entry's path,
    creating `.gitignore` when the project has none.

    Append-only and idempotent: `.gitignore` is hand-authored and hand-commented
    like refdes-project.yaml, so nothing outside the appended blocks moves, and
    when some existing pattern already covers a path nothing is written for that
    path at all -- where "already covers" is git's answer inside a repository
    (`_gitignore_addresses`), so an author's negated glob is never out-ranked
    by a line init appends after it. The same question is asked when the file
    is created (R11-F3): git's answer for a not-yet-written path is the set of
    patterns that will match it once it exists -- the repository's higher
    `.gitignore` files and `core.excludesFile` -- and a project fully covered
    from above gets no file. Each block takes the file's own line
    ending (textio's `append_ending` rule), so a CRLF gitignore does not grow
    an LF island.
    """
    path = os.path.join(target_dir, ".gitignore")
    if not os.path.isfile(path):
        # The coverage question is asked here too, not only on the append
        # path below (R11-F3). It has a real answer for a file that does
        # not exist yet: `check-ignore --no-index` matches a path not on
        # disk, and the patterns covering a fresh project's files can live
        # OUTSIDE it -- a repository root's `.gitignore` above the project,
        # a global `core.excludesFile` -- and #328's own posture is that
        # inside a repository git is the judge. The literal fallback gets
        # the text the project has ("none", spelled empty): outside a
        # repository nothing is ignored and all entries are written, today
        # and after. When git covers everything, the answer is no file at
        # all -- an empty `.gitignore` announces nothing and saves nothing.
        missing = [
            entry for entry in entries if not _gitignore_addresses(target_dir, "", entry)
        ]
        if missing:
            textio.write_text(path, _joined_blocks(missing, textio.LF))
        return
    existing = textio.read_text(path)
    missing = [
        entry for entry in entries if not _gitignore_addresses(target_dir, existing, entry)
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
    _refuse_unwritable_gitignore(target_dir, wanted)

    os.makedirs(target_dir, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write(_init_yaml(standard, version, presets))

    if wants_vscode_entry:
        _write_vscode_settings(target_dir)
    _ensure_gitignore_entries(target_dir, wanted)

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
