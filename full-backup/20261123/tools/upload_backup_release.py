#!/usr/bin/env python3
"""Upload the frozen 2026-11-23 backup package via official gh.
Refuses unless gh is already authenticated. Never prints tokens.
Never force-pushes, never rewrites main, never creates a new repo, never changes visibility.
Does not include M86 or later live research.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("GH_PROMPT_DISABLED", "1")
os.environ.setdefault("GH_NO_UPDATE_NOTIFIER", "1")

BACKUP = Path("/workspace/thesis_full_backup_20261121_2058")
REPO = "shangjinwang36-a11y/thesis-truck-drone"
BRANCH = "backup/20261123-thesis-full"
TAG = "thesis-full-backup-20261123"
TITLE = "Thesis full backup 2026-11-23"
INDEX = BACKUP / "manifests" / "upload_unit_index.json"
WORK = Path("/workspace/backup-upload-20261123/repo")
STAGING_PREFIX = "full-backup/20261123"
LOG = BACKUP / "docs" / "UPLOAD_PROGRESS.jsonl"
STATUS = BACKUP / "docs" / "UPLOAD_STATUS.json"
VERIFY = BACKUP / "docs" / "UPLOAD_VERIFY_20261123.json"
TOKEN_RE = re.compile(r"(token|Token|oauth|secret|ghp_|gho_|github_pat_|ghu_)[^\s]*")


def redact(text: str) -> str:
    return TOKEN_RE.sub("[REDACTED]", text or "")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %Z")


def log(event: str, **kw):
    rec = {"time": now(), "event": event, **kw}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[{rec['time']}] {event} " + " ".join(f"{k}={v}" for k, v in kw.items() if k not in {"stdout", "stderr"}), flush=True)


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


def run(cmd, cwd=None, timeout=None):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    return r


def require_gh_auth() -> str:
    r = run(["gh", "auth", "status"])
    out = redact((r.stdout or "") + (r.stderr or ""))
    if r.returncode != 0 or "not logged into" in out.lower():
        log("auth_missing", detail=out.strip())
        print("REFUSE: gh is not logged in.")
        sys.exit(2)
    r2 = run(["gh", "api", "user", "--jq", ".login"])
    login = (r2.stdout or "").strip()
    if r2.returncode != 0 or not login:
        log("auth_identity_failed", detail=redact(r2.stderr or ""))
        sys.exit(2)
    log("auth_ok", login=login)
    return login


def gh_api(path, method="GET", *args):
    cmd = ["gh", "api", path, "-X", method, *args]
    r = run(cmd)
    return r


def existing_assets() -> dict:
    r = run(["gh", "release", "view", TAG, "--repo", REPO, "--json", "assets,url,tagName,targetCommitish"])
    if r.returncode != 0:
        return {}
    data = json.loads(r.stdout or "{}")
    out = {}
    for a in data.get("assets") or []:
        out[a["name"]] = a
    return {"url": data.get("url"), "tag": data.get("tagName"), "target": data.get("targetCommitish"), "assets": out}


def prepare_branch(login: str) -> str:
    WORK.parent.mkdir(parents=True, exist_ok=True)
    if WORK.exists():
        shutil.rmtree(WORK)
    log("clone_start", from_branch="main")
    r = run(["git", "clone", "--depth", "1", "--branch", "main", f"https://github.com/{REPO}.git", str(WORK)])
    if r.returncode != 0:
        log("clone_failed", stderr=redact(r.stderr or "")[-1000:])
        raise SystemExit(2)
    r = run(["git", "checkout", "-B", BRANCH], cwd=WORK)
    if r.returncode != 0:
        log("branch_create_failed", stderr=redact(r.stderr or "")[-1000:])
        raise SystemExit(2)
    dest = WORK / STAGING_PREFIX
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    def copy_file(src: Path, rel: str):
        if not src.exists():
            return
        t = dest / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, t)

    def copy_tree_filtered(src: Path, rel: str, skip_names=()):
        if not src.exists():
            return
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in skip_names and d != "__pycache__"]
            for fn in filenames:
                if fn.endswith(".pyc"):
                    continue
                fp = Path(dirpath) / fn
                sub = fp.relative_to(src).as_posix()
                copy_file(fp, str(Path(rel) / sub))

    copy_file(BACKUP / "restore.py", "restore.py")
    copy_file(BACKUP / "STATE.md", "STATE.md")
    copy_file(BACKUP / "MISSING.md", "MISSING.md")
    copy_tree_filtered(BACKUP / "docs", "docs")
    copy_tree_filtered(BACKUP / "tools", "tools")
    # Current maps + increment histories; skip bulky as_of_* / v1 duplicate snapshots
    man_src = BACKUP / "manifests"
    man_dest_rel = "manifests"
    for p in man_src.iterdir():
        if p.name.startswith("as_of_") or p.name == "v1_original_snapshot":
            continue
        if p.is_file():
            copy_file(p, f"{man_dest_rel}/{p.name}")
        elif p.is_dir() and p.name.startswith("increment_"):
            copy_tree_filtered(p, f"{man_dest_rel}/{p.name}")

    readme = dest / "README.md"
    readme.write_text(
        f"""# Thesis full backup 2026-11-23

