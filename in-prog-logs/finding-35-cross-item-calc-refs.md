# finding 35 -- cross-item calc references (docs/design/backlog.md)

Status: FINISHED (locally committed on ao/refdes-117/root; not pushed).

## Chunk 1 (reference syntax, composite expansion, dependency-order eval,
loud errors, import refusal)
Already landed before this session: cabd9e1. Not redone.

## Chunk 2 -- content hash, HASH_FORMAT 3 -> 4 (8d0922b)
- Payload for an item with references gains `calc_refs`
  ([key token, name, full-precision value signature]) and hashes its body with
  each reference's target replaced by the key token, so bare -> composite
  expansion and display-half refresh cannot churn. Item with no reference:
  payload identical to format 3 (tested: payload equality + hash equality).
- Value signature is `calc.value_signature` (repr of magnitude + units for
  nom/lo/hi), NOT the sigfig text: a sub-display-precision upstream change still
  registers (tested).
- Format 3 stays reconstructible (`hash_payload_builder(project, 3)`);
  keys.hash_in_format and seal._matches_sealed_hash now range over every earlier
  format instead of the hard-coded (1, 2)/(HASH, 2, 1).
- Decision noted: refs enter the hash only when the body is hashed
  (body on_change == invalidate) -- the calc block is body text, so a body the
  type ignores makes its arithmetic ignored too. Not separately asked.
- Finding 26 (source()) is not in this tree; when it lands it should reuse
  format 4, not bump again (comment at HASH_FORMAT says so).
- Difficulty: my own edit scripts mangled `\n` via the shell heredoc and
  truncated build.py once; restored from git and redone. Tests use in-place
  edits (`_edit`) because rewriting an item file wholesale drops its key.

## Chunk 3 -- baseline diff line (578aa85)
- Baseline entries gain optional `calc_refs {targetkey.name: "12 V (lo … hi)"}`;
  DiffResult.moved_refs; `refdes audit` prints
  `DEC-B -- referenced DEC-PWR-001.V_in: old -> new` (checked via the CLI).
- Silent for baselines without calc_refs; a newly added reference is the item's
  own edit and isn't listed; upstream display rename claims no move.

## Chunk 4 -- docs
docs/math.md, docs/lifecycle.md, docs/change-tracking.md,
changelog.d/calc-cross-item-refs-hash.changed.md.

Known gap (as decided in the finding): references are invisible to the
workspace lint / backlinks / coverage; imports refused.
