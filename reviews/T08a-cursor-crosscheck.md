# T08a cross-check (second reviewer)

Independent review of the 13 commits in `uploads/codex-commits-5eab1b2..91e755d.patch` (author SHAs `a5c8968..91e755d`), applied on top of frozen baseline `5eab1b2`. The upload is 13 commits, not 16. Local SHAs differ from the author's because the series was applied with `git am --ignore-whitespace` onto a CRLF tree. Logic matches the patch. `recovery.py` and `simulate.py` were then restored to CRLF so `test_preserve_crlf` matches the author's byte check. That restore has no textual diff under `--ignore-cr-at-eol`.

This review does not take the author's report as evidence. Nominal numbers below were rebuilt here. Episode numbers below are seed 101 on C50 and R50 only. Seeds 3001–3030 and 4001–4030 were not run.

## Verdicts

| # | Author SHA | Local SHA | Claim | Verdict |
|---|---|---|---|---|
| 1 | `a5c8968` | `4f2554b` | Emergency finish may move an in-flight rendezvous onto the launch truck | bug |
| 2 | `560c58d` | `a0db06e` | Channel check sees a launch still in progress across the cutoff | OK |
| 3 | `3bcdd10` | `d525836` | Emergency finish keeps `E_min` and flags an unpriced finish | bug |
| 4 | `3cd1d21` | `f7ecc65` | Every pending air delivery must be able to fly the parcel back | bug |
| 5 | `35cfe98` | `412f046` | Scenario-cache key includes launch and recovery points | OK |
| 6 | `222443f` | `61f90a0` | S, R, X share MILP top-k 10 and the energy screen is off | unfair |
| 7 | `17275c8` | `9a90a5a` | 1000 recovery evaluations is a hard cap, with no top-ups | unfair |
| 8 | `9beaa8d` | `68ca532` | Clear a handover parcel's old ground drop before a moved rendezvous | OK |
| 9 | `f3b537b` | `25af1b2` | Reachability prefilter is non-negative cruise energy only | OK |
| 10 | `0ee6b9f` | `93cff39` | Failed-delivery return includes wait hover, and a swap may pay for it | unfair |
| 11 | `1003ba5` | `829bf18` | Scenario-cache ground key includes route position | OK |
| 12 | `bece4c6` | `d78ccb5` | Energy-screen and top-k defaults are the same downstream | OK |
| 13 | `91e755d` | `525df76` | X's `S_SEED` catalog receives the energy-screen switch | OK |

`OK` means the claimed bug is real, the fix matches that claim, it does not add a material bug, and S and X take the same path. `bug` means the claim is only partly met, or the commit adds a defect. `unfair` means the change is strategy-blind in the source and still changes the S-versus-X comparison by constraining the flights X exists to use, or by ignoring a switch that only X's preset turned on.

## What actually moved the nominal plans

Rebuilding all six R11 nominals (budget 1000, same preset) under this tree reproduces the author's post-change nominal costs and cross counts to the printed digits: X cross sorties 8→3, and C50 / R50 / RC50 X costs become equal to S.

The same rebuild with only `failure_return_requirement` forced to return nothing, and `failure_return_violations` forced to return nothing, reproduces the frozen `5eab1b2` nominal costs and cross counts to the printed digits, including C50 X `176.4414` with 3 cross sorties and C100 X `424.7615` with 3. That ablation still has the new scenario-cache key, the ignored `x_recovery_wider` flag, top-k 10 for S, and the channel check. None of those move the published R11 nominals. The failure-return rule is the whole nominal change.

| Case | Frozen S | Frozen X (cross) | Head S | Head X (cross) | No-return-check X (cross) |
|---|---:|---:|---:|---:|---:|
| C50 | 193.9428 | 176.4414 (3) | 198.9240 | 198.9240 (0, adopted S, reason `scenario`) | 176.4414 (3) |
| R50 | 442.7403 | 442.7403 (0) | 459.4545 | 459.4545 (0) | 442.7403 (0) |
| RC50 | 338.8813 | 337.8328 (1) | 373.6622 | 373.6622 (0) | 337.8328 (1) |
| C100 | 454.6492 | 424.7615 (3) | 459.6195 | 451.1847 (1) | 424.7615 (3) |
| R100 | 740.5385 | 740.5385 (0) | 762.0043 | 754.6182 (1) | 740.5385 (0) |
| RC100 | 664.7327 | 655.6395 (1) | 696.4477 | 678.1657 (1) | 655.6395 (1) |

