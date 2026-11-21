# M47 audit bundle

Original sealed M46 files were not modified. This bundle is a copy of the M47 stage plus the two algorithm files.

Run the nominal audit from this directory after unpacking beside the K1 and M44 trees it already references:

`python3 audit_nominal.py`

That script is the M46 auditor with one path change: the core directory name is `M47_schedule_closed_exchange_core_20261121`. It checks plan identity, hard H, replay, invoice, and the 1000/200 caps.

`ACCOUNTING.json` lists every measured native call and every unknown. Round-1 and round-2 X replays have no per-call log. The fresh twelve arms do: `fresh_new/<case>/<arm>_RAW.jsonl.gz` and `<arm>_live/receipts.jsonl`.

Nominal cross sorties are not actual SERVICE. No actual batch has been started. `BOUNDED_ACTUAL_PREREGISTRATION.json` is a draft waiting for the recorded dev-world files.
