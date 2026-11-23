#!/usr/bin/env python3
"""Build a content-addressable, volume-split, restorable research backup.

Read-only on sources. No network writes. No CloudAgent. No experiment runs.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import time
import traceback
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BACKUP = Path("/workspace/thesis_full_backup_20261121_2058")
MANIFESTS = BACKUP / "manifests"
CAS = BACKUP / "cas" / "objects"
VOLUMES = BACKUP / "volumes"
DOCS = BACKUP / "docs"
TOOLS = BACKUP / "tools"
MAX_VOL = 45 * 1024 * 1024  # GitHub file warning is 50 MiB; stay under
HASH_CHUNK = 1024 * 1024
SANITIZED_PREFIX = "sanitized:"

SKIP_DIR_NAMES = {
    ".venv",
    "venv",
    "venv_r6",
    "venv314",
    ".venv-stats",
    "__pycache__",
    "node_modules",
    "thesis_full_backup_20261121_2058",
}

# Non-research / other-bot / personal trees never walked
EXCLUDED_ROOTS = {
    "/workspace/avatars",
    "/workspace/pptbot",
    "/workspace/routine-state",
    "/workspace/venv_r6",
    "/workspace/venv314",
    "/workspace/.venv-stats",
}

TREE_ROOTS = [
    ("research_root", "/workspace/projects/td_cloud_research_20261120"),
    ("source_project", "/workspace/projects/失败无人机卡车配送_20261119"),
    ("m46_handoff", "/workspace/M46_CURSOR_HANDOFF_20261121"),
    ("m47_actual_raw_audit", "/workspace/M47_ACTUAL_RAW_AUDIT_20261121"),
    ("m47_actual_registration_audit", "/workspace/M47_ACTUAL_REGISTRATION_AUDIT_20261121"),
    ("m47_actual_result_audit", "/workspace/M47_ACTUAL_RESULT_AUDIT_20261121"),
    ("m47_independent_audit", "/workspace/M47_INDEPENDENT_AUDIT_20261121"),
    ("m48_actual_independent_audit", "/workspace/M48_ACTUAL_INDEPENDENT_AUDIT_20261121"),
    ("m48_fair_control_audit", "/workspace/M48_FAIR_CONTROL_AUDIT_20261121"),
    ("m48_independent_registration_audit", "/workspace/M48_INDEPENDENT_REGISTRATION_AUDIT_20261121"),
    ("m49_independent_audit", "/workspace/M49_INDEPENDENT_AUDIT_20261121"),
    ("thesis_hub", "/workspace/thesis-hub"),
    ("thesis_prep", "/workspace/thesis-prep"),
    ("thesis_truck_drone_local", "/workspace/thesis-truck-drone"),
    ("tdbase", "/workspace/tdbase"),
    ("tddev", "/workspace/tddev"),
    ("tdwork", "/workspace/tdwork"),
    ("work_r6", "/workspace/work_r6"),
    ("research_dir", "/workspace/research"),
    ("round10_bugfix", "/workspace/round10-bugfix"),
    ("round10_baseline_test_src", "/workspace/round10-baseline-test-src"),
    ("r12_review", "/workspace/R12_review"),
    ("r13", "/workspace/R13"),
    ("xfer_20261119", "/workspace/xfer_20261119"),
    ("cloud_agent_transcripts", "/workspace/cloud-agent-transcripts"),
    ("cloud_review", "/workspace/cloud-review"),
    ("exports", "/workspace/exports"),
    ("codex_followup", "/workspace/codex_followup"),
    ("base_nom", "/workspace/base_nom"),
    ("new_nom", "/workspace/new_nom"),
    ("probe_p15", "/workspace/probe_p15"),
    ("qcheck_k12", "/workspace/qcheck_k12"),
    ("qcheck_p10", "/workspace/qcheck_p10"),
    ("smoke_p10", "/workspace/smoke_p10"),
    ("uploads_screenshots", "/workspace/uploads"),
    ("agent_assets", "/cursor/stores/user/grok-bot/agents/80a7a1e7-ab4c-4fa4-be04-d6b58ca45c46/assets"),
    ("cloud_store_bc4a385c", "/cursor/stores/bc-4a385c7b-5c4c-542a-97f4-11c345e9974e"),
]

WORKSPACE_LOOSE_PREFIXES = (
    "M46_",
    "M47_",
    "R1",
    "R2",
    "codex_",
    "composer_",
    "round10-",
    "same_truck_",
    "ep_check",
    "nom_only",
    "probe.py",
    "qcheck",
    "base_nom.log",
    "new_nom.log",
)

# Research filenames that mention token/password in an algorithmic sense, not credentials
RESEARCH_TOKEN_NAME_OK = re.compile(
    r"(body_token_flow|diagnose_token_flow|_tokenizer|pygments/token\.py|token_flow)",
    re.I,
)

CRED_NAME_RE = re.compile(
    r"""(?:^|\.)(
        env|env\.local|env\.production|netrc|npmrc|pypirc|
        git-credentials|credentials|credentials\.json|
        secrets\.json|secret\.json|id_rsa|id_dsa|id_ecdsa|id_ed25519|
        gh/hosts\.yml|auth\.json
    )$""",
    re.I | re.X,
)
CRED_NAME_HINT_RE = re.compile(
    r"(api[_-]?key|apikey|secret[_-]?key|private[_-]?key|\.pem$|\.key$|password|passwd|htpasswd|shadow)",
    re.I,
)

# Content patterns: record pattern NAME only, never the matched value
CONTENT_PATTERNS = [
    ("pem_private_key", re.compile(br"-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("github_pat", re.compile(br"github_pat_[A-Za-z0-9_]{20,}")),
    ("github_token_ghp", re.compile(br"ghp_[A-Za-z0-9]{20,}")),
    ("github_token_gho", re.compile(br"gho_[A-Za-z0-9]{20,}")),
    ("github_token_ghu", re.compile(br"ghu_[A-Za-z0-9]{20,}")),
    ("aws_access_key_id", re.compile(br"AKIA[0-9A-Z]{16}")),
    ("slack_token", re.compile(br"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("bearer_jwt_assign", re.compile(br"(?i)(api[_-]?key|secret|password|passwd|authorization)\s*[:=]\s*['\"]?(?:Bearer\s+)?[A-Za-z0-9_\-./+]{24,}")),
]

TEXT_EXT = {
    ".txt", ".md", ".py", ".json", ".jsonl", ".yml", ".yaml", ".toml", ".ini",
    ".cfg", ".conf", ".log", ".sh", ".bash", ".zsh", ".ps1", ".csv", ".tsv",
    ".xml", ".html", ".css", ".js", ".ts", ".env", ".rst", ".patch", ".diff",
    ".properties", ".service",
}

SEALED_DIR_PARTS = {"sealed_core", "sealed"}
SEALED_CASE_RE = re.compile(r"(?:^|[^0-9])(?:400[1-9]|401[0-9]|402[0-9]|4030|270701)(?:[^0-9]|$)")
# Only treat as sealed-case when the case id is a path component, not a hex hash filename
SEALED_COMPONENT_RE = re.compile(r"^(?:400[1-9]|401[0-9]|402[0-9]|4030|270701)(?:[_-].*)?$")

ARCHIVE_EXT = {".tar", ".gz", ".tgz", ".zip", ".bz2", ".xz"}


def now_cst() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")


def load_cutoff() -> str:
    p = BACKUP / "SNAPSHOT_CUTOFF.txt"
    if p.exists():
        return p.read_text().strip()
    return now_cst()


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def update_state(**kwargs) -> None:
    p = BACKUP / "STATE.json"
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
    data.update(kwargs)
    data["state_updated"] = now_cst()
    write_json(p, data)


def rel_under(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def is_sealed_path(path: str) -> bool:
    parts = Path(path).parts
    for part in parts:
        if part in SEALED_DIR_PARTS:
            return True
        if SEALED_COMPONENT_RE.match(part):
            return True
    return False


def cred_name_reason(path: str) -> str | None:
    name = os.path.basename(path)
    low = path.replace("\\", "/")
    if RESEARCH_TOKEN_NAME_OK.search(low):
        return None
    # do not treat algorithm token-flow or git pack files as credentials
    if name.endswith(".pack") or "/.git/" in low:
        return None
    if CRED_NAME_RE.search(name) or name in {".env", ".netrc", ".npmrc", ".pypirc", ".git-credentials"}:
        return "credential_filename"
    if name.endswith(".pem") or name.endswith(".key"):
        if "cacert.pem" in name or name == "cert.pem":
            return None
        return "key_or_pem_filename"
    if CRED_NAME_HINT_RE.search(name) and not RESEARCH_TOKEN_NAME_OK.search(name):
        # avoid flagging ordinary research logs named *password* if none; still flag obvious ones
        if re.search(r"(password|passwd|secret.?key|api.?key|private.?key)", name, re.I):
            return "credential_filename_hint"
    return None


def looks_text(path: str, size: int) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".so", ".o", ".pyc",
               ".whl", ".pack", ".idx", ".woff", ".ttf", ".otf", ".mp4", ".mov",
               ".bin", ".npy", ".npz"}:
        return False
    if ext in TEXT_EXT or ext == "":
        return size <= 2_000_000
    if ext in {".json", ".jsonl"}:
        return size <= 2_000_000
    return False


def scan_content_reasons(path: str, size: int) -> list[str]:
    """Return pattern NAMES only. Never return or log matched secret bytes."""
    reasons: list[str] = []
    try:
        with open(path, "rb") as f:
            data = f.read(min(size, 1_000_000) if size else 1_000_000)
    except Exception:
        return reasons
    for name, pat in CONTENT_PATTERNS:
        if pat.search(data):
            reasons.append(name)
    return reasons


def sanitize_bytes(data: bytes) -> bytes:
    """Replace secret-like values with a placeholder. Never echo the values."""
    out = data
    replacements = [
        (re.compile(br"-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED )?PRIVATE KEY-----.*?-----END (?:RSA |OPENSSH |EC |DSA |ENCRYPTED )?PRIVATE KEY-----", re.S),
         b"-----BEGIN PRIVATE KEY-----\n***REDACTED***\n-----END PRIVATE KEY-----\n"),
        (re.compile(br"github_pat_[A-Za-z0-9_]{20,}"), b"github_pat_***REDACTED***"),
        (re.compile(br"ghp_[A-Za-z0-9]{20,}"), b"ghp_***REDACTED***"),
        (re.compile(br"gho_[A-Za-z0-9]{20,}"), b"gho_***REDACTED***"),
        (re.compile(br"ghu_[A-Za-z0-9]{20,}"), b"ghu_***REDACTED***"),
        (re.compile(br"AKIA[0-9A-Z]{16}"), b"AKIA***REDACTED***"),
        (re.compile(br"xox[baprs]-[A-Za-z0-9-]{10,}"), b"xox***REDACTED***"),
        (re.compile(br"(?i)((?:api[_-]?key|secret|password|passwd|authorization)\s*[:=]\s*['\"]?(?:Bearer\s+)?)[A-Za-z0-9_\-./+]{24,}"),
         br"\1***REDACTED***"),
    ]
    for pat, repl in replacements:
        out = pat.sub(repl, out)
    return out


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_path(sha: str) -> Path:
    return CAS / sha[:2] / sha


def store_bytes(data: bytes, sha: str | None = None) -> str:
    sha = sha or sha256_bytes(data)
    dest = object_path(sha)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        dest.chmod(0o444)
    return sha


def store_file(src: str, sha: str | None = None) -> str:
    sha = sha or sha256_file(src)
    dest = object_path(sha)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
        dest.chmod(0o444)
    return sha


def list_workspace_loose() -> list[Path]:
    root = Path("/workspace")
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.is_symlink():
            if p.is_symlink() and not p.is_dir():
                name = p.name
                if name.startswith(WORKSPACE_LOOSE_PREFIXES) or name in {"codex-login.log"}:
                    out.append(p)
            continue
        name = p.name
        if name.startswith(WORKSPACE_LOOSE_PREFIXES) or name in {"codex-login.log"}:
            out.append(p)
    return out


def iter_entries():
    """Yield (source_id, root, path, is_symlink) for files and symlinks. Dirs implied."""
    for source_id, root_s in TREE_ROOTS:
        root = Path(root_s)
        if not root.exists():
            yield {"kind": "missing_root", "source_id": source_id, "root": root_s}
            continue
        if root.is_file() or root.is_symlink() and not root.is_dir():
            yield {"kind": "file", "source_id": source_id, "root": root_s, "path": str(root)}
            continue
        for dirpath, dirnames, filenames in os.walk(root_s, followlinks=False):
            dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIR_NAMES]
            # never walk into backup dest if nested
            dirnames[:] = [d for d in dirnames if "thesis_full_backup_20261121_2058" not in d]
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                yield {"kind": "file", "source_id": source_id, "root": root_s, "path": path}
    # workspace loose research files
    for p in list_workspace_loose():
        yield {"kind": "file", "source_id": "workspace_loose_research", "root": "/workspace", "path": str(p)}


def classify_and_hash(rec: dict) -> dict:
    path = rec["path"]
    out = dict(rec)
    out["sealed_unexpanded"] = bool(is_sealed_path(path))
    try:
        st = os.lstat(path)
    except OSError as e:
        out.update(type="unreadable", error=type(e).__name__, classification="unreadable", sha256=None, size=None)
        return out
    mode = stat.S_IMODE(st.st_mode)
    mtime = int(st.st_mtime)
    out.update(mode=mode, mtime=mtime, size=int(st.st_size), uid=st.st_uid, gid=st.st_gid)
    if stat.S_ISLNK(st.st_mode):
        try:
            target = os.readlink(path)
        except OSError:
            target = None
        out.update(type="symlink", symlink_target=target, classification="symlink", sha256=None)
        return out
    if not stat.S_ISREG(st.st_mode):
        out.update(type="special", classification="skipped_special", sha256=None)
        return out
    out["type"] = "file"
    name_reason = cred_name_reason(path)
    content_reasons: list[str] = []
    # Do not inspect sealed world contents. Path-name credential check still applies.
    if not out["sealed_unexpanded"] and looks_text(path, st.st_size):
        content_reasons = scan_content_reasons(path, st.st_size)
    reasons = ([name_reason] if name_reason else []) + content_reasons
    try:
        sha = sha256_file(path)
    except OSError as e:
        out.update(classification="unreadable", error=type(e).__name__, sha256=None)
        return out
    out["original_sha256"] = sha
    if reasons:
        out["credential_reasons"] = reasons  # pattern names only
        if out["sealed_unexpanded"]:
            # sealed + credential name: exclude original, do not sanitize by reading world
            out.update(classification="credential_excluded", sha256=None, stored=False)
            return out
        # Produce a sanitized public copy; do not store original bytes
        try:
            raw = Path(path).read_bytes()
            sanitized = sanitize_bytes(raw)
            if sanitized == raw:
                # could not safely sanitize (e.g. binary); exclude original only
                out.update(classification="credential_excluded", sha256=None, stored=False,
                            sanitize_note="pattern_hit_but_unchanged_excluded_without_original_bytes")
                return out
            s_sha = store_bytes(sanitized)
            out.update(classification="credential_sanitized", sha256=s_sha, stored=True,
                        sanitized=True, original_bytes_not_stored=True)
            return out
        except Exception as e:
            out.update(classification="credential_excluded", sha256=None, stored=False,
                        sanitize_note="sanitize_failed_" + type(e).__name__)
            return out
    # normal research (includes world flags / private visible state authorized for later public upload)
    cls = "sealed_unexpanded" if out["sealed_unexpanded"] else "research"
    out.update(classification=cls, sha256=sha)
    return out


def verify_archive(path: str, sha: str | None) -> dict:
    rec = {"path": path, "sha256": sha, "ok": False, "kind": None, "error": None, "members": None}
    low = path.lower()
    try:
        if low.endswith(".zip"):
            rec["kind"] = "zip"
            with zipfile.ZipFile(path) as z:
                bad = z.testzip()
                rec["members"] = len(z.infolist())
                if bad:
                    rec["error"] = "zip_member_failed"
                    return rec
            rec["ok"] = True
            return rec
        if low.endswith(".tar"):
            rec["kind"] = "tar"
            with tarfile.open(path, "r:") as t:
                rec["members"] = len(t.getmembers())
            rec["ok"] = True
            return rec
        if low.endswith(".tar.gz") or low.endswith(".tgz"):
            rec["kind"] = "tar.gz"
            with tarfile.open(path, "r:gz") as t:
                rec["members"] = len(t.getmembers())
            rec["ok"] = True
            return rec
        if low.endswith(".gz") and not (low.endswith(".tar.gz") or low.endswith(".tgz")):
            rec["kind"] = "gzip"
            import gzip as gz
            with gz.open(path, "rb") as f:
                while f.read(HASH_CHUNK):
                    pass
            rec["ok"] = True
            return rec
        rec["kind"] = "unknown"
        rec["error"] = "not_an_archive_tested_as_file_hash_only"
        rec["ok"] = True
        return rec
    except Exception as e:
        rec["error"] = type(e).__name__
        rec["ok"] = False
        return rec


def estimate_vol_cost(size: int, name: str) -> int:
    low = name.lower()
    if low.endswith((".gz", ".tgz", ".zip", ".png", ".jpg", ".jpeg", ".webp", ".pack", ".xz", ".bz2")):
        return int(size * 1.03) + 256
    return max(64, int(size * 0.45) + 256)


def split_large_object(sha: str, size: int, dest_dir: Path, prefix: str) -> list[dict]:
    src = object_path(sha)
    parts = []
    idx = 0
    with open(src, "rb") as f:
        while True:
            chunk = f.read(MAX_VOL)
            if not chunk:
                break
            idx += 1
            name = f"{prefix}.{idx:03d}"
            part_path = dest_dir / name
            part_path.write_bytes(chunk)
            ph = sha256_bytes(chunk)
            parts.append({
                "name": name,
                "path": str(part_path),
                "bytes": len(chunk),
                "sha256": ph,
                "index": idx,
            })
    return parts


def pack_volumes(objects: list[dict]) -> list[dict]:
    """objects: [{sha256, bytes, classification}] unique objects to pack."""
    VOLUMES.mkdir(parents=True, exist_ok=True)
    volumes = []
    pending: list[dict] = []
    est = 0

    def flush(members: list[dict], vol_i: int) -> dict | None:
        if not members:
            return None
        name = f"vol_{vol_i:04d}.tar.gz"
        path = VOLUMES / name
        # write tar.gz of cas object files with names objects/ab/sha
        def write_tar(dest: Path, mems: list[dict]) -> int:
            with tarfile.open(dest, "w:gz", compresslevel=6) as t:
                for m in mems:
                    op = object_path(m["sha256"])
                    arc = f"objects/{m['sha256'][:2]}/{m['sha256']}"
                    t.add(op, arcname=arc, recursive=False)
            return dest.stat().st_size

        size = write_tar(path, members)
        if size > MAX_VOL and len(members) > 1:
            path.unlink(missing_ok=True)
            mid = max(1, len(members) // 2)
            left = flush(members[:mid], vol_i)
            # caller assigns further indices; handle by recursive list
            return {"_split": True, "left": left, "right_members": members[mid:], "start_index": vol_i}
        if size > MAX_VOL and len(members) == 1:
            path.unlink(missing_ok=True)
            # split the single object
            parts = split_large_object(members[0]["sha256"], members[0]["bytes"], VOLUMES, f"obj_{members[0]['sha256']}.part")
            return {
                "type": "split_object",
                "sha256": members[0]["sha256"],
                "bytes": members[0]["bytes"],
                "parts": parts,
                "part_count": len(parts),
            }
        h = sha256_file(str(path))
        return {
            "type": "tar_gz_volume",
            "name": name,
            "path": str(path),
            "bytes": size,
            "sha256": h,
            "object_count": len(members),
            "object_bytes": sum(m["bytes"] for m in members),
            "objects": [m["sha256"] for m in members],
        }

    # handle oversized unique objects first
    normal = []
    oversized = []
    for o in objects:
        if o["bytes"] > MAX_VOL:
            oversized.append(o)
        else:
            normal.append(o)

    vol_recs = []
    vol_i = 1
    for o in oversized:
        rec = flush([o], vol_i)
        vol_recs.append(rec)
        if rec and rec.get("type") == "tar_gz_volume":
            vol_i += 1
        elif rec and rec.get("type") == "split_object":
            vol_i += 1

    current: list[dict] = []
    current_est = 0
    # pack larger first for slightly better packing, but keep deterministic by sha
    normal.sort(key=lambda x: x["sha256"])
    for o in normal:
        cost = estimate_vol_cost(o["bytes"], o["sha256"])
        if current and current_est + cost > int(MAX_VOL * 0.92):
            rec = flush(current, vol_i)
            # handle recursive splits
            stack = [(rec, vol_i)]
            current = []
            current_est = 0
            while stack:
                rec, idx = stack.pop(0)
                if rec and rec.get("_split"):
                    if rec.get("left"):
                        if rec["left"].get("_split"):
                            stack.append((rec["left"], idx))
                        else:
                            vol_recs.append(rec["left"])
                            if rec["left"].get("type") == "tar_gz_volume":
                                vol_i = max(vol_i, idx + 1)
                    vol_i += 1
                    stack.append((flush(rec["right_members"], vol_i), vol_i))
                elif rec:
                    vol_recs.append(rec)
                    vol_i += 1
        current.append(o)
        current_est += cost
    if current:
        rec = flush(current, vol_i)
        stack = [(rec, vol_i)]
        while stack:
            rec, idx = stack.pop(0)
            if rec and rec.get("_split"):
                if rec.get("left"):
                    if rec["left"].get("_split"):
                        stack.append((rec["left"], idx))
                    else:
                        vol_recs.append(rec["left"])
                        if rec["left"].get("type") == "tar_gz_volume":
                            vol_i = max(vol_i, idx + 1)
                vol_i += 1
                stack.append((flush(rec["right_members"], vol_i), vol_i))
            elif rec:
                vol_recs.append(rec)
                vol_i += 1
    # renumber volume names if needed is already assigned
    return vol_recs


def gzip_jsonl(path: Path, rows) -> dict:
    import gzip as gz
    path.parent.mkdir(parents=True, exist_ok=True)
    with gz.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    sha = sha256_file(str(path))
    size = path.stat().st_size
    parts = None
    if size > MAX_VOL:
        parts = split_file(path, path.parent / (path.name + ".part"))
    return {"path": str(path), "sha256": sha, "bytes": size, "parts": parts}


def split_file(path: Path, prefix: Path) -> list[dict]:
    parts = []
    idx = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(MAX_VOL)
            if not chunk:
                break
            idx += 1
            dest = Path(str(prefix) + f"{idx:03d}")
            dest.write_bytes(chunk)
            parts.append({"name": dest.name, "path": str(dest), "bytes": len(chunk), "sha256": sha256_bytes(chunk), "index": idx})
    return parts


KNOWN_GAPS = [
    {
        "id": "vm_private_observer_34",
        "status": "missing_or_VM_only",
        "detail": "M49 other 34 jobs private observer contexts and complete private observer per-replan candidate streams are not included in the actual36 redacted bundle and are not claimed recovered from the VM.",
    },
    {
        "id": "paid_relief_and_two_ONE_and_2197",
        "status": "unknown",
        "detail": "M49 paid_relief original source (e46...) and two old ONE drivers/contexts/candidates remain missing; old 2197 extra schedule count unknown. Not invented, not filled with CloudAgent.",
    },
    {
        "id": "m49_actual36_unredacted_complete_set",
        "status": "missing_or_incomplete",
        "detail": "Original unredacted M49 actual36 execution hash manifest/private originals were not supplied as a complete set.",
    },
    {
        "id": "vm_paths_not_on_parent_box",
        "status": "VM_only_not_present",
        "detail": "Files referenced only under VM /workspace/m46_incoming/project/batches or /home/ubuntu/m47_private_exec are not proven locally present unless represented by a saved attachment/subtree. /opt/cursor does not exist on this box. The entire VM filesystem is NOT backed up.",
    },
    {
        "id": "vm_unexported_failures_and_terminal_history",
        "status": "VM_only_not_enumerated",
        "detail": "Remote uncommitted source, abandoned/interrupted run directories, console terminal histories, and artifacts never exported from the VM are not enumerated by a complete remote manifest.",
    },
]


def write_restore_and_readme(cutoff: str, summary: dict) -> None:
    restore = r'''#!/usr/bin/env python3
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
'''
    (BACKUP / "restore.py").write_text(restore)
    os.chmod(BACKUP / "restore.py", 0o755)
    (TOOLS / "restore.py").write_text(restore)

    readme = f"""# Thesis research full backup (prepared, not uploaded)