Equal-weight nominal `(X−S)/S` is −2.879% on the frozen plans and −0.905% on the rebuilt plans. That is the nominal slice of the author's −7.45% → −0.37% fair-cost move. The rest is recovery and stopped episodes, which this review only probed on seed 101.

## The −0.37% collapse

The collapse is a real change in the feasible set, and it is the wrong feasible set for this model.

Execution, as implemented and as written in `proj_r6/docs/02_模型与算法实现说明.md`, reveals the failure at the customer, hovers there only until that drone's cutoff (for the failed drone that cutoff is the failure instant), and then replans. Recovery may be at the failure customer (`package_light.json` sets `same_failed_customer_recovery_allowed`) or at any customer node. `land_and_wait` is on in the R11 preset. A landed wait and a landed recovery spend no hover energy and do not require `E_min` (`schedule.py` `stage_energy`, around the `WAIT`/`R` landed branch).

Commit 10 requires something else. At every not-yet-revealed service, energy at arrival must pay for a direct flight back to the **original** rendezvous, loaded hover for `max(0, rec_ready − arrival)` plus the recovery hover, and `E_min` unless the sortie is already marked `landed` (`schedule.py:619-642`). `rec_ready` is the truck/channel time with this drone's own planned arrival removed (`schedule.py:370-371`), which is the right quantity for "wait until that truck reaches the planned point" and the wrong quantity for "a replan may meet the drone at the customer where it failed".

Concrete case, frozen R50 S sortie 30, drone `d9`, truck `t5`, parcels `p043` then `p022`, rendezvous `c017`. The nominal drone reaches `c017` at 2029 s and waits 22 s empty. If `p043` fails at `c043`, the direct loaded return arrives at 1826 s and then hovers 224 s until `rec_ready` 2050.6 s. Post-swap energy at that service is 0.287 kWh; the rule demands 0.323 kWh, so the plan is `SWAP_CANNOT_FIX` even after a fresh battery at launch. The failure customer is a legal recovery point at distance 0. Dropping the wait, treating the return as landed, or recovering at the nearest customer all fit in the same 0.287 kWh. The same pattern is every frozen rejection: R50, RC50, R100, and RC100, S and X alike, all on same-truck services, all still feasible if the wait hover is not charged. C50 and C100 frozen plans stay feasible. Their cross sorties are the tight ones (C50 X minimum slack 0.009 kWh on a 394 s wait), so the rule deletes stepping-stones around them.

The frozen C50 X plan is still feasible under the new rule. Re-evaluating it inserts one swap on `t5` and prices it at 178.13 rather than the stored 176.44. Its two-scenario score, 199.90, still beats the frozen S plan's 207.81, so the scenario gate would keep it. The rebuilt search does not return it; it publishes S at 198.92. The rule does not make that cross plan illegal. It makes the nominal heuristic miss it.

Seed 101, same hidden failures, fair cost `(X−S)/S_nominal`:

| Run | C50 S | C50 X | C50 gap | R50 S | R50 X | R50 gap |
|---|---:|---:|---:|---:|---:|---:|
| Baseline `5eab1b2`, frozen nominal, old budget | 242.83 | 210.03 | −16.9% | 467.78 | 445.31 | −5.1% |
| This tree, return check off, frozen nominal, hard cap | 250.53 | 210.26 | −20.8% | 489.68 | 445.31 | −10.0% |
| This tree, return check on, rebuilt nominal, hard cap | 255.55 | 224.53 | −15.6% | 513.40 | 518.86 | +1.2% |

On these two seeds the hard cap does not remove X's advantage. R50 X is byte-identical to baseline (445.3074) when only the cap changes; C50 X moves by 0.22. Turning the return check on, which also replaces the nominal, flips R50 from X cheaper to X more expensive. Both episodes still complete. This is two seeds, not the 120-pair −0.37%. It is enough to separate the two mechanisms the author left entangled: the return rule moves the nominals and can reverse a seed; the cap, on these seeds, trims evaluations (R50 X 2153→2000) without moving X's cost.

