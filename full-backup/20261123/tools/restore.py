#!/usr/bin/env python3
"""Restore trees from this content-addressable backup.

Usage:
  python3 restore.py --backup-root . --dest /path/to/restore
  python3 restore.py --backup-root . --verify-only

Does not require network. Reconstructs every mapped source path from object
volumes + source-to-object map. Credential originals that were excluded are
not restored (see manifests/credential_exclusions.json); sanitized copies
are restored beside a .sanitized suffix note in the map.
"""
from __future__ import annotations
import argparse, gzip, hashlib, json, os, sys, tarfile
from pathlib import Path

CHUNK = 1024 * 1024

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def load_json(p: Path):
    return json.loads(p.read_text())

def extract_volumes(backup: Path, cas: Path) -> None:
    vol_man = load_json(backup / "manifests" / "volume_manifest.json")
    cas.mkdir(parents=True, exist_ok=True)
    for vol in vol_man.get("volumes", []):
        if vol.get("type") == "tar_gz_volume":
            p = backup / "volumes" / vol["name"]
            if not p.exists():
                p = Path(vol["path"])
            got = sha256_file(p)
            if got != vol["sha256"]:
                raise SystemExit(f"volume hash mismatch: {p} {got} != {vol['sha256']}")
            with tarfile.open(p, "r:gz") as t:
                t.extractall(cas.parent)
        elif vol.get("type") == "split_object":
            dest = cas / vol["sha256"][:2] / vol["sha256"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            parts = sorted(vol["parts"], key=lambda x: x["index"])
            with open(dest, "wb") as out:
                for part in parts:
                    pp = backup / "volumes" / part["name"]
                    if not pp.exists():
                        pp = Path(part["path"])
                    got = sha256_file(pp)
                    if got != part["sha256"]:
                        raise SystemExit(f"part hash mismatch: {pp}")
                    out.write(pp.read_bytes())
            got = sha256_file(dest)
            if got != vol["sha256"]:
                raise SystemExit(f"reassembled object hash mismatch {vol['sha256']}")

def iter_map(backup: Path):
    p = backup / "manifests" / "source_to_object_map.jsonl.gz"
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)

def restore(backup: Path, dest: Path, verify_only: bool) -> None:
    cas = backup / "cas"
    objects = cas / "objects"
    if not any(objects.glob("*/*")):
        extract_volumes(backup, objects)
    n = 0
    missing = 0
    for rec in iter_map(backup):
        typ = rec.get("type")
        rel = rec.get("restore_rel") or rec.get("rel_under_source")
        source_id = rec.get("source_id")
        target = dest / source_id / rel
        if typ == "symlink":
            if verify_only:
                n += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                continue
            os.symlink(rec.get("symlink_target") or "", target)
            n += 1
            continue
        if typ != "file":
            continue
        sha = rec.get("sha256")
        if not sha:
            # excluded (credentials, unreadable)
            missing += 1
            continue
        obj = objects / sha[:2] / sha
        if not obj.exists():
            raise SystemExit(f"missing object {sha} for {rec.get('path')}")
        if verify_only:
            n += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            import shutil
            shutil.copyfile(obj, target)
            if rec.get("mode"):
                try:
                    os.chmod(target, rec["mode"])
                except OSError:
                    pass
        n += 1
    print(f"restored_or_verified={n} excluded_or_unmapped={missing} dest={dest}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup-root", default=".")
    ap.add_argument("--dest", default="./restored")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()
    restore(Path(args.backup_root).resolve(), Path(args.dest).resolve(), args.verify_only)

if __name__ == "__main__":
    main()
