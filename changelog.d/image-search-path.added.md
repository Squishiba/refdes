- An `<img src>` written as a bare filename — `![curve](curve.png)`, no `/` in
  it — that does not resolve beside its own source file is now looked up in the
  directories your `site.assets:` list already declares, `#include <foo.h>`
  style: only those directories, never a walk of the project tree. A `src` that
  resolves relative to its source file still wins exactly as before, so no
  existing document changes; a multi-segment path that fails stays a plain
  does-not-exist error. A bare name found in more than one declared directory
  is a **build error** at the reference site naming every candidate — there is
  no first-match tie-breaker — and a name found nowhere is an error naming the
  directories that were searched. Two same-named files nobody references are
  not an error. See [images and other local
  files](docs/markdown.md#a-bare-filename-found-on-the-search-path).
