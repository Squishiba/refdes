- Calc blocks accept the Calcpad-style unit spelling: the unit a result is
  presented in goes after the expression — `P_mW = V_out * I_load | mW` —
  converting and asserting the dimension exactly like the old
  `P_mW : mW = V_out * I_load` did. Whitespace around `|` is optional; the
  unit accepts compounds (`W/in^2`), aliases, and house units. Writing both
  spellings on one line is an error naming both. Prose references gain the
  same form: `{{P_diss | mW}}` presents that value converted to `mW`, and a
  unit of the wrong dimension is a build error at the reference rather than a
  silent fallback. The old `: unit` spelling is retired — see
  `calc-colon-units-retired.breaking` and `refdes calc-rewrite`.
