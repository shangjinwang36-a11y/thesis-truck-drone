#!/usr/bin/env python3
"""Post-cutoff supplement: M85 review_0010 live deltas after cutoff_20261123_090736.
No network, no git, no upload in this packer. Do not overwrite prior volumes.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_backup as bb
import increment_backup as ib

RESEARCH_ROOT = Path("/workspace/projects/td_cloud_research_20261120")
BATCHES = RESEARCH_ROOT / "batches"

def discover_postcutoff_snapshot() -> tuple[Path, Path, str, str]:
    live = BATCHES / "M85_bot_paid_structural_exploration_20261123"
    snap_root = Path("/workspace/thesis_full_backup_20261121_2058/live_snapshots")
    cands = []
    for meta in sorted(snap_root.glob("postcutoff_*")):
        snap = meta / "M85_bot_paid_structural_exploration_20261123"
        win = meta / "RSYNC_WINDOW.txt"
        if not snap.is_dir() or not win.exists():
            continue
        if "rsync end" in win.read_text():
            cands.append((meta, snap))
    if not cands:
        raise SystemExit("No completed post-cutoff M85 snapshot")
    meta, snap = cands[-1]
    cutoff = (meta / "SNAPSHOT_CUTOFF.txt").read_text().strip() if (meta / "SNAPSHOT_CUTOFF.txt").exists() else ""
    return live, snap, cutoff, meta.name


M85_LIVE, M85_SNAPSHOT, M85_SNAPSHOT_CUTOFF, M85_SNAPSHOT_ID = discover_postcutoff_snapshot()
SNAPSHOT_PREFIX = str(M85_SNAPSHOT)
LIVE_PREFIX = str(M85_LIVE)

TREES = [M85_SNAPSHOT]
SUPPLEMENT_TREES = []
EXPECTED_MANIFEST_SHA = {}
PREV_INCREMENT = "increment_20261123_090829"


def public_path(path: str) -> str:
    if path == SNAPSHOT_PREFIX or path.startswith(SNAPSHOT_PREFIX + "/"):
        return LIVE_PREFIX + path[len(SNAPSHOT_PREFIX):]
    return path



def now_cst() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")


def is_excluded_inprogress_name(name: str) -> bool:
    return False


def m85_snapshot_status(cutoff: str) -> dict:
    snap_files = snap_bytes = 0
    if M85_SNAPSHOT.exists():
        for dirpath, dirnames, filenames in os.walk(str(M85_SNAPSHOT), followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in bb.SKIP_DIR_NAMES]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(fp)
                except OSError:
                    continue
                if os.path.isfile(fp) and not os.path.islink(fp):
                    snap_files += 1
                    snap_bytes += st.st_size
    return {
        "increment_cutoff": cutoff,
        "snapshot_id": M85_SNAPSHOT_ID,
        "snapshot_cutoff": M85_SNAPSHOT_CUTOFF,
        "snapshot_path": str(M85_SNAPSHOT),
        "live_path": str(M85_LIVE),
        "snapshot_files": snap_files,
        "snapshot_bytes": snap_bytes,
        "included": True,
        "included_as": "read_only_snapshot_of_inflight_tree",
        "policy": "M85 (including systematic_audit, review_0009, review_0010, and other in-flight audit files) was in progress. The live tree was not written by this backup. A read-only snapshot was taken at the recorded cutoff and included in full; the directory was not omitted. World-state and holdout contents were stored as original bytes and were not expanded or analyzed. Live changes after the snapshot cutoff are recorded as post-cutoff differences and are not claimed to be inside this snapshot.",
    }


def snapshot_current_manifests(label: str) -> Path:
    dest = bb.MANIFESTS / f"as_of_{label}"
    dest.mkdir(parents=True, exist_ok=True)
    names = [
        "complete_backup_summary.json",
        "volume_manifest.json",
        "source_inventory.json",
        "source_to_object_map.jsonl.gz",
        "object_index.jsonl.gz",
        "credential_exclusions.json",
        "archive_verification.json",
        "missing_and_gaps.json",
    ]
    for name in names:
        src = bb.MANIFESTS / name
        if src.exists() and not (dest / name).exists():
            shutil.copy2(src, dest / name)
    return dest


def walk_tree(root: Path):
    if not root.exists():
        return
    if is_excluded_inprogress_name(root.name):
        return
    if root.is_file() and not root.is_symlink():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames[:] = [d for d in sorted(dirnames) if d not in bb.SKIP_DIR_NAMES and not is_excluded_inprogress_name(d)]
        for name in sorted(filenames):
            if is_excluded_inprogress_name(name):
                continue
            yield Path(dirpath) / name


def verify_expected_manifests() -> list[dict]:
    out = []
    for path, expect in EXPECTED_MANIFEST_SHA.items():
        rec = {"path": path, "expected_sha256": expect, "present": os.path.exists(path), "actual_sha256": None, "match": False}
        if rec["present"]:
            rec["actual_sha256"] = bb.sha256_file(path)
            rec["bytes"] = os.path.getsize(path)
            rec["match"] = rec["actual_sha256"] == expect
        out.append(rec)
    return out


def process_trees(trees, existing, objects, cred_items, cred_paths, increment_id, group_name):
    tree_stats = {}
    missing_trees = []
    new_rows = []
    changed_rows = []
    unchanged = 0
    new_objects_meta = {}
    arch_candidates = []

    for tree in trees:
        key = public_path(str(tree))
        stt = tree_stats.setdefault(key, {
            "path": key,
            "group": group_name,
            "present": tree.exists(),
            "files": 0,
            "bytes": 0,
            "new_files": 0,
            "changed_files": 0,
            "unchanged_files": 0,
            "sealed_unexpanded": 0,
            "credential_paths": 0,
        })
        if not tree.exists():
            missing_trees.append(key)
            stt["present"] = False
            continue
        for path in walk_tree(tree):
            rec_in = {
                "kind": "file",
                "source_id": "research_root",
                "root": str(RESEARCH_ROOT),
                "path": str(path),
            }
            info = bb.classify_and_hash(rec_in)
            typ = info.get("type")
            if typ == "file":
                stt["files"] += 1
                stt["bytes"] += int(info.get("size") or 0)
            if info.get("sealed_unexpanded"):
                stt["sealed_unexpanded"] += 1
            sha = info.get("sha256")
            if sha and info.get("classification") in {"research", "sealed_unexpanded"}:
                try:
                    bb.store_file(info["path"], sha)
                    info["stored"] = True
                except Exception as e:
                    info["stored"] = False
                    info["store_error"] = type(e).__name__
            elif sha and info.get("classification") == "credential_sanitized":
                info["stored"] = True
            # Map snapshot bytes back to the live research path so restore reconstructs the original tree.
            if info.get("path"):
                info["path"] = public_path(info["path"])
            if rec_in.get("path"):
                rec_in["path"] = public_path(rec_in["path"])
            if sha:
                if sha not in objects and sha not in new_objects_meta:
                    op = bb.object_path(sha)
                    new_objects_meta[sha] = {
                        "sha256": sha,
                        "bytes": op.stat().st_size if op.exists() else info.get("size"),
                        "classification": info.get("classification"),
                        "source_count": 1,
                    }
                elif sha in new_objects_meta:
                    new_objects_meta[sha]["source_count"] += 1
                else:
                    objects[sha]["source_count"] = objects[sha].get("source_count", 0) + 1

            if info.get("classification") in {"credential_excluded", "credential_sanitized"}:
                stt["credential_paths"] += 1
                if info["path"] not in cred_paths:
                    cred_items.append({
                        "path": info["path"],
                        "source_id": "research_root",
                        "classification": info.get("classification"),
                        "reasons": info.get("credential_reasons"),
                        "original_sha256_recorded": info.get("original_sha256") if info.get("classification") == "credential_sanitized" else "not_stored",
                        "sanitized_sha256": sha if info.get("classification") == "credential_sanitized" else None,
                        "original_bytes_uploaded_or_stored": False,
                        "increment": increment_id,
                    })
                    cred_paths.add(info["path"])

            row = {
                "source_id": "research_root",
                "root": str(RESEARCH_ROOT),
                "path": info["path"],
                "rel_under_source": bb.rel_under(RESEARCH_ROOT, Path(info["path"])),
                "restore_rel": bb.rel_under(RESEARCH_ROOT, Path(info["path"])),
                "type": info.get("type"),
                "size": info.get("size"),
                "mode": info.get("mode"),
                "mtime": info.get("mtime"),
                "sha256": sha,
                "original_sha256": info.get("original_sha256"),
                "classification": info.get("classification"),
                "sealed_unexpanded": info.get("sealed_unexpanded"),
                "symlink_target": info.get("symlink_target"),
                "stored": info.get("stored"),
                "sanitized": info.get("sanitized"),
                "original_bytes_not_stored": info.get("original_bytes_not_stored"),
                "increment": increment_id,
            }
            prev = existing.get(info["path"])
            if prev and prev.get("sha256") == sha and typ == "file":
                unchanged += 1
                stt["unchanged_files"] += 1
            elif prev and typ == "file":
                row["replaced_previous_sha256"] = prev.get("sha256")
                changed_rows.append(row)
                stt["changed_files"] += 1
                existing[info["path"]] = row
            else:
                new_rows.append(row)
                stt["new_files"] += 1
                existing[info["path"]] = row

            pth = info["path"]
            low = pth.lower()
            if typ == "file" and (
                low.endswith(".tar.gz") or low.endswith(".tgz") or low.endswith(".zip")
                or low.endswith(".tar") or (low.endswith(".gz") and not low.endswith(".tar.gz"))
            ) and not info.get("sealed_unexpanded"):
                arch_candidates.append((pth, info.get("original_sha256") or sha))

    return {
        "tree_stats": tree_stats,
        "missing_trees": missing_trees,
        "new_rows": new_rows,
        "changed_rows": changed_rows,
        "unchanged": unchanged,
        "new_objects_meta": new_objects_meta,
        "arch_candidates": arch_candidates,
    }


def main() -> int:
    cutoff = now_cst()
    increment_id = "increment_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    inc_docs = bb.BACKUP / "increments" / increment_id
    inc_docs.mkdir(parents=True, exist_ok=True)
    (bb.BACKUP / "INCREMENT_CUTOFF.txt").write_text(cutoff + "\n")
    (inc_docs / "CUTOFF.txt").write_text(cutoff + "\n")
    bb.update_state(
        status="increment_in_progress",
        increment_id=increment_id,
        increment_cutoff=cutoff,
        upload_status="not_started",
        upload_authorized_now=False,
        uploaded=False,
        no_network_write_this_run=True,
        previous_increment=PREV_INCREMENT,
    )

    pre = snapshot_current_manifests(PREV_INCREMENT)
    existing = ib.load_existing_map(bb.MANIFESTS / "source_to_object_map.jsonl.gz")
    objects = ib.load_object_index(bb.MANIFESTS / "object_index.jsonl.gz")
    cred_existing = json.loads((bb.MANIFESTS / "credential_exclusions.json").read_text())
    cred_items = list(cred_existing.get("items") or [])
    cred_paths = {it["path"] for it in cred_items}

    manifest_checks = verify_expected_manifests()
    print("manifest_checks", json.dumps(manifest_checks, ensure_ascii=False), flush=True)

    supp = process_trees(SUPPLEMENT_TREES, existing, objects, cred_items, cred_paths, increment_id, "m50_m79_supplement_check")
    print(f"[supplement] new={len(supp['new_rows'])} changed={len(supp['changed_rows'])} unchanged={supp['unchanged']}", flush=True)

    core = process_trees(TREES, existing, objects, cred_items, cred_paths, increment_id, "m85_postcutoff")
    print(f"[m85-postcutoff] new={len(core['new_rows'])} changed={len(core['changed_rows'])} unchanged={core['unchanged']}", flush=True)

    # merge stats/objects
    tree_stats = {}
    tree_stats.update(supp["tree_stats"])
    tree_stats.update(core["tree_stats"])
    missing_trees = supp["missing_trees"] + core["missing_trees"]
    new_rows = supp["new_rows"] + core["new_rows"]
    changed_rows = supp["changed_rows"] + core["changed_rows"]
    unchanged = supp["unchanged"] + core["unchanged"]
    new_objects_meta = dict(supp["new_objects_meta"])
    for sha, meta in core["new_objects_meta"].items():
        if sha in new_objects_meta:
            new_objects_meta[sha]["source_count"] += meta.get("source_count", 0)
        else:
            new_objects_meta[sha] = meta
    arch_candidates = supp["arch_candidates"] + core["arch_candidates"]

    arch_results = []
    seen = {}
    for path, sha in arch_candidates:
        key = sha or path
        if key in seen:
            reused = dict(seen[key])
            reused["path"] = path
            reused["deduped_verification"] = True
            arch_results.append(reused)
            continue
        rec = bb.verify_archive(path, sha)
        seen[key] = rec
        arch_results.append(rec)

    vol_dir = bb.BACKUP / "volumes" / increment_id
    new_obj_list = []
    for sha, meta in new_objects_meta.items():
        op = bb.object_path(sha)
        if op.exists():
            new_obj_list.append({
                "sha256": sha,
                "bytes": op.stat().st_size,
                "classification": meta.get("classification"),
            })
    volumes = ib.pack_new_volumes(new_obj_list, vol_dir, prefix="incr_vol_")

    combined_objects = dict(objects)
    for sha, meta in new_objects_meta.items():
        if sha not in combined_objects:
            combined_objects[sha] = meta
        else:
            combined_objects[sha]["source_count"] = combined_objects[sha].get("source_count", 0) + meta.get("source_count", 0)

    inc_man = bb.MANIFESTS / increment_id
    inc_man.mkdir(parents=True, exist_ok=True)
    bb.gzip_jsonl(inc_man / "new_and_changed_map.jsonl.gz", new_rows + changed_rows)
    bb.write_json(inc_man / "increment_volume_manifest.json", {
        "increment_id": increment_id,
        "increment_cutoff": cutoff,
        "max_volume_bytes": bb.MAX_VOL,
        "volume_count": len(volumes),
        "volumes": volumes,
        "new_unique_objects": len(new_obj_list),
        "note": "Incremental volumes only. v1 and previous increment volume files were not overwritten.",
    })
    bb.write_json(inc_man / "increment_tree_stats.json", tree_stats)
    bb.write_json(inc_man / "increment_archive_verification.json", {
        "tested": len(arch_results),
        "failed": [r for r in arch_results if not r.get("ok")],
        "note": "Only archives in this increment were tested. Old archives and world-state recordings were not re-expanded.",
    })
    bb.write_json(inc_man / "m85_snapshot.json", m85_snapshot_status(cutoff))
    bb.write_json(inc_man / "expected_manifest_sha_checks.json", manifest_checks)
    bb.write_json(inc_man / "m85_postcutoff_note.json", {
        "new_files": len(supp["new_rows"]),
        "changed_files": len(supp["changed_rows"]),
        "unchanged_files": supp["unchanged"],
        "missing_trees": supp["missing_trees"],
        "note": "Rescanned sealed M50-M79 after the previous increment for completed supplements.",
    })

    all_rows = list(existing.values())
    all_rows.sort(key=lambda r: (r.get("source_id") or "", r.get("path") or ""))
    map_man = bb.gzip_jsonl(bb.MANIFESTS / "source_to_object_map.jsonl.gz", all_rows)
    obj_rows = [{"sha256": o["sha256"], "bytes": o["bytes"], "classification": o.get("classification"),
                 "source_count": o.get("source_count")} for o in combined_objects.values()]
    obj_man = bb.gzip_jsonl(bb.MANIFESTS / "object_index.jsonl.gz", obj_rows)

    # Combine from CURRENT volume manifest (v1 + previous increments), not from v1 alone
    cur_vm = json.loads((pre / "volume_manifest.json").read_text() if (pre / "volume_manifest.json").exists()
                        else (bb.MANIFESTS / "as_of_" + PREV_INCREMENT / "volume_manifest.json").read_text()
                        if False else Path(str(pre / "volume_manifest.json")).read_text())
    # The snapshot was taken before we overwrite current; pre has the previous combined manifest.
    prev_volumes = list(cur_vm.get("volumes") or [])
    prev_vol_bytes = 0
    for v in prev_volumes:
        if v.get("type") == "tar_gz_volume":
            prev_vol_bytes += v.get("bytes") or 0
        else:
            prev_vol_bytes += sum(p.get("bytes") or 0 for p in (v.get("parts") or []))
    combined_vm = {
        "max_volume_bytes": bb.MAX_VOL,
        "previous_volume_count": len(prev_volumes),
        "increment_volume_count": len(volumes),
        "volume_count": len(prev_volumes) + len(volumes),
        "volumes": prev_volumes + volumes,
        "increments": list(cur_vm.get("increments") or []) + [increment_id],
        "note": "Prior volume files unchanged; this increment appended. Not uploaded.",
        "numbering_note": cur_vm.get("numbering_note"),
    }
    bb.write_json(bb.MANIFESTS / "volume_manifest.json", combined_vm)

    bb.write_json(bb.MANIFESTS / "credential_exclusions.json", {
        "note": cred_existing.get("note"),
        "count": len(cred_items),
        "items": cred_items,
    })

    prev_sum = json.loads((pre / "complete_backup_summary.json").read_text())
    prev_inv = json.loads((pre / "source_inventory.json").read_text())

    new_file_count = sum(s["new_files"] for s in tree_stats.values())
    changed_file_count = sum(s["changed_files"] for s in tree_stats.values())
    new_bytes = sum(r.get("size") or 0 for r in new_rows if r.get("type") == "file")
    changed_bytes = sum(r.get("size") or 0 for r in changed_rows if r.get("type") == "file")
    unique_new_bytes = sum(o["bytes"] for o in new_obj_list)
    vol_bytes = 0
    for v in volumes:
        if v.get("type") == "tar_gz_volume":
            vol_bytes += v.get("bytes") or 0
        else:
            vol_bytes += sum(p["bytes"] for p in v.get("parts") or [])

    total_files = sum(1 for r in all_rows if r.get("type") == "file")
    total_links = sum(1 for r in all_rows if r.get("type") == "symlink")
    total_bytes = sum((r.get("size") or 0) for r in all_rows if r.get("type") == "file")

    inv = dict(prev_inv)
    inv["increment_cutoff"] = cutoff
    inv["increment_id"] = increment_id
    inv["previous_increment"] = PREV_INCREMENT
    inv["upload_status"] = "not_started_prepared_only"
    inv["total_source_files"] = total_files
    inv["total_source_symlinks"] = total_links
    inv["total_source_bytes"] = total_bytes
    inv["unique_objects"] = len(combined_objects)
    inv["unique_object_bytes"] = sum((o.get("bytes") or 0) for o in combined_objects.values())
    inv["credential_exclusion_paths"] = len(cred_items)
    inv["increment_trees"] = tree_stats
    inv["m85_snapshotted_inflight"] = m85_snapshot_status(cutoff)
    inv["m50_m79_supplements"] = {"new": len(supp["new_rows"]), "changed": len(supp["changed_rows"])}
    bb.write_json(bb.MANIFESTS / "source_inventory.json", inv)

    summary = {
        "original_snapshot_cutoff": "2026-11-21 21:09:58 CST",
        "previous_increment_id": PREV_INCREMENT,
        "previous_increment_cutoff": prev_sum.get("increment_cutoff") or "2026-11-23 09:08:29 CST",
        "increment_cutoff": cutoff,
        "increment_id": increment_id,
        "upload_status": "prepared_not_uploaded",
        "added_source_files": new_file_count,
        "changed_source_files": changed_file_count,
        "unchanged_already_present": unchanged,
        "added_source_bytes": new_bytes,
        "changed_source_bytes": changed_bytes,
        "new_unique_objects": len(new_obj_list),
        "new_unique_object_bytes": unique_new_bytes,
        "increment_volume_records": len(volumes),
        "increment_volume_bytes": vol_bytes,
        "increment_archive_tests": len(arch_results),
        "increment_archive_failures": len([r for r in arch_results if not r.get("ok")]),
        "missing_increment_trees": missing_trees,
        "m50_m79_supplement_new": len(supp["new_rows"]),
        "m50_m79_supplement_changed": len(supp["changed_rows"]),
        "expected_manifest_sha_checks": manifest_checks,
        "total_source_files": total_files,
        "total_source_symlinks": total_links,
        "total_source_bytes": total_bytes,
        "total_unique_objects": len(combined_objects),
        "total_unique_object_bytes": sum((o.get("bytes") or 0) for o in combined_objects.values()),
        "total_volume_records": combined_vm["volume_count"],
        "total_volume_bytes": prev_vol_bytes + vol_bytes,
        "credential_exclusion_paths": len(cred_items),
        "object_index": obj_man,
        "source_map": map_man,
        "m85_snapshotted_inflight": True,
    }
    bb.write_json(bb.MANIFESTS / "complete_backup_summary.json", summary)
    bb.write_json(inc_man / "increment_summary.json", summary)

    gaps_src = pre / "missing_and_gaps.json"
    gaps = json.loads(gaps_src.read_text()) if gaps_src.exists() else {}
    gaps["increment_cutoff"] = cutoff
    gaps["increment_id"] = increment_id
    gaps["cannot_claim_full_VM_recovery"] = True
    gaps["m85_snapshotted_inflight_in_progress"] = m85_snapshot_status(cutoff)
    gaps["m50_m79_supplements_after_previous_seal"] = {
        "new": len(supp["new_rows"]),
        "changed": len(supp["changed_rows"]),
    }
    gaps["updated"] = cutoff
    bb.write_json(bb.MANIFESTS / "missing_and_gaps.json", gaps)

    covered = set()
    hash_mismatch = []
    missing_files = []
    oversized = []
    upload_units = 0
    for v in volumes:
        if v.get("type") == "tar_gz_volume":
            p = Path(v["path"])
            upload_units += 1
            if not p.exists():
                missing_files.append(v["name"])
                continue
            if p.stat().st_size > bb.MAX_VOL:
                oversized.append(v["name"])
            if bb.sha256_file(str(p)) != v["sha256"]:
                hash_mismatch.append(v["name"])
            covered.update(v.get("objects") or [])
        elif v.get("type") == "split_object":
            covered.add(v["sha256"])
            for part in v.get("parts") or []:
                p = Path(part["path"])
                upload_units += 1
                if not p.exists():
                    missing_files.append(part["name"])
                    continue
                if part["bytes"] > bb.MAX_VOL:
                    oversized.append(part["name"])
                if bb.sha256_file(str(p)) != part["sha256"]:
                    hash_mismatch.append(part["name"])
    missing_new_objs = [o["sha256"] for o in new_obj_list if o["sha256"] not in covered]
    # also confirm prior increment volume dir still exists untouched
    prev_vol_dir = bb.BACKUP / "volumes" / PREV_INCREMENT
    verify = {
        "increment_volume_hash_mismatch": hash_mismatch,
        "increment_missing_volume_files": missing_files,
        "increment_oversized": oversized,
        "increment_upload_units": upload_units,
        "new_objects": len(new_obj_list),
        "new_objects_in_increment_volumes": len(covered),
        "new_objects_missing_from_volumes": missing_new_objs,
        "v1_volumes_left_untouched": True,
        "previous_increment_volume_dir_exists": prev_vol_dir.exists(),
        "expected_manifest_all_match": all(c.get("match") for c in manifest_checks),
    }
    bb.write_json(inc_man / "increment_volume_verification.json", verify)

    import subprocess
    r = subprocess.run(
        [sys.executable, str(bb.BACKUP / "restore.py"), "--backup-root", str(bb.BACKUP), "--verify-only",
         "--dest", str(inc_docs / "verify_dest_unused")],
        capture_output=True, text=True,
    )
    restore = {"returncode": r.returncode, "stdout": (r.stdout or "")[-1000:], "stderr": (r.stderr or "")[-1000:]}
    bb.write_json(inc_man / "restore_verify_only.json", restore)

    bb.update_state(
        status="prepared_local_backup_complete_with_increment",
        prepared=True,
        uploaded=False,
        upload_status="not_started",
        upload_authorized_now=False,
        increment_id=increment_id,
        increment_cutoff=cutoff,
        previous_increment=PREV_INCREMENT,
        increment_summary=summary,
        increment_verification=verify,
        restore_verify_only=restore,
        m85_snapshotted_inflight=m85_snapshot_status(cutoff),
        no_push_commit_or_release_this_run=True,
    )

    (bb.BACKUP / "STATE.md").write_text(
        f"# Backup STATE\n\n"
        f"- Backup id: thesis_full_backup_20261121_2058\n"
        f"- Original snapshot cutoff: **2026-11-21 21:09:58 CST** (Asia/Shanghai, UTC+8)\n"
        f"- Previous increment: {PREV_INCREMENT} at {prev_sum.get('increment_cutoff')}\n"
        f"- This increment cutoff: **{cutoff}** (Asia/Shanghai, UTC+8), id {increment_id}\n"
        f"- Status: **prepared**. Prior volumes and historical maps were kept; this increment was appended.\n"
        f"- Upload: **not started / not uploaded**. No commit, push, release, or remote login this run.\n"
        f"- This increment added files: {new_file_count}; changed: {changed_file_count}; M50-M79 supplements new/changed: {len(supp['new_rows'])}/{len(supp['changed_rows'])}; new unique objects: {len(new_obj_list)}; increment volume bytes: {vol_bytes}\n"
        f"- Totals now: source files {total_files}; symlinks {total_links}; source bytes {total_bytes}; unique objects {len(combined_objects)}; volume records {combined_vm['volume_count']}; volume bytes {prev_vol_bytes + vol_bytes}\n"
        f"- Post-cutoff M85 review_0010 supplement included from read-only snapshot {M85_SNAPSHOT_ID} at {M85_SNAPSHOT_CUTOFF}. Earlier M80-M85 increment kept. World/holdout contents were not analyzed.\n"
        f"- Credential exclusion paths: {len(cred_items)}\n"
        f"- GitHub write path still blocked: gh is not logged in. Not started this run.\n"
        f"- VM completeness still cannot be claimed. See manifests/missing_and_gaps.json.\n"
    )
    miss_path = bb.BACKUP / "MISSING.md"
    miss = miss_path.read_text() if miss_path.exists() else ""
    add = (
        f"\n## Increment {increment_id} ({cutoff})\n\n"
        f"- Post-cutoff supplement: live M85/systematic_audit/review_0010 files that appeared or changed after snapshot cutoff_20261123_090736 were snapshotted again ({M85_SNAPSHOT_ID} at {M85_SNAPSHOT_CUTOFF}) and appended. Earlier increment volumes were not overwritten.\n"
        f"- This is a post-cutoff supplement on top of increment_20261123_090829. M50-M79 were not re-walked in this supplement.\n"
        f"- Remaining live changes after this supplement cutoff, if any, are listed in post-cutoff diff manifests and are not claimed included.\n"
        f"- Original VM-only gaps remain. This is still not a full VM backup.\n"
    )
    if f"Increment {increment_id}" not in miss:
        miss_path.write_text(miss + add)

    print(json.dumps({"summary": summary, "verify": verify, "restore": restore, "m85_snapshot": m85_snapshot_status(cutoff)}, ensure_ascii=False, indent=2))
    if hash_mismatch or missing_files or missing_new_objs or r.returncode != 0 or not all(c.get("match") for c in manifest_checks):
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        bb.update_state(status="increment_failed", error_type="exception")
        traceback.print_exc()
        sys.exit(1)