The author's larger stop count is the same rule meeting the init sub-cap. A replan that finds no feasible suffix in the first 100 evaluations stops, and the other 900 are never started (`simulate.py:930-931` and the `opt is None` branch around `simulate.py:984-993`). Baseline, on that event, added `rescue_evals=main_limit` (1000) to the init budget. The new feasible set is smaller, so init fails more often, and the cap then discards the rest of the 1000. That interaction can produce `STOPPED_NO_FEASIBLE_SUFFIX` / `INITIAL_RECOVERY_FAILED` with `stage=SERVICE`. It is not evidence that 1000 equal evaluations were spent.

## Per-commit notes

### 1. T01, emergency-finish relocation — bug

The bug is real. The six finish modes keep the original rendezvous, so an airborne drone that cannot reach it is unpriced even when the launch truck has a reachable customer.

The fix is not complete in this commit, and it adds a defect. `_attempt_relocate` (`ground_finish.py:166-198`) moves one started fragment onto `launch_truck or truck`, inserts a new visit even when that customer is already on the route, and keeps only the nearest 8 cruise-feasible customers. It does not clear that fragment's existing handover ground drops. Moving a cross-truck rendezvous back onto the launch truck can therefore schedule the same parcel twice. Commit 8 fixes that clear. The function has no strategy argument, which is right for a shared finish, and the duplicate-delivery hole is concentrated on plans that already had a cross handover.

Relocation runs only after the six modes fail, and it returns the cheapest feasible candidate it finds. It cannot raise the price of a finish the six modes already priced, and it cannot create the online stop. It is not the source of the collapse.

### 2. T02-B, committed launch occupies the channel — OK

The bug is real. `channel_check` used to record launch intervals only for sorties that had not started, so a launch whose end is still after `t0` was invisible and a same-truck recovery could overlap it. The new interval is `[max(t0, start_time−launch_s), start_time]` on `launch_truck or truck` (`evaluate.py:185-187`), and `verify_plan` passes `state` too. Started sorties are excluded from the ordinary launch loop, so the interval is not counted twice. `compute_commit_times` extends a drone only for an in-progress `L`, so `start_time > t0` on a fragment is the launch end this interval assumes. No S/R/X branch. The tests cover one overlap and one already-finished launch.

### 3. T02-A, keep `E_min` on the emergency finish — bug

Zeroing `reserve_fraction` on the finish was a real pricing hole: a hover recovery could be given a cost with end energy below `E_min`. Keeping the real reserve, and prefixing a total failure with `UNPRICED:` (`ground_finish.py:221-222`, `simulate.py` notes `GROUND_FINISH_UNPRICED`), is right. The same commit tightens `_reachable_customers` to `e0 − e_min`. Landed recovery is allowed to finish below `E_min` with non-negative energy, so that prefilter drops legal landed finishes. Commit 9 undoes the prefilter and leaves the reserve in place. Same function for every strategy. Finish pricing runs after the stop decision, so it does not create stops.

### 4. T02-C, first failure-return check — bug

A success-path schedule can arrive at a customer with too little energy to fly the parcel back to the planned rendezvous and still finish a hover recovery at `E_min`. That narrower statement is true, and putting one check in `evaluate_plan` means nominal search, recovery, and the finish all see it. There is no strategy branch.

This commit's formula omits the wait hover and is not called from `verify_plan`. The new test then asserts that every published S and X nominal already passes. That assertion is true only because the wait is missing. Commit 10 reverses it: the same R and RC plans become `SWAP_CANNOT_FIX` once the wait is charged. The test did not show that the published plans were safe.

### 5. Scenario fingerprint, launch and recovery points — OK

The old air key stored the recovery truck and not the visit. Two sorties that recover at different visits of the same truck shared a scenario score. The new key stores `(truck, index, customer)` for launch and recovery, plus handover, priorities, `landed`, and `started` (`hybrid.py:64-81`). S and X call the same function. The repeated-customer ground collision is still present here; commit 11 fixes it. With the return check disabled, published R11 nominals match the frozen files, so this key change is not what moved them.

