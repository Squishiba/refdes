- **A field name that is a confident misspelling of a declared field is now a
  build error.** `partnum: TPS123` written where `part_number:` belonged used to
  cost a warning: `unknown field 'partnum' on component. Did you mean
  'part_number'?`, exit 0, site written -- and because `part_number` is what
  feeds the parts index, the part silently dropped out of the one report the
  field exists to feed, with no error anywhere to explain where it went. The
  did-you-mean was the good part and is kept; what changed is the severity. The
  same reasoning already governed a misspelled *link* verb -- `sattisfies:` for
  `satisfies:` has always failed the build, because a dropped traceability edge
  is not something a warning should be trusted to catch -- and a misspelled
  field is that same loss one level down: not a field you wanted that the schema
  lacks, but the field you wanted with its value going nowhere. The message now
  reads `unknown field 'partnum' on component -- did you mean the field
  'part_number'? A misspelled field name silently drops it instead of erroring.`
  and `refdes check` and `refdes build` both exit 1 on it. The value is still
  loaded under the key as authored, exactly as the link-verb error has always
  done it, so the file you are fixing still holds what you wrote. **Only a
  confident match changes severity.** A key with nothing close to it -- within
  the same 0.6 similarity the suggestion already used, unchanged -- has no typo
  interpretation: forward-compatible metadata, a field a future schema version
  will declare, deliberate extra data. That stays a warning with its wording and
  its hint exactly as they were, and the build stays green, which is the same
  posture the served API takes toward an unrecognized query parameter. A
  suggestion pointing at something that is not a declared field of the type --
  `boardd:` near `board:` -- likewise stays a warning. **What you have to do:**
  if your project has a field name that is one or two characters off a declared
  one, its build now fails until you fix the spelling; and check what that field
  was supposed to say, because the value has been sitting under the wrong key
  and out of whatever report it feeds. A project that only carries genuinely
  novel fields sees no change at all.