Frozen package for the public repository `{REPO}`.

- Audit-tree snapshot: `auditseal_20261123_091613` at **2026-11-23 09:16:13 CST** (Asia/Shanghai, UTC+8)
- Packed as `increment_20261123_091709` (packer cutoff **2026-11-23 09:17:09 CST**)
- Earlier increments in this same package go back to the 2026-11-21 21:09:58 CST original snapshot, including M50–M85 and the 09:15 review_0010 / v8 seal.
- Volume payloads are **not** stored in git history. They are GitHub Release assets on tag `{TAG}`.
- `M86` and any work after 09:17:09 CST are **not** in this package and will be a later increment.

## Restore

1. Download this branch (or this folder) for `restore.py`, `manifests/`, and docs.
2. Download every asset from the release `{TAG}` into a `volumes/` tree, converting each asset name by replacing `__` with `/`.
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
"""
    )

    notes = dest / "docs" / "RELEASE_NOTES.md"
    notes.write_text(
        f"""Thesis full backup frozen at 2026-11-23 09:16:13 / 09:17:09 CST (Asia/Shanghai).

This release holds the volume units for the prepared local package under `/workspace/thesis_full_backup_20261121_2058` (local path on the build machine). Branch `{BRANCH}` holds restore scripts and manifests only.

Included: original 2026-11-21 snapshot plus increments through `increment_20261123_091709` (M50–M85, systematic_audit including review_0009 and the 09:15 review_0010 / v8 seal, SOURCE_REPAIR_DELIVERY_0010.json).

Not included: M86 and any work after 09:17:09 CST.

346 volume units, all ≤ 45 MiB. Verify by downloading assets and checking SHA256 against `manifests/upload_unit_index.json`, then `python3 restore.py --backup-root . --verify-only`.

