- The id-reuse guarantee is now stated with the condition it actually has.
  `docs/design/keys.md` §8 said a reused display id cannot capture an old
  internal reference and that "risk is gone entirely"; it is gone once the
  references carry keys, which is a state a project reaches on its first
  *writable* load, because that is what writes the keys and the
  `DISPLAY-ID@key` composites. Before that, a reference still in bare form
  resolves by display id — and `--no-write` suppresses both minting and
  expansion — so on a project that has never been writable-loaded, deleting
  an item and creating an unrelated one under the same display id
  re-attaches every bare reference to the new item, silently: `0 errors`,
  exit 0. Verified by running it (`in-prog-logs/identity-remedy-wording.txt`
  §F4.1), along with the contrast that one `refdes check` on the same project
  first turns the same break into four `points at key ... which no item
  declares` errors. `docs/ids.md` said the same thing twice — "closing this
  fully needs identity that survives an id being retyped, which is what
  surrogate keys provide" and the bare-reference clause in its surrogate-keys
  list — and both now carry the condition. Nothing else changed: no
  behaviour, no diagnostic, no message.
