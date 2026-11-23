Thesis full backup frozen at 2026-11-23 09:16:13 / 09:17:09 CST (Asia/Shanghai).

This release holds the volume units for the prepared local package under `/workspace/thesis_full_backup_20261121_2058` (local path on the build machine). Branch `backup/20261123-thesis-full` holds restore scripts and manifests only.

Included: original 2026-11-21 snapshot plus increments through `increment_20261123_091709` (M50–M85, systematic_audit including review_0009 and the 09:15 review_0010 / v8 seal, SOURCE_REPAIR_DELIVERY_0010.json).

Not included: M86 and any work after 09:17:09 CST.

346 volume units, all ≤ 45 MiB. Verify by downloading assets and checking SHA256 against `manifests/upload_unit_index.json`, then `python3 restore.py --backup-root . --verify-only`.

Credential exclusion path count remains 27. Do not treat this as a full VM backup.
