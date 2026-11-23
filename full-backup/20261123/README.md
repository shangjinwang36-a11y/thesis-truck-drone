# Thesis full backup 2026-11-23

Frozen package for the public repository `shangjinwang36-a11y/thesis-truck-drone`.

- Audit-tree snapshot: `auditseal_20261123_091613` at **2026-11-23 09:16:13 CST** (Asia/Shanghai, UTC+8)
- Packed as `increment_20261123_091709` (packer cutoff **2026-11-23 09:17:09 CST**)
- Earlier increments in this same package go back to the 2026-11-21 21:09:58 CST original snapshot, including M50–M85 and the 09:15 review_0010 / v8 seal.
- Volume payloads are **not** stored in git history. They are GitHub Release assets on tag `thesis-full-backup-20261123`.
- `M86` and any work after 09:17:09 CST are **not** in this package and will be a later increment.

## Restore

1. Download this branch (or this folder) for `restore.py`, `manifests/`, and docs.
2. Download every asset from the release `thesis-full-backup-20261123` into a `volumes/` tree, converting each asset name by replacing `__` with `/`.
   Example: `increment_20261123_091709__incr_vol_0002.tar.gz` → `volumes/increment_20261123_091709/incr_vol_0002.tar.gz`.
3. From the backup root (the folder that contains `restore.py` and `manifests/`):

```sh
python3 restore.py --backup-root . --verify-only --dest /tmp/verify_unused
```

## Integrity and exclusions

- Upload unit index: `manifests/upload_unit_index.json` (346 units, all ≤ 45 MiB).
- Credential / login-store / unrelated personal paths remain excluded (27 exclusion records). Secret values are not stored.
- World-state / holdout bytes are stored as original objects and are not expanded.
- Original VM gaps remain; this is not a full VM backup.
- `review_0010/V7_TO_V8_FINAL.diff` is retained only as a non-authoritative interrupted draft. The authoritative patch is `V7_TO_V8_FINAL_0003.diff`.
- `SOURCE_REPAIR_DELIVERY_0010.json` SHA256 `082b2ae5378a1bc9264e066c67538e67f5522843fbf1f0b75d23d0e12279ac89`.

See `docs/PACKAGE_CUTOFF_AND_PENDING.md` and `docs/README_RESTORE.md`.
