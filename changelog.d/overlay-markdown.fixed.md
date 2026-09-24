`parse_markdown_file` opened its file directly instead of going through
`read_source`, so `Project.source_overlay` was invisible to `.md` files:
a candidate edit to a Markdown file was validated against the OLD bytes
(the edit service's delta gate saw nothing the overlay changed), and a
load whose overlay named a file that did not exist yet failed outright.
Markdown sources now read through `read_source` like list files, and
`read_source` normalizes CRLF in overlay text so a candidate matches what
the text-mode disk read would show. Found by the Slice 3 create path,
which validates a new `.md` file exactly this way.
