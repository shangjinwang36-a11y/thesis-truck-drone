# Robust dict and the two clocks

`cross_robust_violations` builds a dict only when a cross sortie has a tag. The append is `if tags: out[sid] = tags`. An empty dict therefore means the function returned, and no checked cross sortie had a tag. It does not by itself prove a cross existed.

On the published RC100 replay the same call recorded one cross, sid 56, `t1` to `t2`, parcels `p095` and `p057`, and `robust` was `{}`. That sortie was iterated and produced no tag. On the published C100 replay there is no cross sortie, so the empty dict means no cross entry was generated.

`handover_s` is 20. That is the U action for an abnormal handover. `air_service_s` is 60. That is the normal air SERVICE stage. The nominal replay had SERVICE durations of 60 and no U actions, because every sortie `handover` list was empty. Neither constant was edited.

# Call totals by stage

| Stage | Physical | Scenario | Per-call log |
|---|---:|---:|---|
| Proxy diagnostic | 42 | 0 | `PROXY_FALSE_NEGATIVE.json` rows |
| First pytest of the three tests | unknown | unknown | not instrumented; do not add to the rerun |
| Metered rerun of the same three tests | 6 | 4 | `TEST_NATIVE_LEDGER.json` |
| Round-1 X replay | envelope 5990; accepted hook 6202; scenario 212 inferred as the difference | inferred | absent |
| Round-2 X replay | 5995 | 224 | absent |
| Post-hoc nominal replay | 3 | 6 | one RC100 attempt plus the successful RC100 and C100 rerun |
| Fresh twelve arms | 11995 | 584 | `fresh_new/<case>/*_RAW.jsonl.gz` and receipts. Denied 2. Accepted 12579 |

Round-1 scenario 212 is not a stored ledger. It is accepted calls minus the physical envelope.