Snapshot cutoff: **{cutoff}** (Asia/Shanghai, UTC+8)

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
- M50_bot_narrow_land_20261121 is included only as the point-in-time tree at cutoff and was not chased as it changed. Later incremental backup is expected.

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
"""
    (BACKUP / "README_RESTORE.md").write_text(readme)
    (DOCS / "README_RESTORE.md").write_text(readme)
    write_json(MANIFESTS / "summary_at_readme.json", {"cutoff": cutoff, **{k: summary.get(k) for k in summary}})


def main() -> int:
    cutoff = load_cutoff()
    for d in (MANIFESTS, CAS, VOLUMES, DOCS, TOOLS):
        d.mkdir(parents=True, exist_ok=True)
    update_state(status="inventory_walk_started", snapshot_cutoff=cutoff, upload_status="not_started",
                 upload_authorized_now=False, no_network_write_this_run=True)

    map_raw = MANIFESTS / "source_to_object_map.raw.jsonl"
    if map_raw.exists():
        map_raw.unlink()

    source_stats = defaultdict(lambda: {"files": 0, "symlinks": 0, "bytes": 0, "present": True,
                                        "classifications": defaultdict(int), "unreadable": 0})
    missing_roots = []
    rows = []
    unique = {}  # sha -> {sha256, bytes, classification, store_count}
    cred_exclusions = []
    unreadable = []
    archived_candidates = []
    n = 0
    t0 = time.time()

    for rec in iter_entries():
        if rec["kind"] == "missing_root":
            missing_roots.append({"source_id": rec["source_id"], "root": rec["root"]})
            source_stats[rec["source_id"]]["present"] = False
            source_stats[rec["source_id"]]["root"] = rec["root"]
            continue
        info = classify_and_hash(rec)
        sid = info["source_id"]
        source_stats[sid]["root"] = info["root"]
        n += 1
        typ = info.get("type")
        if typ == "file":
            source_stats[sid]["files"] += 1
            source_stats[sid]["bytes"] += int(info.get("size") or 0)
        elif typ == "symlink":
            source_stats[sid]["symlinks"] += 1
        if info.get("classification") == "unreadable":
            source_stats[sid]["unreadable"] += 1
            unreadable.append({"path": info["path"], "error": info.get("error")})
        source_stats[sid]["classifications"][info.get("classification") or "unknown"] += 1

        # store research / sanitized / sealed bytes
        sha = info.get("sha256")
        if sha and info.get("classification") in {"research", "sealed_unexpanded"}:
            try:
                store_file(info["path"], sha)
                info["stored"] = True
            except Exception as e:
                info["stored"] = False
                info["store_error"] = type(e).__name__
        elif sha and info.get("classification") == "credential_sanitized":
            info["stored"] = True  # already stored during classify
        if sha:
            unique.setdefault(sha, {"sha256": sha, "bytes": object_path(sha).stat().st_size if object_path(sha).exists() else info.get("size"),
                                     "classification": info.get("classification"), "source_count": 0})
            unique[sha]["source_count"] += 1

        if info.get("classification") in {"credential_excluded", "credential_sanitized"}:
            cred_exclusions.append({
                "path": info["path"],
                "source_id": sid,
                "classification": info.get("classification"),
                "reasons": info.get("credential_reasons"),  # names only
                "original_sha256_recorded": info.get("original_sha256") if info.get("classification") == "credential_sanitized" else "not_stored",
                "sanitized_sha256": sha if info.get("classification") == "credential_sanitized" else None,
                "original_bytes_uploaded_or_stored": False,
            })

        row = {
            "source_id": sid,
            "root": info.get("root"),
            "path": info["path"],
            "rel_under_source": rel_under(Path(info["root"]), Path(info["path"])),
            "restore_rel": rel_under(Path(info["root"]), Path(info["path"])),
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
        }
        rows.append(row)
        with open(map_raw, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

        # archive verification candidates (skip sealed world inspection; still test archive containers)
        pth = info["path"]
        low = pth.lower()
        if typ == "file" and (low.endswith(".tar.gz") or low.endswith(".tgz") or low.endswith(".zip") or low.endswith(".tar") or (low.endswith(".gz") and not low.endswith(".tar.gz"))):
            if not info.get("sealed_unexpanded"):
                archived_candidates.append((pth, info.get("original_sha256") or sha))

        if n % 20000 == 0:
            update_state(status="inventory_walk_in_progress", files_seen=n,
                         unique_objects=len(unique), elapsed_s=round(time.time() - t0, 1))
            print(f"[progress] files={n} unique={len(unique)} elapsed={time.time()-t0:.1f}s", flush=True)

    print(f"[inventory done] files_rows={n} unique={len(unique)} elapsed={time.time()-t0:.1f}s", flush=True)
    update_state(status="archive_verification", files_seen=n, unique_objects=len(unique))

    # Verify unique archives by sha
    arch_results = []
    seen_arch = {}
    for path, sha in archived_candidates:
        key = sha or path
        if key in seen_arch:
            # still record path but reuse result
            reused = dict(seen_arch[key])
            reused["path"] = path
            reused["deduped_verification"] = True
            arch_results.append(reused)
            continue
        rec = verify_archive(path, sha)
        seen_arch[key] = rec
        arch_results.append(rec)

    # Cross-check the 28 original attachment archives if the index exists
    idx_path = Path("/workspace/M49_INDEPENDENT_AUDIT_20261121/M47_M49_ORIGINAL_ARCHIVE_INDEX.json")
    index_checks = []
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text())
            for item in idx:
                p = item.get("path")
                expect = item.get("sha256")
                ok = False
                got = None
                err = None
                present = bool(p and os.path.exists(p))
                if present:
                    try:
                        got = sha256_file(p)
                        ok = (got == expect)
                    except Exception as e:
                        err = type(e).__name__
                index_checks.append({
                    "path": p,
                    "expected_sha256": expect,
                    "actual_sha256": got,
                    "present": present,
                    "sha_match": ok,
                    "error": err,
                    "bytes": item.get("bytes"),
                })
        except Exception as e:
            index_checks.append({"error": type(e).__name__, "path": str(idx_path)})

    failed_archives = [r for r in arch_results if not r.get("ok")]
    write_json(MANIFESTS / "archive_verification.json", {
        "tested": len(arch_results),
        "unique_tested": len(seen_arch),
        "failed": len(failed_archives),
        "original_28_index_checks": index_checks,
        "original_28_sha_mismatches": [c for c in index_checks if not c.get("sha_match")],
        "failures": failed_archives[:500],
    })

    update_state(status="packing_volumes", files_seen=n, unique_objects=len(unique))

    # Unique objects actually present in CAS
    cas_objects = []
    for sha, meta in unique.items():
        op = object_path(sha)
        if op.exists():
            cas_objects.append({"sha256": sha, "bytes": op.stat().st_size, "classification": meta.get("classification"),
                                "source_count": meta.get("source_count")})
    volumes = pack_volumes(cas_objects)
    # sanitize volume records for manifest (do not embed huge object lists twice if enormous — keep them, needed for restore)
    # If object lists make the manifest too large, gzip it as well.
    vol_manifest = {
        "max_volume_bytes": MAX_VOL,
        "volume_count": len(volumes),
        "volumes": volumes,
        "note": "Each volume or split part has sha256 for later remote download verification. Not uploaded in this run.",
    }
    write_json(MANIFESTS / "volume_manifest.json", vol_manifest)
    vm_size = (MANIFESTS / "volume_manifest.json").stat().st_size
    if vm_size > MAX_VOL:
        gzip_jsonl(MANIFESTS / "volume_manifest.jsonl.gz", [])  # placeholder unused
        import gzip as gz
        gzp = MANIFESTS / "volume_manifest.json.gz"
        with open(MANIFESTS / "volume_manifest.json", "rb") as inp, gz.open(gzp, "wb") as out:
            shutil.copyfileobj(inp, out)
        # also split if needed
        if gzp.stat().st_size > MAX_VOL:
            split_file(gzp, MANIFESTS / "volume_manifest.json.gz.part")

    # compact object index without repeating huge membership
    obj_index_rows = [{"sha256": o["sha256"], "bytes": o["bytes"], "classification": o["classification"],
                       "source_count": o["source_count"]} for o in cas_objects]
    obj_man = gzip_jsonl(MANIFESTS / "object_index.jsonl.gz", obj_index_rows)
    map_man = gzip_jsonl(MANIFESTS / "source_to_object_map.jsonl.gz", rows)
    if map_raw.exists():
        map_raw.unlink()

    # source inventory
    inv = {}
    total_files = total_bytes = total_links = 0
    for sid, stt in source_stats.items():
        cls = dict(stt["classifications"])
        inv[sid] = {
            "root": stt.get("root"),
            "present": stt.get("present", True),
            "files": stt["files"],
            "symlinks": stt["symlinks"],
            "bytes": stt["bytes"],
            "unreadable": stt["unreadable"],
            "classifications": cls,
        }
        total_files += stt["files"]
        total_bytes += stt["bytes"]
        total_links += stt["symlinks"]

    source_inventory = {
        "snapshot_cutoff": cutoff,
        "timezone": "Asia/Shanghai (UTC+8)",
        "upload_status": "not_started_prepared_only",
        "total_source_files": total_files,
        "total_source_symlinks": total_links,
        "total_source_bytes": total_bytes,
        "unique_objects": len(cas_objects),
        "unique_object_bytes": sum(o["bytes"] for o in cas_objects),
        "credential_exclusion_paths": len(cred_exclusions),
        "missing_roots": missing_roots,
        "sources": inv,
        "excluded_non_research_roots": sorted(EXCLUDED_ROOTS),
        "pruned_directory_names": sorted(SKIP_DIR_NAMES),
        "m50_policy": "M50_bot_narrow_land_20261121 included only as tree-at-cutoff under the research root; not chased afterwards",
        "handoff_lists_incorporated": [
            "/workspace/M49_INDEPENDENT_AUDIT_20261121/M47_M49_LOCAL_HANDOFF_INVENTORY.json",
            "/workspace/M49_INDEPENDENT_AUDIT_20261121/M47_M49_ORIGINAL_ARCHIVE_INDEX.json",
            "/workspace/M49_INDEPENDENT_AUDIT_20261121/RUN33_HANDOFF_SEAL.json",
        ],
    }
    write_json(MANIFESTS / "source_inventory.json", source_inventory)
    write_json(MANIFESTS / "credential_exclusions.json", {
        "note": "Paths and detection pattern names only. Secret values are not recorded. Original credential bytes are not stored in cas/objects. Sanitized copies are stored when a safe redaction was possible.",
        "count": len(cred_exclusions),
        "items": cred_exclusions,
    })
    write_json(MANIFESTS / "missing_and_gaps.json", {
        "snapshot_cutoff": cutoff,
        "cannot_claim_full_VM_recovery": True,
        "missing_roots_on_this_box": missing_roots,
        "unreadable_files": unreadable,
        "known_gaps": KNOWN_GAPS,
        "opt_cursor_on_parent_box": os.path.exists("/opt/cursor"),
        "notes": "Later M50 incremental products after cutoff are not in this snapshot. Do not invent missing VM artifacts.",
    })

    # volume compactness + hashes list
    vol_failed_size = [v for v in volumes if v.get("type") == "tar_gz_volume" and v.get("bytes", 0) > MAX_VOL]
    summary = {
        "snapshot_cutoff": cutoff,
        "source_files": total_files,
        "source_symlinks": total_links,
        "source_bytes": total_bytes,
        "unique_objects": len(cas_objects),
        "unique_object_bytes": sum(o["bytes"] for o in cas_objects),
        "volumes": len(volumes),
        "volume_bytes": sum((v.get("bytes") or 0) if v.get("type") == "tar_gz_volume" else sum(p["bytes"] for p in v.get("parts") or []) for v in volumes),
        "credential_exclusion_paths": len(cred_exclusions),
        "archive_tests": len(arch_results),
        "archive_failures": len(failed_archives),
        "missing_roots": missing_roots,
        "upload_status": "prepared_not_uploaded",
        "volumes_exceeding_limit": vol_failed_size,
        "object_index": obj_man,
        "source_map": map_man,
    }
    write_json(MANIFESTS / "complete_backup_summary.json", summary)
    write_restore_and_readme(cutoff, summary)

    # human missing list
    (BACKUP / "MISSING.md").write_text(
        "# Missing and authenticity gaps\n\n"
        f"Snapshot cutoff: {cutoff} (Asia/Shanghai, UTC+8)\n\n"
        "This backup cannot claim that all VM content has been recovered.\n\n"
        + "\n".join(f"- {g['id']}: {g['detail']}" for g in KNOWN_GAPS)
        + "\n"
    )

    update_state(
        status="prepared_local_backup_complete",
        upload_status="not_started",
        upload_authorized_now=False,
        prepared=True,
        uploaded=False,
        snapshot_cutoff=cutoff,
        summary=summary,
        github_write_path_blocker="gh not logged in; no file-push MCP; CloudAgent forbidden",
    )
    # refresh STATE.md
    (BACKUP / "STATE.md").write_text(
        f"# Backup STATE\n\n"
        f"- Backup id: thesis_full_backup_20261121_2058\n"
        f"- Snapshot cutoff: **{cutoff}** (Asia/Shanghai, UTC+8)\n"
        f"- Status: **prepared** (local inventory, CAS objects, volumes, restore script)\n"
        f"- Upload: **not started / not uploaded**. Parent will trigger a unified upload later near quota, after incremental M50 merge.\n"
        f"- Source files: {total_files}; source bytes: {total_bytes}; unique objects: {len(cas_objects)}; volumes: {len(volumes)}\n"
        f"- Credential exclusion paths: {len(cred_exclusions)}\n"
        f"- GitHub write path blocker (early): gh is not logged in. cursor-github MCP cannot push files or upload release assets. CloudAgent is forbidden.\n"
        f"- VM completeness: cannot be claimed. See manifests/missing_and_gaps.json and MISSING.md.\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        update_state(status="packager_failed", error_type="exception")
        traceback.print_exc()
        sys.exit(1)
