`refdes serve` answers `GET /api/navis` (HEAD too, behind the same launch
token as every other `/api/` call) with the project's Navis: `navis` rows
in `refdes navis all` order -- active first, then archived -- each row the
published-site panel's shape plus the full `key` (`""` for a keyless
marker), and `counts` with the active/archived tallies. The archive store
is merged at request time, so an archive made on disk is visible on the
next GET. The GET writes nothing and answers on a `--no-write` server; a
Navi-free project answers 200 with empty rows and zero counts; any other
method is a 405.