Credential exclusion path count remains 27. Do not treat this as a full VM backup.
"""
    )

    run(["git", "add", "-A"], cwd=WORK)
    r = run(["git", "status", "--porcelain"], cwd=WORK)
    if not (r.stdout or "").strip():
        log("branch_nothing_to_commit")
    else:
        r = run(
            [
                "git",
                "-c", "user.email=shangjinwang36-a11y@users.noreply.github.com",
                "-c", "user.name=shangjinwang36-a11y",
                "commit",
                "-m",
                "Add 2026-11-23 frozen thesis backup manifests and restore docs.\n\nVolume payloads are published as release assets on tag thesis-full-backup-20261123. M86 and later work are excluded.",
            ],
            cwd=WORK,
        )
        if r.returncode != 0:
            log("commit_failed", stderr=redact(r.stderr or "")[-1500:], stdout=redact(r.stdout or "")[-500:])
            raise SystemExit(2)
        log("commit_ok")
    # confirm we are not on main before push
    br = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=WORK)
    if (br.stdout or "").strip() != BRANCH:
        log("wrong_branch", got=(br.stdout or "").strip())
        raise SystemExit(2)
    # no force
    r = run(["git", "push", "-u", "origin", BRANCH], cwd=WORK)
    if r.returncode != 0:
        # if remote branch already exists and is fast-forward or already up to date, inspect
        log("push_failed", stderr=redact(r.stderr or "")[-2000:], stdout=redact(r.stdout or "")[-500:])
        raise SystemExit(2)
    sha = run(["git", "rev-parse", "HEAD"], cwd=WORK).stdout.strip()
    url = f"https://github.com/{REPO}/tree/{BRANCH}"
    log("branch_pushed", sha=sha, url=url)
    write_status(branch=BRANCH, branch_sha=sha, branch_url=url, branch_pushed=True)
    return sha


def ensure_release(sha: str) -> str:
    existing = existing_assets()
    if existing:
        url = existing.get("url") or f"https://github.com/{REPO}/releases/tag/{TAG}"
        log("release_already_exists", url=url, assets=len(existing.get("assets") or {}))
        write_status(release_url=url, release_existed=True)
        return url
    notes = WORK / STAGING_PREFIX / "docs" / "RELEASE_NOTES.md"
    r = run(
        [
            "gh", "release", "create", TAG,
            "--repo", REPO,
            "--target", BRANCH,
            "--title", TITLE,
            "--notes-file", str(notes),
        ]
    )
    if r.returncode != 0:
        # maybe created in a race
        existing = existing_assets()
        if existing:
            url = existing.get("url") or f"https://github.com/{REPO}/releases/tag/{TAG}"
            log("release_exists_after_create_error", url=url)
            return url
        log("release_create_failed", stderr=redact(r.stderr or "")[-2000:])
        raise SystemExit(2)
    url = f"https://github.com/{REPO}/releases/tag/{TAG}"
    # prefer API url
    ex = existing_assets()
    if ex.get("url"):
        url = ex["url"]
    log("release_created", url=url, target=BRANCH)
    write_status(release_url=url, release_created=True, release_tag=TAG)
    return url


def upload_units(idx: dict) -> dict:
    units = idx["units"]
    batch_size = 5
    uploaded = 0
    skipped = 0
    failed = []
    uploaded_bytes = 0
    skipped_bytes = 0
    existing = (existing_assets().get("assets") or {})
    pending = []
    for u in units:
        name = u["asset_name"]
        path = u["path"]
        if not Path(path).exists():
            failed.append({"name": name, "reason": "local_missing"})
            continue
        if name in existing and existing[name].get("size") == u["bytes"]:
            skipped += 1
            skipped_bytes += u["bytes"]
            continue
        pending.append(u)

    log("upload_plan", total=len(units), already_remote_same_size=skipped, to_upload=len(pending), skipped_bytes=skipped_bytes)

    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        args = ["gh", "release", "upload", TAG, "--repo", REPO]
        for u in batch:
            args.append(f"{u['path']}#{u['asset_name']}")
        r = run(args, timeout=60 * 30)
        if r.returncode != 0:
            # retry one-by-one
            log("batch_failed_retry_singles", batch_start=i, stderr=redact(r.stderr or "")[-1500:])
            for u in batch:
                r2 = run(["gh", "release", "upload", TAG, "--repo", REPO, f"{u['path']}#{u['asset_name']}"], timeout=60 * 20)
                if r2.returncode != 0:
                    # if already exists, treat as skip after re-list
                    err = redact(r2.stderr or "")
                    if "already exists" in err.lower():
                        skipped += 1
                        skipped_bytes += u["bytes"]
                        log("asset_exists_skipped", name=u["asset_name"])
                    else:
                        failed.append({"name": u["asset_name"], "reason": err[-400:]})
                        log("asset_failed", name=u["asset_name"], reason=err[-400:])
                else:
                    uploaded += 1
                    uploaded_bytes += u["bytes"]
                    log("asset_uploaded", name=u["asset_name"], bytes=u["bytes"], uploaded=uploaded, uploaded_bytes=uploaded_bytes)
        else:
            for u in batch:
                uploaded += 1
                uploaded_bytes += u["bytes"]
            log("batch_uploaded", batch_start=i, batch_count=len(batch), uploaded=uploaded, uploaded_bytes=uploaded_bytes)
        write_status(
            upload_uploaded=uploaded,
            upload_uploaded_bytes=uploaded_bytes,
            upload_skipped=skipped,
            upload_skipped_bytes=skipped_bytes,
            upload_failed=len(failed),
            upload_pending=max(0, len(pending) - uploaded - sum(1 for f in failed if f["name"] in {u["asset_name"] for u in batch})),
            release_url=f"https://github.com/{REPO}/releases/tag/{TAG}",
        )
    summary = {
        "uploaded": uploaded,
        "uploaded_bytes": uploaded_bytes,
        "skipped_existing": skipped,
        "skipped_bytes": skipped_bytes,
        "failed": failed,
        "total_units": len(units),
        "total_bytes": idx.get("total_bytes"),
    }
    log("upload_finished", **{k: v for k, v in summary.items() if k != "failed"}, failed_count=len(failed))
    return summary


def verify_remote(idx: dict, upload_summary: dict) -> dict:
    assets = existing_assets().get("assets") or {}
    dest = Path("/workspace/backup-upload-20261123/download-verify")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    results = []
    ok = 0
    bad = 0
    missing = 0
    checked_bytes = 0
    for u in idx["units"]:
        name = u["asset_name"]
        meta = assets.get(name)
        rec = {"name": name, "expected_sha256": u["sha256"], "expected_bytes": u["bytes"]}
        if not meta:
            rec["status"] = "missing_on_remote"
            missing += 1
            results.append(rec)
            continue
        rec["remote_size"] = meta.get("size")
        rec["remote_url"] = meta.get("url")
        out = dest / name
        r = run(
            ["gh", "release", "download", TAG, "--repo", REPO, "--pattern", name, "--dir", str(dest), "--clobber"],
            timeout=60 * 20,
        )
        # downloaded file may keep asset name
        if r.returncode != 0 or not out.exists():
            # gh may save as original filename
            candidates = list(dest.glob("*"))
            found = None
            for c in candidates:
                if c.name == name or c.name == Path(u["path"]).name:
                    found = c
                    break
            if not found:
                rec["status"] = "download_failed"
                rec["stderr"] = redact(r.stderr or "")[-300:]
                bad += 1
                results.append(rec)
                continue
            out = found
        h = __import__("hashlib").sha256()
        n = 0
        with open(out, "rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(chunk)
                n += len(chunk)
        rec["downloaded_bytes"] = n
        rec["downloaded_sha256"] = h.hexdigest()
        if n == u["bytes"] and h.hexdigest() == u["sha256"]:
            rec["status"] = "ok"
            ok += 1
            checked_bytes += n
        else:
            rec["status"] = "hash_or_size_mismatch"
            bad += 1
        results.append(rec)
        # delete to save disk
        try:
            out.unlink()
        except OSError:
            pass
        if (ok + bad + missing) % 20 == 0:
            log("verify_progress", ok=ok, bad=bad, missing=missing, checked_bytes=checked_bytes)
            write_status(verify_ok=ok, verify_bad=bad, verify_missing=missing, verify_checked_bytes=checked_bytes)
    report = {
        "time": now(),
        "release_tag": TAG,
        "release_url": f"https://github.com/{REPO}/releases/tag/{TAG}",
        "branch": BRANCH,
        "branch_url": f"https://github.com/{REPO}/tree/{BRANCH}",
        "ok": ok,
        "bad": bad,
        "missing": missing,
        "checked_bytes": checked_bytes,
        "upload_summary": upload_summary,
        "results": results,
    }
    VERIFY.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    log("verify_done", ok=ok, bad=bad, missing=missing, checked_bytes=checked_bytes)
    write_status(verify_ok=ok, verify_bad=bad, verify_missing=missing, verify_checked_bytes=checked_bytes, verify_report=str(VERIFY))
    return report


def main() -> int:
    login = require_gh_auth()
    if login != "shangjinwang36-a11y":
        log("unexpected_login", login=login)
        print("REFUSE: logged-in account is not shangjinwang36-a11y")
        return 2
    if not INDEX.exists():
        print("REFUSE: upload unit index missing")
        return 2
    idx = json.loads(INDEX.read_text())
    write_status(started=now(), login=login, repo=REPO, upload_authorized_now=True, uploaded=False)
    sha = prepare_branch(login)
    url = ensure_release(sha)
    summary = upload_units(idx)
    if summary["failed"]:
        write_status(uploaded=False, upload_status="partial_failed", release_url=url, **{k: summary[k] for k in ("uploaded", "uploaded_bytes", "skipped_existing", "skipped_bytes")})
        log("stop_before_full_verify_due_to_failed_uploads", failed=len(summary["failed"]))
        # still verify what is remote
    report = verify_remote(idx, summary)
    success = report["bad"] == 0 and report["missing"] == 0 and not summary["failed"]
    write_status(
        uploaded=bool(success),
        upload_status="uploaded_and_verified" if success else "incomplete_or_failed",
        release_url=url,
        branch_url=f"https://github.com/{REPO}/tree/{BRANCH}",
        **{k: summary[k] for k in ("uploaded", "uploaded_bytes", "skipped_existing", "skipped_bytes") if k in summary},
    )
    print(json.dumps({"success": success, "release_url": url, "branch": BRANCH, "verify": {k: report[k] for k in ("ok", "bad", "missing", "checked_bytes")}}, indent=2))
    return 0 if success else 3


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        log("exception")
        import traceback
        traceback.print_exc()
        sys.exit(1)
