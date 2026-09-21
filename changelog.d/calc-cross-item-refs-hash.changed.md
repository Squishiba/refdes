A cross-item calc reference's resolved value (`V_in = DEC-PWR-001.V_in`) now
enters the referring item's content hash (`hash_format` 4): when the upstream
value or tolerance moves, the dependent shows as `changed` in the baseline diff
even though its own text is untouched, and `refdes audit` names the moved
reference with its old and new value (`referenced DEC-PWR-001.V_in: 12 V (…) ->
11.4 V (…)`). Baselines now record each item's referenced values (`calc_refs`)
for that line. Items with no reference hash exactly as before, an upstream
display-id rename or the on-disk bare → composite expansion does not churn, and
format-3 baselines carry forward as usual. See docs/math.md.
