#!/usr/bin/env python3
"""Incremental local backup update. No network, no git, no upload."""
from __future__ import annotations

import gzip
import json
import os
import shutil
import sys
import tarfile
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_backup as bb

INCREMENT_ID = None  # set in main
RESEARCH_ROOT = Path("/workspace/projects/td_cloud_research_20261120")
BATCHES = RESEARCH_ROOT / "batches"

INCREMENT_TREES = [
    BATCHES / "M50_bot_narrow_land_20261121" / "offline_bottleneck_20261121",
    BATCHES / "M51_bot_terminal_pickup_20261121",
    BATCHES / "M52_bot_terminal_shared_condition_20261121",
    BATCHES / "M53_bot_economic_feedback_20261121",
    BATCHES / "M54_bot_dependency_structure_20261121",
    BATCHES / "M55_bot_joint_payload_20261121",
    BATCHES / "M56_bot_paid_parent_joint_20261121",
    BATCHES / "M57_bot_paid_parent_condition_20261121",
]
EXCLUDED_IN_PROGRESS = [
    {
        "path": str(BATCHES / "M58_bot_joint_coverage_20261121"),
        "reason": "M58 main research just started; not claimed complete; excluded from this increment; do not race-write its files.",
    }
]


def now_cst() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")


def load_existing_map(path: Path) -> dict:
    recs = {}
    if not path.exists():
        return recs
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            recs[rec["path"]] = rec
    return recs


def load_object_index(path: Path) -> dict:
    objs = {}
    if not path.exists():
        return objs
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            objs[rec["sha256"]] = rec
    return objs


def walk_tree(root: Path):
    if not root.exists():
        return
    if root.is_file() and not root.is_symlink():
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames[:] = [d for d in sorted(dirnames) if d not in bb.SKIP_DIR_NAMES]
        # never enter M58 even if somehow nested
        dirnames[:] = [d for d in dirnames if d != "M58_bot_joint_coverage_20261121"]
        for name in sorted(filenames):
            yield Path(dirpath) / name


