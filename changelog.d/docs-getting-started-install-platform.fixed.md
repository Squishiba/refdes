- Docs: `docs/getting-started.md`'s Install section no longer leads with a
  Windows-only command. It gave `./.venv/Scripts/python.exe -m pip install -e .`
  in the first code block — the first command anyone following the guide runs —
  and told a macOS/Linux reader their interpreter is `.venv/bin/python` only in
  the sentence after it, with the same Windows path repeated in the fallback
  line below. Both are now shown as two labelled blocks (Linux and macOS,
  Windows PowerShell) under a line saying the venv interpreter path differs by
  platform, and the fallback names both: `./.venv/bin/python -m refdes.cli` and
  `.\.venv\Scripts\python.exe -m refdes.cli`. Nothing else on the page changed;
  the other fenced blocks, the documented `refdes init` output and the build
  output are untouched.
