# M47 schedule-closed detour

M46 remains a DROP. Sealed M46 outputs were not overwritten. This file keeps the first negative round and the second round.

## Round 1, kept

A proxy veto plus a one-ground-parcel gate emitted nothing. Six fresh X nominals matched sealed M46 exactly, including `FUNNEL_CROSS`. See `FRESH_X_SIXMAP.json`.

## Why the gate was too narrow

A separate diagnostic paid at most eight physical evaluations per sealed champion and did not draw scenarios (`PROXY_FALSE_NEGATIVE.json`, 42 physical calls).

- RC100: deleting a recovery stop that has no ground parcel is feasible, inside hard H, robust-clean, and about +22.5 on cost and original J. The old gate required exactly one ground parcel, so it never built this plan. The proxy was already positive.
- C100: absorbing the stop's single parcel `p026` is robust-clean and about +0.8 on original J, +3.4 on the charged scenario score. The geometric proxy scored it at -2.3. That veto was a false negative.
- Swapping two terminal recoveries stays out. Those plans were physically feasible and lost about 13 to 46 on J.

The proxy still ranks. It no longer vetoes. At most two candidates per parent are paid. Original physical, J, scenario, H, robust and CAS gates are unchanged. Keeping parent air parcels is only this move's shape, not a global ban and not a new objective.

## Tests

`test_schedule_closed_detour.py`: 3 passed in about 2.3 s.

- RC100 emits a complete zero-parcel cross. One physical evaluation, J gain above 20, then a separate scenario ledger also gains above 20.
- C100 emits the proxy-negative `p026` plan. Charged physical evaluation, original J gain above 0.5.
- Energy: `reserve_fraction=0.99` makes the same RC100 plan `ENERGY_INFEASIBLE`.
- Timing: horizon 100 s returns `H_EXCEEDED`.
- Custody: a feasible cross that carries the receiver's own customer is tagged `GROUND`. The operator does not offer that pattern.

## X replay on sealed K1 S

This is not a fresh S/X experiment. S is the sealed K1 nominal. Its preparation cost was already paid in that study and is not bought again. Reference H is that S plan's `H_s`. X still spends its own 1000 physical evaluations and its own scenario ledger.

| Map | X cost | vs sealed M46 X | Air | Cross sorties | Cross customers | Physical | Scenario | CPU s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C50 | 121.10960906755213 | 0 | 45 | 0 | 0 | 995 | 40 | 9.4 |
| R50 | 384.5596607673594 | 0 | 43 | 0 | 0 | 1000 | 34 | 10.3 |
| RC50 | 303.2494243777115 | 0 | 45 | 0 | 0 | 1000 | 28 | 8.9 |
| C100 | 321.9461658588226 | -29.623 | 82 | 0 | 0 | 1000 | 52 | 34.8 |
| R100 | 729.5020961963194 | 0 | 76 | 0 | 0 | 1000 | 28 | 38.4 |
| RC100 | 542.4744922191281 | -22.205 | 76 | 1 | 2 | 1000 | 42 | 38.1 |

RC50 stays at 45 air parcels and the sealed M46 cost. S was not re-solved, so S is not weakened by this replay.

RC100 publishes one cross sortie, `t1` to `t2`, carrying two parcels. Nominal cost falls by 22.205. Hard H remains the sealed S horizon 5911.7 s; the plan finishes at 5695.0 s. Verified.

C100 publishes no cross sortie. Air rises from 67 to 82 and nominal cost falls by 29.623. The detour move is accepted inside the search and later same-truck moves remove the cross while keeping the extra air. That is a coverage and cost change, not a surviving cross.

No actual world was run. Seeds 4001–4030 were not read. No 180-seed batch.

## Diff

`M46_TO_M47_DIFF.json`: 145 identical core files, two algorithm files (`complete_joint.py` changed, `schedule_closed_exchange.py` added). The freeze file hash changes because it records those two files. Everything else in the core is the imported M46 baseline.
