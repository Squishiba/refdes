- **`refdes check --refresh` now fails when a pinned citation cannot be
  re-fetched.** It reported the failure as a warning and exited `0`, so a CI
  drift guard went green through a network outage — having checked nothing — and
  green on a datasheet the vendor had deleted, while `docs/cli-reference.md`
  promised "Exits non-zero on drift, same as on any other error". No bytes
  arrived, so there is nothing to compare the pin against: that is not a drift
  finding, but it is a check that did not happen, and the run now says so and
  exits `1` —

  ```
  ERROR   <project> — could not refresh https://…/tps62913.pdf: <urlopen error [Errno 111] Connection refused> -- upstream drift was NOT verified for this citation (no bytes arrived, so there is nothing to compare the pin against)
  ERROR   <project> — 1 pinned citation could not be refreshed, so upstream drift was NOT verified for it -- the run cannot claim to have checked it. Fix the network or the urls, or pass --allow-unreachable to treat an unreachable source as a warning and let the exit code reflect only real findings (you then get no guarantee that every pinned source was checked at all)
  ```

  **If your CI runs `check --refresh`, this is a change you have to make
  deliberately.** Either accept the new exit code — a drift guard that passes
  through an outage is not a drift guard — or pass the new
  **`check --allow-unreachable`**, which reports each unreachable citation as a
  warning and lets the exit code reflect only real findings. What that flag gives
  up is stated in its `--help` and in the docs: whatever could not be fetched is
  left unverified, so a deleted datasheet passes exactly as a dead network does.
  Drift findings and ordinary project errors still exit non-zero under it — it
  changes the severity of "could not check", never the verdict on "checked, and
  it differs".

  A partial outage is not a special case: every url is still attempted, the ones
  that answered are compared and reported as usual, and the unreachable ones
  account for the error count. An HTTP error status (`404`, `500`) is classified
  as unreachable rather than as a finding, which is what the code already did
  with it and what `refdes fetch` does — a failed citation, never a changed
  document. A redirect is not unreachable: `fetch_bytes` follows 3xx inside
  `urlopen`, so a hop that lands on a 200 is compared on its final bytes, as
  `fetch` pins it.