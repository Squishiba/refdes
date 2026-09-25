"""Reading and writing a source file without disturbing its line endings.

Every tool that writes a source file back -- `refdes id` allocating an id,
key minting, link/check/calc expansion, `former-ids confirm`, `revise`,
`calc rewrite`, the browser editor's append -- does the same three steps: read
the file, work on a list of lines, write the list back. Text mode is wrong for
the first and third of those. A text-mode read turns every CRLF into LF before
the caller can look, so the original style is already gone by the time anyone
asks what style the file was; a text-mode write then hands the whole file to
the platform's newline translation, which on Windows rewrites every line of an
LF file to CRLF. One `refdes id` on a two-line edit is enough to reformat a
file nobody asked to reformat, and the diff that follows is all line endings
and no content.

`SourceText` is the one place that knows how to avoid that. It reads with
`newline=""` so the terminators survive, hands back bare lines through
`.lines` (what every caller's line-oriented edit expects), and re-joins with
`.render()` -- which puts each original line's *own* terminator back on that
same line, so a file that was LF stays LF, a file that was CRLF stays CRLF, and
a file that was already mixed stays mixed with only the lines an edit actually
touched changing. Byte-for-byte that is the fidelity contract
docs/design/browser-editor.md states for write-back, and it holds here for the
ordinary load-time writes too, not just the editor's.

The one thing `.render()` has to decide is the terminator for a line that did
not exist before: an inserted `key: ...` in a file whose front matter is LF
must not arrive wearing CRLF. It takes the ending of the line it was inserted
above -- the line whose slot it now occupies, and the block it joined, since
every insertion here puts a new line at the top of an item and the item's own
keys are below. Only an append at the end of a file, with nothing below to ask,
falls back to the line above; and a file that ended without a break still ends
without one.

`write_text` is the matching write: `newline=""`, so whatever terminators the
text already carries reach the file unchanged. It is the counterpart to
`read_text` and to the `open(..., "w", ..., newline="")` idiom these call sites
already use -- the reason it is named here is that the *unsafe* form
(`open(..., "w", encoding="utf-8")` with no `newline=`) is what this module
exists to replace, and having one spelling of the safe form is what keeps the
next one from drifting back.
"""

from __future__ import annotations

import difflib

LF = "\n"
CRLF = "\r\n"

# Every character `str.splitlines()` treats as a line break. The list matters:
# `splitlines()` splits on all of them, so a terminator extractor that only
# knew about "\n" and "\r\n" would disagree with it about where the lines are,
# and `.render()` would then attach terminators to the wrong lines.
_BREAKS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _split_terminator(line: str) -> tuple[str, str]:
    """`(line without its terminator, the terminator)`.

    Mirrors `str.splitlines(keepends=True)`, which always yields exactly as
    many pieces as `str.splitlines()` -- that pairing is what lets `.render()`
    put line *i*'s terminator back on line *i* without guessing.
    """
    i = len(line)
    while i > 0 and line[i - 1] in _BREAKS:
        i -= 1
    return line[:i], line[i:]


