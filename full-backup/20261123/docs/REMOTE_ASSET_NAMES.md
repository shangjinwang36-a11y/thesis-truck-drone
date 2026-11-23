# Remote asset names for thesis-full-backup-20261123

Times below are Asia/Shanghai (UTC+8), labeled CST.

The official pack index `manifests/upload_unit_index.json` is unchanged.
It still records the planned unique asset names and the original SHA256 values.

## What happened on the release

`gh release upload path#planned_name` did not store the planned unique names.
The first 336 units landed under their local basenames. Ten later volumes that
shared a basename (`incr_vol_0002/0005/0006/0009/0010/0011.tar.gz`) were
skipped during that pass; they were then uploaded under the planned unique
names (for example `increment_20261122_023149__incr_vol_0005.tar.gz`).

After that gap-fill, the release `thesis-full-backup-20261123` has 346
assets and 12,808,094,808 bytes, with no duplicate names. Size of each asset
matches the official index. Download SHA256 and remote restore verify-only
are recorded separately; listing and size agreement alone is not a hash pass.

## How to restore volumes from the release

Use `manifests/REMOTE_ASSET_NAME_MAP_20261123.json`:

1. Download `actual_remote_name` from the release.
2. Write it to `volumes/` + `planned_asset_name` with `__` replaced by `/`.
3. Compare SHA256 with `expected_sha256` from the same map (or from
   `upload_unit_index.json`). Do not treat a same-sized short name as
   automatically correct.
4. Run `python3 restore.py --backup-root . --verify-only`.

`tools/download_release_assets.py` does steps 1–3.

The first increment that used a colliding basename owns the short remote
name. Later increments with the same basename use the unique prefixed name.
`volume_manifest.json` still distinguishes those files by their unique
`path` fields; do not flatten them into a single `volumes/incr_vol_0005.tar.gz`.
