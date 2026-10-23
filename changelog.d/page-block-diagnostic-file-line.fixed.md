- A `refdes check` diagnostic for a page block (`{{index}}`, `{{tree}}`,
  `{{compare}}`, `{{calcblock}}`, `{{cascade}}`) reported a line
  counted inside the page body, which has the front matter already stripped,
  so a page with front matter named a line a few lines early — front matter
  on lines 1-4 with the bad directive on file line 8 printed `:3`, pointing
  at an `order:` key. Block diagnostics now name the line in the file, front
  matter included, like every other page diagnostic. A page with no front
  matter is unchanged.
