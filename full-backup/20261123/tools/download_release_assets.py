#!/usr/bin/env python3
"""Download release assets using REMOTE_ASSET_NAME_MAP_20261123.json.

Writes files to volumes/<planned_asset_name with __ replaced by /> and checks
SHA256 against the official expected hashes. Does not modify upload_unit_index.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("GH_PROMPT_DISABLED", "1")
os.environ.setdefault("GH_NO_UPDATE_NOTIFIER", "1")

BACKUP = Path("/workspace/thesis_full_backup_20261121_2058")
MAP = BACKUP / "manifests" / "REMOTE_ASSET_NAME_MAP_20261123.json"
REPO = "shangjinwang36-a11y/thesis-truck-drone"
TAG = "thesis-full-backup-20261123"


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def main() -> int:
    dest_root = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/backup-upload-20261123/restore-from-remote")
    doc = json.loads(MAP.read_text())
    ok = bad = missing = 0
    dest_root.mkdir(parents=True, exist_ok=True)
    scratch = dest_root / ".download-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    for u in doc["units"]:
        planned = u["planned_asset_name"]
        remote = u["actual_remote_name"]
        placed = dest_root / "volumes" / planned.replace("__", "/")
        placed.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["gh", "release", "download", TAG, "--repo", REPO, "--pattern", remote, "--dir", str(scratch), "--clobber"],
            text=True, capture_output=True, timeout=60 * 20,
        )
        src = scratch / remote
        if r.returncode != 0 or not src.exists():
            print(f"MISSING {planned} remote={remote}", flush=True)
            missing += 1
            continue
        digest, n = sha256_file(src)
        if digest != u["expected_sha256"] or n != u["expected_bytes"]:
            print(f"BAD {planned} remote={remote} got={digest} expected={u['expected_sha256']}", flush=True)
            bad += 1
            src.unlink(missing_ok=True)
            continue
        if placed.exists():
            placed.unlink()
        src.replace(placed)
        ok += 1
    print(json.dumps({"ok": ok, "bad": bad, "missing": missing, "dest": str(dest_root)}), flush=True)
    return 0 if bad == 0 and missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
