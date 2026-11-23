#!/usr/bin/env python3
"""Download-hash verify the 2026-11-23 backup release using actual remote asset names.

GitHub ignored the `path#asset_name` unique names for the first 336 uploads, so those
assets landed under the local basename. Ten colliding later volumes were then uploaded
under their planned unique names. This tool:

- lists every release asset via the paginated official API (not `gh release view`)
- maps each planned unit to the actual remote name (first-wins basename, else unique prefix)
- downloads each asset and SHA256-checks it against manifests/upload_unit_index.json
- never modifies that index or the original hashes
- never re-uploads the 336, never uses --clobber on upload

Usage: python3 -u tools/verify_remote_mapped.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("GH_PROMPT_DISABLED", "1")
os.environ.setdefault("GH_NO_UPDATE_NOTIFIER", "1")

BACKUP = Path("/workspace/thesis_full_backup_20261121_2058")
REPO = "shangjinwang36-a11y/thesis-truck-drone"
BRANCH = "backup/20261123-thesis-full"
TAG = "thesis-full-backup-20261123"
INDEX = BACKUP / "manifests" / "upload_unit_index.json"
DEST = Path("/workspace/backup-upload-20261123/download-verify-mapped")
RESTORE_ROOT = Path("/workspace/backup-upload-20261123/restore-from-remote")
MAP_PATH = BACKUP / "manifests" / "REMOTE_ASSET_NAME_MAP_20261123.json"
REPORT = BACKUP / "docs" / "UPLOAD_MAPPED_VERIFY_20261123.json"
RESTORE_REPORT = BACKUP / "docs" / "REMOTE_RESTORE_VERIFY_20261123.json"
LOG = BACKUP / "docs" / "MAPPED_VERIFY_PROGRESS.jsonl"
STATUS = BACKUP / "docs" / "MAPPED_VERIFY_STATUS.json"


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z")


def log(event: str, **kw):
    rec = {"time": now(), "event": event, **kw}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    extra = " ".join(f"{k}={v}" for k, v in kw.items() if k not in {"stdout", "stderr", "units"})
    print(f"[{rec['time']}] {event} {extra}", flush=True)


def write_status(**kw):
    cur = {}
    if STATUS.exists():
        try:
            cur = json.loads(STATUS.read_text())
        except Exception:
            cur = {}
    cur.update(kw)
    cur["updated"] = now()
    STATUS.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n")


def run(cmd, timeout=None):
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def list_all_assets() -> tuple[int, list[dict]]:
    r = run(["gh", "api", f"/repos/{REPO}/releases/tags/{TAG}", "--jq", ".id"])
    if r.returncode != 0 or not (r.stdout or "").strip():
        raise SystemExit(f"cannot read release id: {(r.stderr or r.stdout or '')[-400:]}")
    rid = (r.stdout or "").strip()
    # Line-delimited objects across paginated arrays.
    r2 = run([
        "gh", "api", "--paginate",
        f"/repos/{REPO}/releases/{rid}/assets?per_page=100",
        "--jq", ".[] | {name,size,id,browser_download_url,url,updated_at,digest}",
    ])
    if r2.returncode != 0:
        raise SystemExit(f"cannot list assets: {(r2.stderr or r2.stdout or '')[-400:]}")
    assets = []
    for line in (r2.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        assets.append(json.loads(line))
    return int(rid), assets


def planned_remote_name(unit: dict, first_wins: dict[str, str]) -> tuple[str, str]:
    base = Path(unit["path"]).name
    planned = unit["asset_name"]
    if first_wins[base] == planned:
        reason = "basename_equals_planned" if planned == base else "unprefixed_first_wins_basename"
        return base, reason
    return planned, "unique_prefixed_gapfill"


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n



def run_restore_verify_only() -> dict:
    """Rebuild an isolated backup root from downloaded volumes and official manifests.

    Path fields in the *copy* of volume_manifest.json are rewritten so restore.py
    cannot fall back to the original local volume paths. Official manifests in
    the backup tree are not modified.
    """
    import shutil as sh
    RESTORE_ROOT.mkdir(parents=True, exist_ok=True)
    (RESTORE_ROOT / "manifests").mkdir(parents=True, exist_ok=True)
    (RESTORE_ROOT / "volumes").mkdir(parents=True, exist_ok=True)
    sh.copy2(BACKUP / "tools" / "restore.py", RESTORE_ROOT / "restore.py")
    # Official maps/manifests needed by restore.py
    for name in ("source_to_object_map.jsonl.gz", "volume_manifest.json"):
        src = BACKUP / "manifests" / name
        if not src.exists():
            raise FileNotFoundError(name)
        sh.copy2(src, RESTORE_ROOT / "manifests" / name)
    vol_path = RESTORE_ROOT / "manifests" / "volume_manifest.json"
    man = json.loads(vol_path.read_text())
    old_prefix = str(BACKUP)
    new_prefix = str(RESTORE_ROOT)

    def rewrite(obj):
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k in {"path"} and isinstance(v, str) and v.startswith(old_prefix + "/"):
                    obj[k] = new_prefix + v[len(old_prefix):]
                else:
                    rewrite(v)
        elif isinstance(obj, list):
            for v in obj:
                rewrite(v)

    rewrite(man)
    man["note_remote_restore"] = (
        "This is a copy used only for remote download restore verify. "
        "Absolute paths were rewritten to the isolated restore root. "
        "The official backup manifests were not changed."
    )
    vol_path.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n")

    # Sanity: no rewritten path should still point at the official backup volumes.
    leftover = []
    def check(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "path" and isinstance(v, str) and v.startswith(old_prefix):
                    leftover.append(v)
                else:
                    check(v)
        elif isinstance(obj, list):
            for v in obj:
                check(v)
    check(man)
    if leftover:
        raise RuntimeError(f"path rewrite incomplete: {leftover[:5]}")

    log("restore_verify_start", root=str(RESTORE_ROOT))
    r = run(
        [sys.executable, str(RESTORE_ROOT / "restore.py"), "--backup-root", str(RESTORE_ROOT), "--verify-only", "--dest", str(RESTORE_ROOT / "verify_unused")],
        timeout=60 * 180,
    )
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    result = {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "output": out[-4000:],
        "restore_root": str(RESTORE_ROOT),
        "used_official_backup_volumes": False,
    }
    log("restore_verify_done", ok=result["ok"], returncode=r.returncode, output=out[-500:])
    return result


def main() -> int:
    idx = json.loads(INDEX.read_text())
    units = idx["units"]
    rid, assets = list_all_assets()
    by_name = {}
    dups = defaultdict(list)
    for a in assets:
        dups[a["name"]].append(a)
        by_name[a["name"]] = a
    if any(len(v) > 1 for v in dups.values()):
        log("duplicate_remote_names", names=[k for k, v in dups.items() if len(v) > 1])

    first_wins = {}
    for u in units:
        base = Path(u["path"]).name
        if base not in first_wins:
            first_wins[base] = u["asset_name"]

    mapping_units = []
    for u in units:
        remote_name, reason = planned_remote_name(u, first_wins)
        mapping_units.append({
            "planned_asset_name": u["asset_name"],
            "actual_remote_name": remote_name,
            "reason": reason,
            "path": u["path"],
            "expected_sha256": u["sha256"],
            "expected_bytes": u["bytes"],
            "increment": u.get("increment"),
            "type": u.get("type"),
            "parent_sha256": u.get("parent_sha256"),
        })

    DEST.mkdir(parents=True, exist_ok=True)

    results = []
    ok = bad = missing = 0
    checked_bytes = 0
    write_status(
        release_id=rid,
        remote_asset_count=len(assets),
        planned_units=len(units),
        ok=0, bad=0, missing=0, checked_bytes=0, started=now(),
    )
    log("start", release_id=rid, remote_asset_count=len(assets), planned_units=len(units))

    for i, mu in enumerate(mapping_units, 1):
        name = mu["actual_remote_name"]
        planned = mu["planned_asset_name"]
        rec = dict(mu)
        meta = by_name.get(name)
        if not meta:
            rec["status"] = "missing_on_remote"
            missing += 1
            results.append(rec)
            log("missing", planned=planned, remote=name)
            continue
        rec["remote_size"] = meta.get("size")
        rec["remote_id"] = meta.get("id")
        rec["remote_digest_field"] = meta.get("digest")
        rec["remote_updated_at"] = meta.get("updated_at")
        out = DEST / name
        r = run(
            ["gh", "release", "download", TAG, "--repo", REPO, "--pattern", name, "--dir", str(DEST), "--clobber"],
            timeout=60 * 20,
        )
        if r.returncode != 0 or not out.exists():
            found = None
            if DEST.exists():
                for c in DEST.iterdir():
                    if c.is_file() and c.name == name:
                        found = c
                        break
            if not found:
                rec["status"] = "download_failed"
                rec["stderr"] = (r.stderr or r.stdout or "")[-300:]
                bad += 1
                results.append(rec)
                log("download_failed", planned=planned, remote=name)
                continue
            out = found
        digest, n = sha256_file(out)
        rec["downloaded_bytes"] = n
        rec["downloaded_sha256"] = digest
        size_ok = (meta.get("size") == mu["expected_bytes"] == n)
        hash_ok = digest == mu["expected_sha256"]
        if size_ok and hash_ok:
            rec["status"] = "ok"
            ok += 1
            checked_bytes += n
        else:
            rec["status"] = "hash_or_size_mismatch"
            rec["size_ok"] = size_ok
            rec["hash_ok"] = hash_ok
            bad += 1
            log("mismatch", planned=planned, remote=name, expected=mu["expected_sha256"], got=digest, expected_bytes=mu["expected_bytes"], got_bytes=n, remote_size=meta.get("size"))
        results.append(rec)
        # Keep a copy in the isolated restore root, then drop the scratch file.
        if rec.get("status") in {"ok", "hash_or_size_mismatch"} and out.exists():
            rel = Path(mu["path"]).resolve().relative_to(BACKUP)
            placed = RESTORE_ROOT / rel
            placed.parent.mkdir(parents=True, exist_ok=True)
            if placed.exists():
                placed.unlink()
            out.replace(placed)
            rec["placed_path"] = str(placed)
        elif out.exists():
            try:
                out.unlink()
            except OSError:
                pass
        if i % 10 == 0 or i == len(mapping_units):
            log("progress", i=i, total=len(mapping_units), ok=ok, bad=bad, missing=missing, checked_bytes=checked_bytes)
            write_status(ok=ok, bad=bad, missing=missing, checked_bytes=checked_bytes, processed=i)

    map_doc = {
        "created_at": now(),
        "repo": REPO,
        "release_tag": TAG,
        "release_id": rid,
        "release_url": f"https://github.com/{REPO}/releases/tag/{TAG}",
        "branch": BRANCH,
        "branch_url": f"https://github.com/{REPO}/tree/{BRANCH}",
        "note": (
            "Do not change manifests/upload_unit_index.json. planned_asset_name and expected_sha256 "
            "are the original packed values. actual_remote_name is the asset name currently on the release. "
            "To rebuild a volumes/ tree, download actual_remote_name and write it to the path formed by "
            "replacing '__' with '/' in planned_asset_name (under volumes/)."
        ),
        "remote_asset_count": len(assets),
        "planned_unit_count": len(units),
        "ok": ok,
        "bad": bad,
        "missing": missing,
        "checked_bytes": checked_bytes,
        "units": [
            {
                "planned_asset_name": r["planned_asset_name"],
                "actual_remote_name": r["actual_remote_name"],
                "reason": r["reason"],
                "expected_sha256": r["expected_sha256"],
                "expected_bytes": r["expected_bytes"],
                "status": r.get("status"),
                "downloaded_sha256": r.get("downloaded_sha256"),
                "downloaded_bytes": r.get("downloaded_bytes"),
            }
            for r in results
        ],
        "remote_names_not_in_plan": sorted(
            set(by_name) - {r["actual_remote_name"] for r in results}
        ),
    }
    MAP_PATH.write_text(json.dumps(map_doc, ensure_ascii=False, indent=2) + "\n")

    report = {
        "time": now(),
        "release_tag": TAG,
        "release_id": rid,
        "release_url": f"https://github.com/{REPO}/releases/tag/{TAG}",
        "branch": BRANCH,
        "map_path": str(MAP_PATH),
        "index_path": str(INDEX),
        "index_untouched": True,
        "ok": ok,
        "bad": bad,
        "missing": missing,
        "checked_bytes": checked_bytes,
        "planned_units": len(units),
        "remote_asset_count": len(assets),
        "results": results,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    restore_result = None
    if bad == 0 and missing == 0 and ok == len(units):
        try:
            restore_result = run_restore_verify_only()
        except Exception as e:
            restore_result = {"ok": False, "error": str(e)}
            log("restore_verify_failed", error=str(e))
    else:
        log("skip_restore_verify", reason="hash_verify_not_clean", ok=ok, bad=bad, missing=missing)

    report["restore_verify"] = restore_result
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    RESTORE_REPORT.write_text(json.dumps({"time": now(), "hash_ok": ok, "hash_bad": bad, "hash_missing": missing, "restore": restore_result}, ensure_ascii=False, indent=2) + "\n")

    log("done", ok=ok, bad=bad, missing=missing, checked_bytes=checked_bytes, map=str(MAP_PATH), report=str(REPORT), restore=(restore_result or {}).get("ok"))
    write_status(ok=ok, bad=bad, missing=missing, checked_bytes=checked_bytes, processed=len(units), done=True, report=str(REPORT), map=str(MAP_PATH), restore_ok=(restore_result or {}).get("ok"))
    print(json.dumps({"ok": ok, "bad": bad, "missing": missing, "checked_bytes": checked_bytes, "remote_asset_count": len(assets), "restore": restore_result}, indent=2), flush=True)
    restore_ok = bool(restore_result and restore_result.get("ok"))
    return 0 if (bad == 0 and missing == 0 and ok == len(units) and restore_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
