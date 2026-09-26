- `refdes former-ids propose` printed an empty old title for every candidate it
  paired by surrogate key — the form it normally takes, since keys are minted
  automatically. A current baseline is keyed by *display* id and carries the
  surrogate inside a `key:` field, so the lookup by surrogate found nothing and
  the one field that tells you which item you are about to re-identify came
  back blank. The record is now resolved in either baseline storage shape
  (`refdes keys adopt` flips the map to key-keyed), and the candidate line
  reads `CAN_00 (requirement 'The bus shall recover...') -> REQ-CAN-001 (...)`
  again.