### 6. Uniform top-k, screen forced off — unfair

Baseline R11 sets `x_recovery_wider=True` (`run_round2.py:130-133`). Baseline `run_episode` then used that flag only for X: energy tail dropped, MILP `top_k` 10. S and R stayed at `top_k` 6 with the tail kept.

This commit stops reading `x_recovery_wider`. `run_episode` passes `recovery_energy_screen` (default `False`) and `recovery_milp_top_k` (default 10) for every strategy (`simulate.py:957-959`, `config.py:311-315`). Under the R11 preset that is a behavior change for X: the energy-penalty tail is no longer removed, while the preset label still says the tail is removed. S gains four MILP candidates. The screen is off during nominal search, which is why the nominal ablation does not move when this commit's flag is left at its new default.

`recovery_milp.py:389-413` still appends one extra solution per other truck when `strategy != "S"` and every top-k solve was optimal. "Same top-k" is the base cut, not the same candidate list. Those extras are an X/R advantage, and they spend the shared budget. The commit does not disclose that in the call site.

### 7. Hard cap of 1000 — unfair

The deleted top-ups are real and they were strategy-blind: joint +60, land +120, rescue +`rescue_evals`, fallback +24. `rescue_evals` is still passed as `main_limit` and only sets `init_rescue_used`. A scan of `eval_limit` stores in the recovery path finds none outside `Budget.__init__`. `nominal.py` still rewrites its own nominal budget; that is a different ledger. S, R, and X share the formula. On seed 101 the cap binds and does not, by itself, erase X's advantage (table above).

The split does not implement "1000 evaluations are available to find a suffix". Init receives `min(recovery_init_eval_budget, main_limit)`, and `recovery_init_eval_budget` is still 100 (`simulate.py:930-931`). The main budget is created only after init returns a plan. If init returns nothing, the episode stops and up to 900 evaluations are abandoned. Baseline's rescue top-up existed exactly for that case. X's catalog is every truck; the first `guard_n = (init_limit−4)//2` entries are forced onto the launch truck before any other truck is yielded (`recovery.py:302-310`, guard size at `recovery.py:1062`). With init limited to 100, that guard is 48 launch-truck entries before a cross truck is tried, and a failed init never reaches the ALNS half of the cap. The same numbers are applied to S, whose catalog is one truck. Equal integers, unequal coverage. This is the budget mechanism that hits cross-truck search harder, and it matters when the return rule has already made the first 100 candidates infeasible.

Wall-clock logging is honest: `run_round2` still does not pass `recovery_wall_s`, `wall_cap_armed` is false, and a replan over 60 s is counted and not stopped.

### 8. Clear the old handover drop — OK

On the cloned plan, every ground entry of the fragment's handover parcels is removed before `_attempt` (`ground_finish.py:186-189`). `_build` then places them after the new rendezvous. The input plan and state are not modified. The test that used to hard-code seed 1002 now uses seed 11 and still checks that the Bernoulli draw is a function of the parcel id, not of list order. S, R, and X share the finish function.

### 9. Prefilter allows a landed finish below `E_min` — OK

`_reachable_customers` again keeps customers whose cruise energy is at most `e0` (`ground_finish.py:157-160`). Hover, wait, recovery, and the landed-versus-hover floor stay in `evaluate_plan`. A point that is cruise-feasible and hover-infeasible is still generated and then rejected by the full evaluation, which is what a prefilter should do. Same path for every strategy. This commit repairs commit 3 without putting the zero-reserve hole back.

### 10. Wait hover on the failed return — unfair

Relative to commit 4, the missing pieces are implemented correctly and shared:

- `failure_return_requirement` adds loaded hover for the truck/channel wait plus `recovery_s`, and `E_min`, and a landed sortie pays cruise only with reserve 0 (`schedule.py:619-642`).
- The swap pass treats that requirement as a start-of-service floor by checking end-of-stage energy against `need − stage_energy` (`schedule.py:667-671`). The service hover cancels, so a pre-launch swap is judged against energy at arrival. Algebra holds. A sortie that has already launched cannot be repaired, which matches "no swap in the air".
- `evaluate_plan` and `verify_plan` both call `failure_return_violations`.
- `r_start` is unchanged: `max(rec_ready, arr)` equals the old `max(ready, t_arr, arr, channel_free)`. The new field does not move the success-path schedule.
- Resumed services are exempt; the next unrevealed service is not.