def pack_new_volumes(objects: list[dict], dest_dir: Path, prefix: str) -> list[dict]:
    """Pack only new objects into a new directory. Never overwrite existing volume files."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    MAX = bb.MAX_VOL
    volumes: list[dict] = []

    def write_tar(dest: Path, mems: list[dict]) -> int:
        with tarfile.open(dest, "w:gz", compresslevel=6) as t:
            for m in mems:
                op = bb.object_path(m["sha256"])
                arc = f"objects/{m['sha256'][:2]}/{m['sha256']}"
                t.add(op, arcname=arc, recursive=False)
        return dest.stat().st_size

    def split_obj(sha: str) -> dict:
        src = bb.object_path(sha)
        parts = []
        idx = 0
        with open(src, "rb") as f:
            while True:
                chunk = f.read(MAX)
                if not chunk:
                    break
                idx += 1
                name = f"{prefix}obj_{sha}.part.{idx:03d}"
                part_path = dest_dir / name
                if part_path.exists():
                    raise RuntimeError(f"refusing to overwrite existing part {part_path}")
                part_path.write_bytes(chunk)
                parts.append({
                    "name": name,
                    "path": str(part_path),
                    "bytes": len(chunk),
                    "sha256": bb.sha256_bytes(chunk),
                    "index": idx,
                })
        return {
            "type": "split_object",
            "sha256": sha,
            "bytes": src.stat().st_size,
            "parts": parts,
            "part_count": len(parts),
            "increment": True,
        }

    def flush(members: list[dict], vol_i: int) -> list[dict]:
        if not members:
            return []
        if len(members) == 1 and members[0]["bytes"] > MAX:
            return [split_obj(members[0]["sha256"])]
        name = f"{prefix}{vol_i:04d}.tar.gz"
        path = dest_dir / name
        if path.exists():
            raise RuntimeError(f"refusing to overwrite existing volume {path}")
        size = write_tar(path, members)
        if size > MAX and len(members) > 1:
            path.unlink()
            mid = max(1, len(members) // 2)
            out = flush(members[:mid], vol_i)
            out.extend(flush(members[mid:], vol_i + len(out)))
            return out
        if size > MAX and len(members) == 1:
            path.unlink()
            return [split_obj(members[0]["sha256"])]
        return [{
            "type": "tar_gz_volume",
            "name": name,
            "path": str(path),
            "bytes": size,
            "sha256": bb.sha256_file(str(path)),
            "object_count": len(members),
            "object_bytes": sum(m["bytes"] for m in members),
            "objects": [m["sha256"] for m in members],
            "increment": True,
        }]

    oversized = [o for o in objects if o["bytes"] > MAX]
    normal = [o for o in objects if o["bytes"] <= MAX]
    normal.sort(key=lambda x: x["sha256"])
    vol_i = 1
    for o in oversized:
        recs = flush([o], vol_i)
        volumes.extend(recs)
        vol_i += len(recs)
    current: list[dict] = []
    current_est = 0
    for o in normal:
        cost = bb.estimate_vol_cost(o["bytes"], o["sha256"])
        if current and current_est + cost > int(MAX * 0.92):
            recs = flush(current, vol_i)
            volumes.extend(recs)
            vol_i += len(recs)
            current = []
            current_est = 0
        current.append(o)
        current_est += cost
    if current:
        recs = flush(current, vol_i)
        volumes.extend(recs)
    return volumes


def preserve_v1() -> Path:
    v1 = bb.MANIFESTS / "v1_original_snapshot"
    if v1.exists():
        return v1
    v1.mkdir(parents=True, exist_ok=True)
    names = [
        "complete_backup_summary.json",
        "volume_manifest.json",
        "source_inventory.json",
        "source_to_object_map.jsonl.gz",
        "object_index.jsonl.gz",
        "credential_exclusions.json",
        "archive_verification.json",
        "missing_and_gaps.json",
        "M50_inclusion.json",
    ]
    for name in names:
        src = bb.MANIFESTS / name
        if src.exists():
            shutil.copy2(src, v1 / name)
    return v1


def m58_status() -> dict:
    p = BATCHES / "M58_bot_joint_coverage_20261121"
    files = 0
    bytes_ = 0
    names = []
    exists = p.exists()
    if exists:
        for dirpath, dirnames, filenames in os.walk(str(p), followlinks=False):
            if "__pycache__" in dirnames:
                dirnames.remove("__pycache__")
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(fp)
                except OSError:
                    continue
                if os.path.isfile(fp):
                    files += 1
                    bytes_ += st.st_size
                    names.append(os.path.relpath(fp, p))
    return {
        "path": str(p),
        "exists": exists,
        "files_at_cutoff": files,
        "bytes_at_cutoff": bytes_,
        "sample_names": names[:20],
        "included": False,
        "policy": "In-progress at increment cutoff; excluded; not claimed complete; reserved for a later increment. Source files were not written by this backup.",
    }


def main() -> int:
    global INCREMENT_ID
    cutoff = now_cst()
    INCREMENT_ID = "increment_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    inc_docs = bb.BACKUP / "increments" / INCREMENT_ID
    inc_docs.mkdir(parents=True, exist_ok=True)
    (bb.BACKUP / "INCREMENT_CUTOFF.txt").write_text(cutoff + "\n")
    (inc_docs / "CUTOFF.txt").write_text(cutoff + "\n")
    bb.update_state(
        status="increment_in_progress",
        increment_id=INCREMENT_ID,
        increment_cutoff=cutoff,
        upload_status="not_started",
        upload_authorized_now=False,
        uploaded=False,
        no_network_write_this_run=True,
    )

    v1 = preserve_v1()
    existing = load_existing_map(bb.MANIFESTS / "source_to_object_map.jsonl.gz")
    objects = load_object_index(bb.MANIFESTS / "object_index.jsonl.gz")
    cred_existing = json.loads((bb.MANIFESTS / "credential_exclusions.json").read_text())
    cred_items = list(cred_existing.get("items") or [])
    cred_paths = {it["path"] for it in cred_items}

    tree_stats = {}
    missing_trees = []
    new_rows = []
    changed_rows = []
    unchanged = 0
    new_objects_meta = {}
    arch_candidates = []
    n_seen = 0

    for tree in INCREMENT_TREES:
        sid = "research_root"
        key = str(tree)
        stt = tree_stats.setdefault(key, {
            "path": key,
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
            n_seen += 1
            rec_in = {
                "kind": "file",
                "source_id": sid,
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
                        "source_id": sid,
                        "classification": info.get("classification"),
                        "reasons": info.get("credential_reasons"),
                        "original_sha256_recorded": info.get("original_sha256") if info.get("classification") == "credential_sanitized" else "not_stored",
                        "sanitized_sha256": sha if info.get("classification") == "credential_sanitized" else None,
                        "original_bytes_uploaded_or_stored": False,
                        "increment": INCREMENT_ID,
                    })
                    cred_paths.add(info["path"])

            row = {
                "source_id": sid,
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
                "increment": INCREMENT_ID,
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

    # archive verify only new increment archives; do not re-extract old sealed world contents
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

    vol_dir = bb.BACKUP / "volumes" / INCREMENT_ID
    new_obj_list = []
    for sha, meta in new_objects_meta.items():
        op = bb.object_path(sha)
        if op.exists():
            new_obj_list.append({"sha256": sha, "bytes": op.stat().st_size, "classification": meta.get("classification")})
    volumes = pack_new_volumes(new_obj_list, vol_dir, prefix="incr_vol_")

    # combined maps: v1 objects + new
    combined_objects = dict(objects)
    for sha, meta in new_objects_meta.items():
        if sha not in combined_objects:
            combined_objects[sha] = meta
        else:
            combined_objects[sha]["source_count"] = combined_objects[sha].get("source_count", 0) + meta.get("source_count", 0)

    # write increment manifests
    inc_man = bb.MANIFESTS / INCREMENT_ID
    inc_man.mkdir(parents=True, exist_ok=True)
    bb.gzip_jsonl(inc_man / "new_and_changed_map.jsonl.gz", new_rows + changed_rows)
    bb.write_json(inc_man / "increment_volume_manifest.json", {
        "increment_id": INCREMENT_ID,
        "increment_cutoff": cutoff,
        "max_volume_bytes": bb.MAX_VOL,
        "volume_count": len(volumes),
        "volumes": volumes,
        "new_unique_objects": len(new_obj_list),
        "note": "Incremental volumes only. Original v1 volume files were not overwritten.",
    })
    bb.write_json(inc_man / "increment_tree_stats.json", tree_stats)
    bb.write_json(inc_man / "increment_archive_verification.json", {
        "tested": len(arch_results),
        "failed": [r for r in arch_results if not r.get("ok")],
        "note": "Only archives in this increment were tested. Old archives were not re-expanded.",
    })
    bb.write_json(inc_man / "m58_exclusion.json", m58_status())

    # combined current maps (do not modify v1 copies)
    all_rows = list(existing.values())
    # stable-ish order
    all_rows.sort(key=lambda r: (r.get("source_id") or "", r.get("path") or ""))
    map_man = bb.gzip_jsonl(bb.MANIFESTS / "source_to_object_map.jsonl.gz", all_rows)
    obj_rows = [{"sha256": o["sha256"], "bytes": o["bytes"], "classification": o.get("classification"),
                 "source_count": o.get("source_count")} for o in combined_objects.values()]
    obj_man = bb.gzip_jsonl(bb.MANIFESTS / "object_index.jsonl.gz", obj_rows)

    # combined volume manifest = v1 volumes + increment
    v1_vm = json.loads((v1 / "volume_manifest.json").read_text())
    combined_vm = {
        "max_volume_bytes": bb.MAX_VOL,
        "original_volume_count": len(v1_vm.get("volumes") or []),
        "increment_volume_count": len(volumes),
        "volume_count": len(v1_vm.get("volumes") or []) + len(volumes),
        "volumes": list(v1_vm.get("volumes") or []) + volumes,
        "increments": [INCREMENT_ID],
        "note": "v1 volume files unchanged; increment volumes appended. Each unit has sha256 for later remote verification. Not uploaded.",
        "numbering_note": v1_vm.get("numbering_note"),
    }
    bb.write_json(bb.MANIFESTS / "volume_manifest.json", combined_vm)

    # credentials combined
    bb.write_json(bb.MANIFESTS / "credential_exclusions.json", {
        "note": cred_existing.get("note"),
        "count": len(cred_items),
        "items": cred_items,
    })

    v1_sum = json.loads((v1 / "complete_backup_summary.json").read_text())
    v1_inv = json.loads((v1 / "source_inventory.json").read_text())

    new_file_count = sum(s["new_files"] for s in tree_stats.values())
    changed_file_count = sum(s["changed_files"] for s in tree_stats.values())
    new_bytes = sum(
        r.get("size") or 0 for r in new_rows if r.get("type") == "file"
    )
    changed_bytes = sum(
        r.get("size") or 0 for r in changed_rows if r.get("type") == "file"
    )
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
    unique_bytes = sum((o.get("bytes") or 0) for o in combined_objects.values() if bb.object_path(o["sha256"]).exists() or True)

    # inventory update
    inv = dict(v1_inv)
    inv["snapshot_cutoff"] = v1_inv.get("snapshot_cutoff")
    inv["increment_cutoff"] = cutoff
    inv["increment_id"] = INCREMENT_ID
    inv["upload_status"] = "not_started_prepared_only"
    inv["total_source_files"] = total_files
    inv["total_source_symlinks"] = total_links
    inv["total_source_bytes"] = total_bytes
    inv["unique_objects"] = len(combined_objects)
    inv["unique_object_bytes"] = sum((o.get("bytes") or 0) for o in combined_objects.values())
    inv["credential_exclusion_paths"] = len(cred_items)
    inv["increment_trees"] = tree_stats
    inv["m58_excluded"] = m58_status()
    inv["m50_offline_bottleneck_included"] = True
    bb.write_json(bb.MANIFESTS / "source_inventory.json", inv)

    summary = {
        "original_snapshot_cutoff": v1_sum.get("snapshot_cutoff"),
        "increment_cutoff": cutoff,
        "increment_id": INCREMENT_ID,
        "upload_status": "prepared_not_uploaded",
        "added_source_files": new_file_count,
        "changed_source_files": changed_file_count,
        "unchanged_already_in_v1": unchanged,
        "added_source_bytes": new_bytes,
        "changed_source_bytes": changed_bytes,
        "new_unique_objects": len(new_obj_list),
        "new_unique_object_bytes": unique_new_bytes,
        "increment_volume_records": len(volumes),
        "increment_volume_bytes": vol_bytes,
        "increment_archive_tests": len(arch_results),
        "increment_archive_failures": len([r for r in arch_results if not r.get("ok")]),
        "missing_increment_trees": missing_trees,
        "total_source_files": total_files,
        "total_source_symlinks": total_links,
        "total_source_bytes": total_bytes,
        "total_unique_objects": len(combined_objects),
        "total_unique_object_bytes": sum((o.get("bytes") or 0) for o in combined_objects.values()),
        "total_volume_records": combined_vm["volume_count"],
        "total_volume_bytes": (v1_sum.get("volume_bytes") or 0) + vol_bytes,
        "credential_exclusion_paths": len(cred_items),
        "object_index": obj_man,
        "source_map": map_man,
        "m58_excluded": True,
    }
    bb.write_json(bb.MANIFESTS / "complete_backup_summary.json", summary)
    bb.write_json(inc_man / "increment_summary.json", summary)

    # gaps: keep original VM gaps, add increment notes
    gaps = json.loads((v1 / "missing_and_gaps.json").read_text()) if (v1 / "missing_and_gaps.json").exists() else {}
    gaps["increment_cutoff"] = cutoff
    gaps["increment_id"] = INCREMENT_ID
    gaps["cannot_claim_full_VM_recovery"] = True
    gaps["m58_excluded_in_progress"] = m58_status()
    gaps["post_m50_offline_bottleneck_reserved_for_incremental"] = {
        "status": "included_in_this_increment",
        "files_seen": tree_stats.get(str(INCREMENT_TREES[0]), {}).get("files"),
    }
    gaps["updated"] = cutoff
    bb.write_json(bb.MANIFESTS / "missing_and_gaps.json", gaps)

    # verify all increment volume hashes and object coverage for NEW objects
    covered = set()
    hash_mismatch = []
    missing_files = []
    oversized = []
    for v in volumes:
        if v.get("type") == "tar_gz_volume":
            p = Path(v["path"])
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
                if not p.exists():
                    missing_files.append(part["name"])
                    continue
                if part["bytes"] > bb.MAX_VOL:
                    oversized.append(part["name"])
                if bb.sha256_file(str(p)) != part["sha256"]:
                    hash_mismatch.append(part["name"])
    missing_new_objs = [o["sha256"] for o in new_obj_list if o["sha256"] not in covered]
    verify = {
        "increment_volume_hash_mismatch": hash_mismatch,
        "increment_missing_volume_files": missing_files,
        "increment_oversized": oversized,
        "new_objects": len(new_obj_list),
        "new_objects_in_increment_volumes": len(covered),
        "new_objects_missing_from_volumes": missing_new_objs,
        "v1_volumes_left_untouched": True,
    }
    bb.write_json(inc_man / "increment_volume_verification.json", verify)

    # restore verify-only
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
        increment_id=INCREMENT_ID,
        increment_cutoff=cutoff,
        increment_summary=summary,
        increment_verification=verify,
        restore_verify_only=restore,
        m58_excluded=m58_status(),
        no_push_commit_or_release_this_run=True,
    )

    # human STATE.md (no shell backticks needed; this file is written by Python)
    (bb.BACKUP / "STATE.md").write_text(
        f"# Backup STATE\n\n"
        f"- Backup id: thesis_full_backup_20261121_2058\n"
        f"- Original snapshot cutoff: **{v1_sum.get('snapshot_cutoff')}** (Asia/Shanghai, UTC+8)\n"
        f"- Increment cutoff: **{cutoff}** (Asia/Shanghai, UTC+8), id {INCREMENT_ID}\n"
        f"- Status: **prepared** (v1 sealed volumes kept; increment volumes and updated maps added)\n"
        f"- Upload: **not started / not uploaded**. No commit, push, release, or remote login this run.\n"
        f"- This increment added files: {new_file_count}; changed: {changed_file_count}; new unique objects: {len(new_obj_list)}; increment volume bytes: {vol_bytes}\n"
        f"- Totals now: source files {total_files}; source bytes {total_bytes}; unique objects {len(combined_objects)}; volume records {combined_vm['volume_count']}\n"
        f"- M58 excluded as in-progress at cutoff (not claimed complete).\n"
        f"- Credential exclusion paths: {len(cred_items)}\n"
        f"- GitHub write path still blocked: gh is not logged in. Not started this run.\n"
        f"- VM completeness still cannot be claimed. See manifests/missing_and_gaps.json.\n"
    )
    miss_path = bb.BACKUP / "MISSING.md"
    miss = miss_path.read_text() if miss_path.exists() else ""
    add = (
        f"\n## Increment {INCREMENT_ID} ({cutoff})\n\n"
        f"- M50 offline_bottleneck, M51 (including real_cache_gate/mechanical_v2), and M52-M57 complete trees were added.\n"
        f"- M58_bot_joint_coverage_20261121 was excluded as in-progress at this increment cutoff and is not claimed complete.\n"
        f"- Original VM-only gaps remain. This is still not a full VM backup.\n"
    )
    if f"Increment {INCREMENT_ID}" not in miss:
        miss_path.write_text(miss + add)

    print(json.dumps({"summary": summary, "verify": verify, "restore": restore, "trees": tree_stats, "m58": m58_status()}, ensure_ascii=False, indent=2))
    if hash_mismatch or missing_files or missing_new_objs or r.returncode != 0:
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        bb.update_state(status="increment_failed", error_type="exception")
        traceback.print_exc()
        sys.exit(1)
