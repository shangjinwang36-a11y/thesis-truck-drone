# GitHub upload plan (prepared locally; execute only after gh is logged in)

Cutoff and inventory numbers are completed in increment manifests after packing. This plan is the authorized upload procedure.

## Target and constraints

- Existing public repository only: https://github.com/shangjinwang36-a11y/thesis-truck-drone
- Do not create a new repository, do not change visibility, do not open a PR, do not force-push, do not rewrite `main` history.
- Authorized layout after login: a new dated backup branch for small restore docs/manifests, plus a GitHub Release whose assets are the <=45 MiB volume units.
- Credentials, login stores, and unrelated personal data stay excluded (existing 27 exclusion paths plus any new sanitized/excluded paths in this increment). Secret values are never recorded or printed.
- World-state / holdout bytes remain original sealed objects and are not expanded.
- Original VM gaps remain; this is not a full VM backup.
- Live GitHub connector tools can read the repository but have no release-write or asset-upload tools. Upload must use official `gh` after sanctioned login.
- Do not extract MCP, session, or browser tokens. Do not start a second `gh auth login` if one is already waiting for the user.

## After login is approved (parent/user)

Check identity only, never print tokens:

```sh
export GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1
gh auth status
# Expected: logged into github.com. If not logged in, stop. Do not run gh auth login here if a device flow is already pending.
```

Then run the helper (it refuses unless `gh auth status` succeeds):

```sh
python3 /workspace/thesis_full_backup_20261121_2058/tools/upload_backup_release.py
```

Planned names (created only if missing; never `--force`):

- Branch: `backup/20261123-thesis-full`
- Release tag: `thesis-full-backup-20261123`
- Release title: `Thesis full backup 2026-11-23`

The helper will:

1. Confirm `gh` is authenticated and the repository is `shangjinwang36-a11y/thesis-truck-drone`.
2. Create the dated branch from the default branch if it does not exist (no force).
3. Add only small files (restore script, docs, manifests, upload unit index). Volume payloads stay out of git history and go to the release.
4. Create the release if the tag does not already exist (no overwrite of an existing release).
5. Upload every volume unit listed in the upload-unit index as a release asset, then download each asset and verify SHA256 against the local volume manifest.
6. Write `docs/UPLOAD_VERIFY_20261123.json` with pass/fail. Success is only recorded after remote hash verification. Do not mark `uploaded` on a local package alone.

## If `gh` is still not logged in

Do not claim uploaded. Required official login (for the parent to present to the user; do not start a second copy if one is already pending):

```sh
gh auth login --hostname github.com --git-protocol https --web
```

Needed scopes: repository read/write sufficient to create a branch, create a release, and upload release assets on `shangjinwang36-a11y/thesis-truck-drone` (typically `repo` for a private repo; this target is public but write still needs an authenticated account with push access). Git and `gh` stay on this box; do not use Cursor, CloudAgent, or the user's PC as the uploader.

