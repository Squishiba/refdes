- Three user-facing messages no longer leak a Python `repr`. An out-of-range
  enum now reads `status: 'picked' is not one of candidate, selected,
  rejected, obsolete.` instead of a bracketed list repr, and a link pointed at
  the wrong type reads `constrained_by may point at bound, but REQ-002 is a
  requirement` — comma-joined, and naming the target's bare display id rather
  than the `DISPLAY-ID@key` composite the file actually stores. The surrogate
  key is an implementation detail of the file, not something to read in a
  sentence meant for a human.
