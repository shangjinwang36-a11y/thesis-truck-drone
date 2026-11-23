# Thesis research full backup (prepared, not uploaded)

Snapshot cutoff: **2026-11-21 21:09:58 CST** (Asia/Shanghai, UTC+8)

This directory is a local, restorable, content-addressable archive of readable
research on the parent box at the cutoff. It is **prepared**, not uploaded.
Do not describe this package as already on GitHub.

## Target for a later unified upload (not performed in this run)

- Existing public repository: https://github.com/shangjinwang36-a11y/thesis-truck-drone
- No new repository, no visibility change, no force-push, no PR, no overwrite of main/history
- Preferred later layout: a dated backup branch for the restore index plus GitHub Release assets for volume files, after the parent explicitly triggers upload near quota
- Current GitHub write-path blocker: gh is installed but not logged in. cursor-github MCP cannot push files or upload release assets. CloudAgent is forbidden by the user. A later upload needs sanctioned gh authentication. Do not extract tokens or bypass controls.

## What is included

- Research root: /workspace/projects/td_cloud_research_20261120 (including all batches present at cutoff, success/failure/interrupt artifacts, logs, audits, 147 source/execution packages kept as found)
- Source project: /workspace/projects/失败无人机卡车配送_20261119
- All M46 handoff / M47-M49 independent audit trees and audit reports, plus M46/M47 research tar/json artifacts and workspace loose research files
- Agent thesis-related attachments and the readable cloud-agent store for bc-4a385c7b-5c4c-542a-97f4-11c345e9974e (research files only)
- Other local research trees: thesis-hub, thesis-prep, thesis-truck-drone checkout, tdbase/tddev/tdwork, work_r6, round10, xfer, exports, codex evidence, transcripts, etc.
- Research world flags and visible private state are archived as original bytes (user authorized later public upload). Sealed case material (including sealed_core and any 4001-4030 / 270701 path components) is stored as raw bytes without expanding or viewing world contents.
- Completed M50_bot_narrow_land_20261121 is included (394 files, 66,513,297 bytes). FINAL_MANIFEST SHA d3f7b1d5a5bf79f63b02b6d5628b408c04eeb11d680a7bd6c42781f8af217d6f matches. Sealed originals were archived as bytes and not modified. Subsequent paid-cache analysis under offline_bottleneck_20261121 is reserved for a later incremental snapshot.

## What is excluded

- Passwords, API tokens, and login credentials: originals are not stored in the object store. If a research file contained a credential pattern, a sanitized copy is stored and the original path is listed in manifests/credential_exclusions.json (paths and pattern names only; no secret values).
- Virtualenvs and bytecode caches
- Unrelated personal/other-bot data (avatars, pptbot, routine-state, other stores)
- Anything that exists only on a Cursor/cloud VM and was never exported here

## Known gaps (do not claim a full VM recovery)

See manifests/missing_and_gaps.json. In short:

- Remaining 34-job private observer contexts / per-replan streams: not on this box as a complete set
- paid_relief original source, two old ONE originals, and the 2197 extra schedule count: unknown
- Unredacted M49 actual36 originals: not supplied as a complete set
- VM paths /opt/cursor, /workspace/m46_incoming/..., /home/ubuntu/m47_private_exec, unexported failed/interrupted directories, and terminal history: not present or not enumerated here

## Restore

```
python3 restore.py --backup-root . --dest /path/to/restore
python3 restore.py --backup-root . --verify-only
```

If cas/objects is empty, restore.py will extract volumes after checking each volume SHA-256.

## Layout

- STATE.json / STATE.md — progress and upload status (prepared, not uploaded)
- manifests/source_inventory.json — sources, file/byte counts, coverage
- manifests/source_to_object_map.jsonl.gz — every source path to object SHA-256 (deduped bytes, mapping not omitted)
- manifests/object_index.jsonl.gz — unique objects
- manifests/volume_manifest.json — volume files, hashes, membership
- manifests/credential_exclusions.json — credential paths (no values)
- manifests/missing_and_gaps.json
- manifests/archive_verification.json
- cas/objects/aa/<sha256> — unique file bytes
- volumes/vol_XXXX.tar.gz — GitHub-sized packs of objects
- restore.py — reconstruction script

Same-byte files are stored once; the source-to-object map keeps every path.