The rule is still the wrong contingency, for the reasons in the collapse section. Nominal search never sets `landed` (only recovery landing candidates and the emergency finish do), so the landed exemption does not give the nominal heuristic the action `land_and_wait` already allows. X also still faces the pre-existing cross margin `E_min + 0.05·E_cap` and the 90 s empty-hover slack, on top of this check.

`tl.rec_ready[stage.sid]` is an unguarded lookup (`schedule.py:639`). A recovery visit that is not on a route passes `validate_structure` (that function checks that the visit exists, not that it is on the route) and then `schedule_plan` raises `KeyError`. Reproduced by removing the recovery visit from the route of the frozen C50 S plan. Search that emits such a candidate crashes the episode instead of recording an infeasible evaluation.

The adjusted tests document the new physics, and two of them lower `beta_hover` to 0.5 so old fixtures stay feasible (`test_round4.py`, `test_round6.py`). Those tests no longer lock the published hover power. The cross-robust margin test replaces the real evaluation with an injected 0.06 / 0.10 kWh ledger because the saved R50 X plan is now rejected upstream. The margin arithmetic is still tested. The integration claim is not.

Non-swap charging is unchanged. `allocate_charging` does not see `failure_return_need`. The light package runs `swap_mode`, so the R11 rebuilds do not take that path. A non-swap run would reject after the LP rather than charge for the return.

### 11. Ground fingerprint includes route position — OK

Ground entries are `(truck, index, customer, parcels)` for visits that sit on a route (`hybrid.py:72-74`). Two drops of the same customer at two positions no longer share a scenario score, and renumbering visit ids still hits. S and X share the cache. An off-route visit is absent from the key; that is a leftover collision for a plan structure validation usually rejects. The nominal ablation shows this key is not what changed the published plans.

### 12. Screen and top-k defaults downstream — OK

`initial_recovery` and `solve_recovery_milp` default `top_k` to 10. The catalog drops `est ≥ 1e4` before the S-prefix / tail split, for every strategy, when the switch is on (`recovery.py:291-293`, `1064`). That closes the hole where S, and X's guard prefix, skipped the screen. The R11 preset still does not turn the switch on, so this commit does not restore baseline X's tail filter and does not change the nominals. H4's extra per-truck solve remains.

### 13. `S_SEED` receives the screen switch — OK

The X-only fallback catalog was built with `drop_energy_tail` left at its default `False` (`recovery.py:1237-1241` before this commit). With the screen on, the main X catalog dropped the tail and the fallback put it back. Passing `energy_screen` through is the right one-line fix. Default `False` means an R11 run, which never turns the screen on, is unchanged by this commit. The fallback existing only for X is pre-existing (`keep_s_recovery`), and the screen value it now uses is the same value S uses.

## S and X, side by side

Shared, and actually the same code path: channel check, finish reserve, finish relocation, failure-return formula, scenario fingerprint, the numeric hard cap, and the top-k value passed into `initial_recovery`.

Not the same experiment as the frozen R11 comparison:

- `x_recovery_wider=True` is unread. Baseline X dropped energy-penalty tail candidates. This tree does not, for anyone.
- Init is capped at 100 inside a stated cap of 1000, and a failed init does not spend the rest. The launch-truck guard consumes 48 of those 100 before X tries another truck.
- H4 still adds candidates only when `strategy != "S"`.
- The return rule has no `if strategy` and still deletes long truck waits. Cross-truck waits are the long ones (frozen C50 X cross slack bottoms at 0.009 kWh). Same-truck R/RC services with a 150–230 s loaded wait are deleted too, so S's nominals also get more expensive. The gap shrinks because X's remaining cross plans are fewer (8→3) and, on C50, the search stops returning a cross plan that is still legal.
- X-only 5% recovery margin and 90 s slack are unchanged and now sit on top of the new floor.

## Required fixes, in order

