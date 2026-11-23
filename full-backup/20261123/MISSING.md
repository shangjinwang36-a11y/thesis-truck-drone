# Missing and authenticity gaps

Snapshot cutoff: 2026-11-21 21:09:58 CST (Asia/Shanghai, UTC+8)

This backup cannot claim that all VM content has been recovered.

- vm_private_observer_34: M49 other 34 jobs private observer contexts and complete private observer per-replan candidate streams are not included in the actual36 redacted bundle and are not claimed recovered from the VM.
- paid_relief_and_two_ONE_and_2197: M49 paid_relief original source (e46...) and two old ONE drivers/contexts/candidates remain missing; old 2197 extra schedule count unknown. Not invented, not filled with CloudAgent.
- m49_actual36_unredacted_complete_set: Original unredacted M49 actual36 execution hash manifest/private originals were not supplied as a complete set.
- vm_paths_not_on_parent_box: Files referenced only under VM /workspace/m46_incoming/project/batches or /home/ubuntu/m47_private_exec are not proven locally present unless represented by a saved attachment/subtree. /opt/cursor does not exist on this box. The entire VM filesystem is NOT backed up.
- vm_unexported_failures_and_terminal_history: Remote uncommitted source, abandoned/interrupted run directories, console terminal histories, and artifacts never exported from the VM are not enumerated by a complete remote manifest.

## Post-cutoff incremental (not in this package)

- M50 paid-cache follow-on files under offline_bottleneck_20261121 (15 files observed after the completed 394-file M50 snapshot) are reserved for a later incremental backup and were not chased here.

## Increment increment_20261121_234839 (2026-11-21 23:48:39 CST)

- M50 offline_bottleneck, M51 (including real_cache_gate/mechanical_v2), and M52-M57 complete trees were added.
- M58_bot_joint_coverage_20261121 was excluded as in-progress at this increment cutoff and is not claimed complete.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261122_023149 (2026-11-22 02:31:49 CST)

- M58-M65 completed sealed trees were added (source, inputs, RAW/EV/trajectories, reports, failures, journals, manifests). World-state bytes were stored without expanding or analyzing them.
- M50-M57 supplement rescan: new=0, changed=0.
- M66 was excluded as in-progress at this cutoff and is not claimed complete.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261122_045229 (2026-11-22 04:52:29 CST)

- M66-M69 completed sealed trees were added (source, originals, inputs, EV, logs, registration, tests, intermediate drafts, failures, supervision interruptions, native accounting, formal verify, manifests). World-state bytes were stored without expanding or analyzing them.
- M50-M65 supplement rescan: new=0, changed=0.
- M70 was excluded as in-progress at this cutoff and is not claimed complete.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261122_072132 (2026-11-22 07:21:32 CST)

- M70-M72 completed sealed trees were added (including unused/rejected revisions, tests, failures, M72 inputs/RAW/dynamic EV/postCAS, supervision interruptions, accounting, release verification, and manifests). World-state bytes were stored without expanding or analyzing them.
- M50-M69 supplement rescan: new=0, changed=0.
- M73 was excluded as in-progress at this cutoff and is not claimed complete.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261122_094439 (2026-11-22 09:44:39 CST)

- M73-M75 completed sealed trees were added (including M75 main seal and postseal_supervision_0941, two supervision interruptions, failures, complete inputs/RAW/EV/Q original receipts, world-state original bytes, source, accounting, final verify, and manifests). World-state bytes were stored without expanding or analyzing them.
- M50-M72 supplement rescan: new=0, changed=0.
- M76 was excluded as in-progress at this cutoff and is not claimed complete. World/holdout contents were not analyzed.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261122_132920 (2026-11-22 13:29:20 CST)

- M76-M79 completed sealed trees were added (including M77 failed zero-call, M78 all revisions/tests/intermediate drafts, M79 eight arms and three supervision interruptions plus cache-error minimal fix, complete source bytes, RAW/EV/Q receipts, inputs, world-state original bytes, source, accounting, reports, and manifests). World-state bytes were stored without expanding or analyzing them.
- M50-M75 supplement rescan: new=0, changed=0.
- M80 was excluded as in-progress at this cutoff and is not claimed complete. World/holdout contents were not analyzed.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261123_090829 (2026-11-23 09:08:29 CST)

- M80-M85 trees were added (M80-M84 sealed complete trees; M85 including systematic_audit and review_0009 from a read-only snapshot, plus review_0010 and other in-flight audit files present at snapshot cutoff). Failures, revisions, tests, intermediate drafts, RAW/EV/Q receipts, inputs, world-state original bytes, source, accounting, reports, and manifests are included. World-state bytes were stored without expanding or analyzing them.
- M50-M79 supplement rescan: new=0, changed=0.
- M85 in-progress material was snapshotted and included, not omitted. Post-cutoff live differences are listed in the increment manifests. World/holdout contents were not analyzed.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261123_091449 (2026-11-23 09:14:49 CST)

- Post-cutoff supplement: live M85/systematic_audit/review_0010 files that appeared or changed after snapshot cutoff_20261123_090736 were snapshotted again (postcutoff_20261123_091422 at 2026-11-23 09:14:22 CST) and appended. Earlier increment volumes were not overwritten.
- This is a post-cutoff supplement on top of increment_20261123_090829. M50-M79 were not re-walked in this supplement.
- Remaining live changes after this supplement cutoff, if any, are listed in post-cutoff diff manifests and are not claimed included.
- Original VM-only gaps remain. This is still not a full VM backup.

## Increment increment_20261123_091709 (2026-11-23 09:17:09 CST)

- Full systematic_audit tree was re-snapshotted after the 09:15 stable seal (auditseal_20261123_091613 at 2026-11-23 09:16:13 CST), including review_0010 delivery, V7_TO_V8_FINAL_0003.diff, retained non-authoritative V7_TO_V8_FINAL.diff, fixes/blueprint_v0008, and SOURCE_REPAIR_DELIVERY_0010.json. Earlier volumes were not overwritten.
- This is a post-cutoff supplement on top of increment_20261123_090829. M50-M79 were not re-walked in this supplement.
- Remaining live changes after this supplement cutoff, if any, are listed in post-cutoff diff manifests and are not claimed included.
- Original VM-only gaps remain. This is still not a full VM backup.
