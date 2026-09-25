- A file that already mixed line endings is no longer normalized by a command
  that writes it back. Every write-back picked one ending for the whole file —
  `"\r\n" if "\r\n" in text else "\n"` — so a single CRLF line anywhere re-typed
  every untouched line around it, and a one-line edit produced a whole-file diff
  that was nothing but line endings. `refdes id`, key minting, link/check/calc
  expansion, `follows` freezing, `former-ids confirm`, `revise`, and
  `calc rewrite` now leave every line that survived the edit holding the exact
  bytes that used to terminate it: an LF file stays LF, a CRLF file stays CRLF,
  and a mixed file keeps its mix. A line the edit *adds* takes the ending of the
  line it was inserted above, so a new `key:` line in an LF front matter does
  not arrive wearing CRLF.
- `refdes former-ids confirm` no longer converts a CRLF item file to LF. It read
  the file in text mode, which had already rewritten every CRLF before the
  line-ending style was chosen — so this one lost the endings on *every*
  platform, not only Windows.
- `refdes standard upgrade` no longer restyles `refdes-project.yaml` to bump one
  number, and `standard add-preset` / `remove-preset` no longer restyle it to
  add or remove one entry. All three read the config in text mode and wrote it
  back through a bare `open(..., "w")`, so a CRLF config came out all-LF on
  Linux and an LF one came out all-CRLF on Windows. The edit itself is still a
  span edit: nothing outside `presets: [...]` or the one `version:` number moves.
- Creating an item in the browser editor no longer gives it CRLF endings when
  the file it is appended to is otherwise LF but happens to contain one CRLF
  line. The appended block takes the ending of the line it is appended after.
- `refdes stub-tests` no longer appends CRLF into an LF `stub-tests.md` on
  Windows, and `refdes standard add-preset`/`remove-preset` no longer append
  CRLF into an LF config. Both wrote the new lines in text mode, so the platform
  translated them a second time.
- The tool's own committed state files — `.refdes/ids.yaml`, the citation
  lockfile, captured-history objects and events, and `.refdes/schema.json` — are
  now written with the same bytes on every platform. They are regenerated whole
  and are meant to be committed, so their line endings must not depend on which
  machine last ran the command that wrote them; on Windows they were coming out
  CRLF where Linux produced LF. Baselines, seals, and the board manifest already
  behaved this way. Site HTML and the site manifest are unchanged: they are
  build output, and a Windows build is still expected to produce Windows line
  endings there.
