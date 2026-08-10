---
id: DEC-PWR-001
type: decision
title: 3V3 rail regulator topology
status: accepted
date: 2026-03-14
owner: J. Bin
tags: [power, thermal]
satisfies: [REQ-PWR-002, REQ-PWR-003]
constrains: [CON-THM-001]
options:
  - name: LDO (TPS7A4700)
    verdict: rejected
    because: >
      Dissipates 10.4 W at full load from a 12 V input. Roughly seventy times the
      thermal budget in CON-THM-001. Not close.
  - name: Synchronous buck (TPS62913)
    verdict: chosen
    because: >
      93 % efficiency at half load, low output ripple with a second-stage LC, and
      the dissipation lands within the enclosure budget.
  - name: Buck with LDO post-regulation
    verdict: rejected
    because: >
      Adds $1.80 of BOM and 0.4 W of extra dissipation to solve a ripple problem
      that REQ-PWR-002 does not actually have once the second-stage LC is fitted.
checks:
  - value: eff
    against: CON-THM-002
  - value: P_dens
    against: CON-THM-001
---

The 3V3 rail draws up to 1.2 A from a 9–36 V input, in a sealed enclosure with no
airflow. REQ-PWR-002 sets the load and ripple; CON-THM-001 sets what we are allowed
to dissipate getting there.

## Working

```calc
V_in             = 12 V ± 5%            # nominal supply, 5% tolerance
V_out            = 3.3 V
I_load           = 1.2 A
eff              = 0.93                 # TPS62913 datasheet, half load
P_out   : W      = V_out * I_load
P_diss  : W      = P_out * (1/eff - 1)  # converter loss at full load
A_board          = 1.4 inch * 0.9 inch  # area allocated to the power stage
P_dens  : W/in^2 = P_diss / A_board
```

The converter loses {{P_diss}} at full load, spread over {{A_board}} of board, so
the power stage runs at {{P_dens}}.

That is where this decision is currently in trouble: CON-THM-001 allows
0.15 W/in², and the check below fails. The options are to widen the power stage
allocation, improve efficiency, or renegotiate the enclosure spec — none of which
have been decided yet.

For comparison, the rejected LDO option dissipates `V_in - V_out` across the pass
element at the full load current, which is the 10.4 W figure quoted above.