1. **Replace the failed-return floor with the contingency the episode actually flies.** At a failure the drone is at that customer, a recovery there is legal, `land_and_wait` spends no hover, and the replan chooses the rendezvous. A sufficient check is: from the arrival energy, some legal recovery (the failure customer itself, or a customer the drone can reach) is feasible under landed or hover physics, whichever the preset allows. Charging loaded hover until the original truck's nominal `rec_ready` rejects plans the replan can fly, and it is the entire nominal move from −2.879% to −0.905%. Do this for S, R, and X with one function.

2. **If any original-rendezvous reserve is kept, guard `rec_ready` and make the landed alternative reachable in nominal search.** Missing `rec_ready` must be an infeasible evaluation, not `KeyError` (`schedule.py:639`). With `land_and_wait` on, a nominal sortie that fails the hover floor and passes the landed floor has to be able to flip to `landed` inside the nominal neighborhood. Today that flag is only set for an already-airborne recovery candidate and for the emergency finish.

3. **Spend the 1000 on the replan that needs them.** One budget object of 1000 for init and the main loop. Init may use as many as it needs up to 1000. The main loop gets the remainder. A replan stops only when a feasible suffix has been found and the budget is exhausted, or when the budget is exhausted with no suffix. Do not stop at 100 while 900 remain (`simulate.py:930-931`, `984-993`). Apply that to S, R, and X. Revisit `guard_n`: forcing the first 48 evaluations onto the launch truck before any cross truck is tried is a large fraction of a 100-eval init window and a small fraction of a 1000-eval window.

4. **Make the energy screen match the preset, for all three strategies.** Either pass `x_recovery_wider` into `recovery_energy_screen` for S, R, and X, or delete the preset flag and change the R11 label. Leaving `x_recovery_wider=True` unread (`run_round2.py:132-133` versus `simulate.py:958`) silently drops a filter only X used to have. When the screen is on, H4's extra per-truck entries (`recovery_milp.py:389-413`) should be included in the "same candidate list" claim or removed.

5. **Do not describe the non-swap charging LP as covered.** `failure_return_need` never enters `allocate_charging`. The light package is swap-mode, so this did not affect the rebuild. A later non-swap run would only reject, not recharge.

No algorithm patch is applied in this branch. The two mechanisms above are large enough that a one-line change would be a new policy, not a typo fix.

## Tests and commands

Full suite before the CRLF restore, from `proj_r6` with `PYTHONPATH=src`:

`python3 -m pytest -q --tb=line -p no:cacheprovider`

Result: `2 failed, 283 passed, 3 skipped` in 237 s. Both failures are `test_preserve_crlf` on `recovery.py` and `simulate.py`, caused by applying an LF patch onto CRLF sources. After restoring CRLF, those two tests pass. The author's 285 passed / 3 skipped count is the same set. `pytest-xdist` was not installed, so the suite was one process. The order-dependent `test_find_chain_slot_and_cycle_detection` passed inside that full run.

Nominal ablation: six cases, R11, budget 1000, three workers, one process per case, for the tree as committed and for the same tree with the return check disabled. Outputs under `/tmp/nom_head` and `/tmp/nom_nofail` (not committed).

Episodes: C50 and R50, seed 101, strategies S and X, baseline worktree at `5eab1b2` against the frozen nominals, this tree with the return check off against those same nominals, and this tree with the check on against the rebuilt nominals. No seed in 3001–3030 or 4001–4030.

## Suggestion, not applied

Init should draw on the same 1000 as the main loop, and a missing `rec_ready` should fail the evaluation:

```python
# simulate.py, inside the replan loop
recovery_budget = Budget(main_limit, recovery_wall_s, start=t_budget0)
init_budget = recovery_budget          # one ledger; no nested cap of 100
# ... initial_recovery(..., budget=init_budget)
# main loop keeps using recovery_budget, so it sees the evaluations init already took
```

```python
# schedule.py, failure_return_requirement
ready = tl.rec_ready.get(stage.sid)
if ready is None:
    return None          # caller records the sortie as energy-infeasible
```

The second snippet needs the caller to treat "service with no scheduled recovery" as a violation. Returning `None` alone would skip the check. Neither change is in the tree.
