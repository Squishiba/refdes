The browser editor's refdes row gained a `Navi` button. With no
selection it inserts a keyless Navi marker `<!--navi: text-->` with
`text` selected, so typing replaces it; with a selection it wraps it
(`<!--navi: your text-->`) and leaves the text selected. A selection
containing `--` or a newline is left untouched: a Navi is a one-line
HTML comment and `--` inside one is not safe. The marker is keyless on
purpose -- the next writable command mints its key, as always.
