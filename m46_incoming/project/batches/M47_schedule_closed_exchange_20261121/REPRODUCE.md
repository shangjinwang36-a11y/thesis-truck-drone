# Reproduce the M47 checks

From an empty working directory, with this repository and the unpacked attachment
available as siblings of `M47_schedule_closed_exchange_20261121`:

```text
python3 -m pytest -q M47_schedule_closed_exchange_20261121/test_schedule_closed_detour.py
python3 M47_schedule_closed_exchange_20261121/diagnose_proxy_false_negative.py
```

The pytest file pays a few native physical evaluations and two scenario scores.
Those calls are diagnostic. They do not write a fresh nominal directory.

`diagnose_proxy_false_negative.py` pays at most eight physical evaluations per
sealed X champion and writes `PROXY_FALSE_NEGATIVE.json`. It does not draw the
fixed training scenarios.

The six-map X replay is not a fresh S solve. It adopts the sealed K1 S nominal
as the reference H and the same-truck baseline. S's historical preparation is
the sealed K1 run, not a new 1000-evaluation S search. Outputs are under
`replay_x/` and `REPLAY_X_SIXMAP.json`.

`M46_TO_M47_DIFF.json` is the file-hash manifest against the sealed M46 core.
The algorithm delta is `schedule_closed_exchange.py` plus the admission lines
in `complete_joint.py`. Every other core file is the imported baseline.
