- `refdes serve` now treats project images as build inputs. Every file under a
  directory your `site.assets:` list declares joins the watched set and the
  content revision alongside the config files, item and page sources,
  `.refdes/` state, and imported artifacts — the whole directory, not the
  subset some document currently references, because a bare `<img src>` is a
  query over those directories: adding a file can retire a does-not-exist or
  ambiguous-name build error and deleting one can raise it. Adding, replacing,
  or deleting such a file therefore moves the revision and rebuilds the
  preview, where before it did neither and an author would save and see
  nothing. Files outside every declared asset directory are still not inputs,
  a touch that changes no bytes is still not a change, and the per-tick cost
  stays a `(mtime, size)` stat — content is hashed only once that differs.
  Declared directories that do not exist are skipped, as the build skips them.
  Decided by Jared 2026-09-25 (`docs/design/editor-image-upload.md` 15.1).