class SourceText:
    """One source file's text, with its per-line terminators remembered.

    Not a mutable buffer: `.lines` hands out a fresh list of bare lines and
    `.render()` takes one back, so a caller cannot edit the text in place
    behind the terminators' back. The alternative -- keeping the file's text
    around as a plain string and re-deriving its style on write -- is what
    loses a mixed file's layout.
    """

    __slots__ = ("_text", "_lines", "_ends", "_dominant")

    def __init__(self, text: str) -> None:
        self._text = text
        pieces = text.splitlines(keepends=True)
        split = [_split_terminator(piece) for piece in pieces]
        self._lines = [body for body, _ in split]
        self._ends = [end for _, end in split]
        self._dominant = _dominant(self._ends)

    @classmethod
    def of(cls, path: str) -> SourceText:
        """Read `path` as a source file, terminators intact."""
        return cls(read_text(path))

    def __len__(self) -> int:
        return len(self._lines)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"SourceText({len(self._lines)} lines, dominant {self._dominant!r})"

    @property
    def text(self) -> str:
        """The text exactly as read, terminators and all."""
        return self._text

    @property
    def lines(self) -> list[str]:
        """The lines, without terminators -- what `text.splitlines()` gives.

        A fresh list every call: callers splice, sort, and index into it, and
        a shared list would let one file's edit show up in another's.
        """
        return list(self._lines)

    @property
    def dominant(self) -> str:
        """The ending most of this file's lines use, `LF` when it cannot tell.

        Only ever consulted for a line with no neighbour to inherit from, and
        for a file that is empty. A tie goes to LF, matching `.gitattributes`:
        an ambiguous file is a file nobody has expressed an opinion about yet,
        and LF is the repository's stated default.
        """
        return self._dominant

    def ending_at(self, index: int) -> str:
        """The ending a line inserted at `index` should wear.

        The public door to the same neighbour rule `.render()` applies
        internally, for a caller splicing its own text into the middle of a
        file. Prefer `append_ending` for a block going on the end, which is
        the only shape the codebase actually appends.
        """
        return self._neighbour_end(index)

    def last_ending(self) -> str:
        """The last ending in the file that is not `""`, else its dominant one.

        Always a real ending, so it is safe to break a line with. `append_ending`
        is this, wrapped for a caller holding plain text.
        """
        for i in range(len(self._ends) - 1, -1, -1):
            if self._ends[i]:
                return self._ends[i]
        return self._dominant

    def render(self, lines: list[str]) -> str:
        """Re-join `lines` into file text, preserving untouched terminators.

        `lines` is the edited list a caller built from `.lines`; the result is
        what should go back to disk. Lines that came through unchanged get
        their original terminator back, whatever it was -- so an LF file stays
        LF and a mixed file keeps its mix. Lines that are new (inserted) or
        rewritten take the ending of the original line they sit next to.
        """
        if lines == self._lines:
            return self._text
        out: list[tuple[str, str]] = []
        # autojunk=False is required, not a tuning knob: item files are full of
        # repeated lines (`- type: requirement`, `    body: |`), and difflib's
        # "popular element" heuristic would classify those as junk and produce
        # an alignment that moves terminators between unrelated lines.
        matcher = difflib.SequenceMatcher(a=self._lines, b=lines, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                out.extend(zip(lines[j1:j2], self._ends[i1:i2]))
                continue
            if tag == "delete":
                continue
            # insert (i1 == i2) or replace (i1 < i2). A replacement inherits
            # from the line it replaces, so an edited line keeps its own
            # ending; an insertion has no such line and asks its neighbour.
            for offset, j in enumerate(range(j1, j2)):
                if tag == "replace" and i1 < i2:
                    end = self._ends[min(i1 + offset, i2 - 1)]
                else:
                    end = self._neighbour_end(i1)
                out.append((lines[j], end))
        return "".join(
            line + end for line, end in _break_unterminated(out, self._dominant)
        )

    def _neighbour_end(self, i1: int) -> str:
        """The ending a line inserted at `i1` should wear.

        Asked of the line the insertion pushes down first, and only then of the
        line above. That order is the whole rule: an inserted line lands in the
        slot the line below it used to terminate, so it should wear that line's
        ending -- which is also the block it joins, since every insertion here
        puts a new `id:`/`key:`/link line at the *top* of an item and the item's
        own keys are below it. Falling back to the line above is for an append
        at the end of a file, where there is nothing below to ask.

        An empty ending is skipped except when appending past the last line,
        where it is the answer: a file that ended without a break should still
        end without one after a line is added to it.
        """
        if i1 >= len(self._ends):
            return self._ends[-1] if self._ends else self._dominant
        for i in (i1, i1 - 1, i1 + 1, i1 - 2):
            if 0 <= i < len(self._ends) and self._ends[i]:
                return self._ends[i]
        return self._dominant


def _break_unterminated(
    out: list[tuple[str, str]], dominant: str
) -> list[tuple[str, str]]:
    """Give every line but the last a terminator, whatever the diff handed it.

    An empty ending is only ever correct on the final line -- it is how
    `splitlines(keepends=True)` spells "this file has no trailing newline". Once
    a line is no longer last, its empty ending has to become a real break or
    two lines run together: appending to a file whose last line had no
    terminator is exactly this case. The replacement is the nearest ending that
    is real, so an unterminated tail in an otherwise-CRLF file picks up CRLF
    rather than being normalized to LF.
    """
    fixed = list(out)
    for i, (line, end) in enumerate(fixed):
        if end or i == len(fixed) - 1:
            continue
        replacement = next(
            (fixed[j][1] for j in range(i + 1, len(fixed)) if fixed[j][1]),
            None,
        ) or next(
            (fixed[j][1] for j in range(i - 1, -1, -1) if fixed[j][1]),
            dominant,
        )
        fixed[i] = (line, replacement)
    return fixed


def _dominant(ends: list[str]) -> str:
    crlf = sum(1 for end in ends if end == CRLF)
    return CRLF if crlf * 2 > len(ends) else LF


def append_ending(text: str) -> str:
    """The ending a block appended to `text` should wear.

    The appending twin of `SourceText.render`, for the two callers that build
    a block of new lines and add it to the end of a file rather than editing a
    line list they got back. It asks the *last line that has an ending*, not
    the file at large: "does this file mention CRLF anywhere" gave a new item
    CRLF endings in a file whose tail was LF, which is the same whole-file
    mistake `render` was written to stop making.

    Always a real ending, never `""` -- unlike `render`, this is not deciding
    where a file's last line ends, it is deciding what to break an appended
    block's lines with. Both callers supply the break in front of the block
    themselves (they must, when the file had no final break), so an empty
    answer here would run the block into the line above it.
    """
    return SourceText(text).last_ending()


def read_text(path: str) -> str:
    """Read `path` as UTF-8 text with its line terminators intact.

    `newline=""` is the whole point: it disables both halves of text mode's
    newline handling, so no CRLF is folded to LF on the way in and nothing is
    translated on the way out. A caller that only wants to parse may use text
    mode instead (`parse.read_source` does, and should -- normalizing for the
    parser is right, losing the author's layout is not).
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path: str, text: str) -> None:
    """Write `text` to `path` verbatim, terminators included."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
