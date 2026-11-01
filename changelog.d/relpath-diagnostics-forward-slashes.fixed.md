- **Three diagnostics that printed Windows backslashes in a
  project-relative path now print `/`.** The cache-missing sentence
  (`local copy of <url> is missing at .refdes/copies/<sha>.pdf`), the
  citation case-mismatch warning (`... differs in case from the file on
  disk (docs/SCH.pdf); ...`), and the baseline-conflict remedy from
  stamping (`... delete .refdes/baselines/<name>.yaml first ...`) each
  interpolated the raw `os.path.relpath` result, which on Windows spells
  its separators `\` -- so the printed path read differently per
  platform and was not pasteable as quoted. Conditions, sentences, and
  exit codes are unchanged; only the separator spelling of the path in
  those three messages.
