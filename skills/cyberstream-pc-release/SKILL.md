---
name: cyberstream-pc-release
description: Cut a CyberStream PC desktop release end-to-end without asking the user. Use when the user says "发个 release", "打个新版本", "发布最新版", "ship 1.21.x", "发 lite/full". Covers default-backend reset, uv-based PyInstaller sidecar build, dual lite+full MSI build, GitHub release via REST API with assets uploaded. Repo: https://github.com/Purewo/CyberStream.
---

# CyberStream PC Release

## Mission

The user runs `release` flow many times a year. They want a default-action skill — every "发个 release" should produce a tagged GitHub release with both MSIs uploaded, **without questions**. This document captures every gotcha hit on prior runs so the next pass is silent.

## Project facts

- **Repo root**: `G:\AI\AI_private\Cluade_code_projects\CyberStream-repo` (Windows host, Git Bash shell)
- **Three apps in one repo**: `backend/` (Flask), `frontend/` (React+Vite), `pc/` (Tauri 2)
- **Versioning is dual-tracked**: semver in `pc/src-tauri/tauri.conf.json` + `frontend/package.json` is `X.Y.Z` (no suffix); the `-pc.N` suffix lives only in **git tag, release notes filename, MSI asset filename**. Never put `-pc.N` in tauri.conf.json — Tauri rejects SemVer prereleases there.
- **Two MSI variants** ship every release:
  - `lite` (~95 MB): no embedded backend; user fills 「设置 → 后端服务器」 themselves
  - `full` (~125 MB): bundles `cyber-backend.exe` (PyInstaller-frozen Flask, listens 127.0.0.1:49152) as a Tauri sidecar
- **MSI naming**: `CyberStream_<X.Y.Z>-pc.<n>_<variant>_x64.msi`, lives under `pc/src-tauri/target/release/bundle/msi/`
- **`gh` CLI is NOT installed** — use git for push/tag and the REST API for releases.
- **GitHub HTTPS requires proxy on this host**: `http://127.0.0.1:10808`. Set both `HTTPS_PROXY` and `HTTP_PROXY` for git/curl calls.
- **`requirements.txt` is at repo root**, not under `backend/`.
- **`pc/vendor/mpv-dev/libmpv-2.dll`** must be present (gitignored). build.rs copies it into `target/<profile>/libmpv-2.dll`. If absent, `cargo tauri build` errors at link time — tell the user, don't try to download it.

## Hard rules

- **Default backend in shipped builds = `''` (empty string)** at `frontend/src/platform/pc.ts → PC_DEFAULT_API_BASE`. Never bake a developer hostname into a release.
- Do **not** skip git hooks (no `--no-verify`), do **not** force-push, do **not** amend already-pushed commits. Always create new commits.
- The TMDB token, GitHub PAT, and `.env.local` content **must never** appear in commits, release notes, or asset metadata. The PAT is fetched from git credential manager (see Step 8).
- Don't modify backend code as part of release work unless a release-blocker bug requires it.
- Two unrelated Claude sessions sometimes work the same repo concurrently. Inspect `git status` before staging — anything you didn't author probably belongs to the other session; leave it.
- Hash drift on rebased commits is normal — the parallel session occasionally rebases. Don't panic if your local hashes change between sessions; check commit messages match.
- **Default to action**: when the user says "发布", proceed through the workflow without re-asking the standard questions (variant, version bump, default backend, proxy, token). Those answers are codified below.

## Standard answers (don't ask)

| Question | Answer |
|---|---|
| Variant | Both lite and full |
| Version bump | Patch suffix only (`-pc.<n+1>`); bump core semver minor only when there's a user-visible feature |
| Default backend | Empty string |
| Proxy | `http://127.0.0.1:10808` |
| Tag style | `vX.Y.Z-pc.N` |
| GitHub release type | `prerelease: true` (any `-pc.N` suffix is pre-release) |
| Token | `git credential fill` |
| Python | uv venv at `.venv-build` with Python 3.10 |

Only ask when:
- The user's working tree has files you can't account for AND they look load-bearing
- An MSI's size is wildly off (lite > 130 MB or full < 100 MB → bloat or missing sidecar)
- The bump straddles backend version (then `docs/VERSIONING.md` rules apply)

## Workflow

Run from repo root unless noted. The Bash shell is persistent across tool calls — if you `cd pc/src-tauri`, subsequent calls are inside it. Prefer absolute paths or restart cwd with `cd /g/AI/AI_private/Cluade_code_projects/CyberStream-repo`.

### 0. Triage

```bash
git fetch origin main
git status --short
git log --oneline <last-pc-release-tag>..HEAD
```

Decide:
- Bump: see standard answers
- Anything in `git status` you didn't author → leave it untouched

### 1. Reset default backend (if not already empty)

`frontend/src/platform/pc.ts`:
```ts
const PC_DEFAULT_API_BASE = '';
```

### 2. Bump version (only if bumping core semver)

For patch-suffix-only releases (the common case), **don't touch** `tauri.conf.json` or `package.json` — they keep the same `X.Y.Z`. The `-pc.N` increment happens only in tag/filename/release-notes.

If bumping core semver: change `"version"` in both `pc/src-tauri/tauri.conf.json` and `frontend/package.json`.

### 3. Write release notes

`pc/RELEASE_NOTES_<X.Y.Z>-pc.<n>.md`. Follow `pc/RELEASE_NOTES_1.21.1-pc.1.md` (or any prior pc.N) as a template:

- Opening sentence: vs. previous version, what changed at a glance
- 「下载选哪个？」 lite vs full table with **real** MSI sizes (post-build) — not eyeballed
- 「主要变化」 sections grouping fixes/features
- 「已知坑」
- 「升级指南」 — explicitly mention what data is preserved across upgrade

UI copy in Chinese (Simplified). Code/CLI in English. Don't mention friend names, internal hostnames, or token fragments.

### 4. Build backend sidecar (full build only)

Skip if shipping lite-only — but the standard answer is "both", so usually do this.

**Set up uv venv** (idempotent — if `.venv-build/` already exists with the right Python, this is a no-op):

```bash
cd /g/AI/AI_private/Cluade_code_projects/CyberStream-repo
uv venv .venv-build --python 3.10
HTTPS_PROXY=http://127.0.0.1:10808 HTTP_PROXY=http://127.0.0.1:10808 \
  uv pip install --python .venv-build/Scripts/python.exe -r requirements.txt pyinstaller
```

**Build** (from repo root, NOT `cd backend`):

```bash
.venv-build/Scripts/python.exe -m PyInstaller backend/cyber-backend.spec --clean --noconfirm
```

Long-running (~1 min) — run in background, wait for completion.

**Verify size**: `dist/cyber-backend.exe` should be ~32 MB. If 100 MB+, the spec re-grew the ddddocr/OpenCC/onnxruntime/numpy/Pillow includes — see "common gotchas" below.

**Copy into Tauri sidecar slot**:

```bash
cp dist/cyber-backend.exe pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe
```

The `-x86_64-pc-windows-msvc` triple suffix is what Tauri's `externalBin` resolver expects.

### 5. Build lite MSI

```bash
cd /g/AI/AI_private/Cluade_code_projects/CyberStream-repo/pc/src-tauri
cargo tauri build --config '{"bundle":{"externalBin":[]}}'
```

`--config` overlay strips the sidecar binary out of this build. The flag value is JSON; quote it carefully on Windows Bash. ~3-5 min compile in release mode (incremental on subsequent runs).

Output: `pc/src-tauri/target/release/bundle/msi/CyberStream_<X.Y.Z>_x64_en-US.msi`. Rename to `<...>-pc.<n>_lite_x64.msi`:

```bash
cd /g/AI/AI_private/Cluade_code_projects/CyberStream-repo
MSI_DIR=pc/src-tauri/target/release/bundle/msi
mv "$MSI_DIR/CyberStream_<X.Y.Z>_x64_en-US.msi" "$MSI_DIR/CyberStream_<X.Y.Z>-pc.<n>_lite_x64.msi"
```

Run it in background; takes minutes. Wait for completion before starting full build.

### 6. Build full MSI

```bash
cd /g/AI/AI_private/Cluade_code_projects/CyberStream-repo/pc/src-tauri
cargo tauri build
```

Uses the unmodified `tauri.conf.json` (with `externalBin` set). Cargo will rebuild from scratch because the bundle config differs from step 5 — that's expected, ~3-5 min.

Rename:

```bash
cd /g/AI/AI_private/Cluade_code_projects/CyberStream-repo
MSI_DIR=pc/src-tauri/target/release/bundle/msi
mv "$MSI_DIR/CyberStream_<X.Y.Z>_x64_en-US.msi" "$MSI_DIR/CyberStream_<X.Y.Z>-pc.<n>_full_x64.msi"
```

### 7. Stage everything in git

```bash
git add frontend/src/platform/pc.ts \
        pc/src-tauri/tauri.conf.json \
        frontend/package.json \
        pc/RELEASE_NOTES_<X.Y.Z>-pc.<n>.md
# Also stage backend/cyber-backend.spec if you trimmed includes during this release.
git status --short  # double-check no foreign files staged
git commit -m "release: <X.Y.Z>-pc.<n>"
git tag "v<X.Y.Z>-pc.<n>"
```

**Don't** commit MSI files — they go to the release as attachments.

### 8. Push (proxy)

```bash
HTTPS_PROXY=http://127.0.0.1:10808 HTTP_PROXY=http://127.0.0.1:10808 \
  git push origin main
HTTPS_PROXY=http://127.0.0.1:10808 HTTP_PROXY=http://127.0.0.1:10808 \
  git push origin "v<X.Y.Z>-pc.<n>"
```

### 9. Create GitHub release via REST API

**Get token silently** — never ask user:

```bash
TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill 2>/dev/null | grep '^password=' | cut -d= -f2-)
PROXY="http://127.0.0.1:10808"
```

**Build JSON body via Node** (heredoc + curl `-d` mangles multi-line markdown — don't try). Write to a temp file in repo root (NOT `/tmp/`, that's not on G drive):

```bash
node -e "const fs=require('fs');const body=fs.readFileSync('pc/RELEASE_NOTES_<X.Y.Z>-pc.<n>.md','utf8');fs.writeFileSync('release.body.json',JSON.stringify({tag_name:'v<X.Y.Z>-pc.<n>',name:'CyberStream PC <X.Y.Z>-pc.<n>',body,draft:false,prerelease:true}))"
```

**POST** the release with `--data-binary @file` (NOT `-d`, which strips newlines):

```bash
curl -sS -x "$PROXY" -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  --data-binary @release.body.json \
  https://api.github.com/repos/Purewo/CyberStream/releases \
  -o release.json
```

**Extract upload URL**:

```bash
UPLOAD=$(node -e "const d=JSON.parse(require('fs').readFileSync('release.json','utf8'));if(!d.upload_url){console.error('release create failed:',d.message);process.exit(1)}console.log(d.upload_url.replace(/\{.*\}/,''))")
```

**Upload assets** — loop both MSIs, parse each response to confirm `state: "uploaded"`:

```bash
MSI_DIR=pc/src-tauri/target/release/bundle/msi
for f in CyberStream_<X.Y.Z>-pc.<n>_lite_x64.msi CyberStream_<X.Y.Z>-pc.<n>_full_x64.msi; do
  echo "uploading $f"
  curl -sS -x "$PROXY" -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"$MSI_DIR/$f" \
    "${UPLOAD}?name=${f}" | \
  node -e "let s='';process.stdin.on('data',c=>s+=c).on('end',()=>{const d=JSON.parse(s);console.log(' →',d.name||d.message,d.size||'',d.state||'')})"
done
```

Both should print `<name> <bytes> uploaded`. Sizes must match the local MSIs byte-exact.

### 10. Cleanup

```bash
rm -f release.json release.body.json
git status --short  # should show only any deferred changes (e.g. another session's work)
```

### 11. Tell the user

Print the release URL: `https://github.com/Purewo/CyberStream/releases/tag/v<X.Y.Z>-pc.<n>`. List asset sizes. Stop. Don't ask "want me to do anything else" — that breaks the default-to-action posture.

## Common gotchas (read before each release)

- **`cyber-backend.exe` size 175 MB instead of 32 MB**: `cyber-backend.spec` re-grew `collect_all('ddddocr')` / `collect_all('OpenCC')` or stopped excluding `onnxruntime/numpy/Pillow`. Backend code never imports any of these. Strip them; rebuild. The exclude list as of pc.2 is canonical.
- **`requirements.txt` install fails behind proxy**: missing `HTTPS_PROXY`/`HTTP_PROXY` env vars on the `uv pip install` line.
- **`cargo tauri build` says "libmpv-2.dll not found"**: `pc/vendor/mpv-dev/libmpv-2.dll` is gitignored and must be on disk. Don't auto-download — tell the user.
- **MSI output named `CyberStream_<v>_x64_en-US.msi`** without `-pc.N` — that's correct, you rename it after build.
- **`curl -d "$(cat <<JSON ... JSON)"` produces "Problems parsing JSON" 400**: heredoc quoting + multi-line markdown body is the issue. Use the file-based approach (Step 9).
- **Port 3000 already bound when running `cargo tauri dev` in parallel**: another Claude session has Vite up. Don't kill it without asking — they may be mid-work.
- **`git status` shows files you didn't write**: the parallel session. Don't stage them.
- **Hash drift after fetch**: parallel session rebased. Verify your commit messages still appear in `git log`; if so, content is intact.
- **`cd` persists across Bash tool calls**: so does `set -e`. Either use absolute paths everywhere, or `cd /g/AI/...` to reset.
- **Tag push fails "permission denied"**: PAT in credential store doesn't have `repo` scope. Tell the user.

## Don'ts

- Don't run `cargo clean` "just to be safe" before a release build — adds 10+ min.
- Don't push to a feature branch and expect the release flow to find it. Tag must be on `main`.
- Don't include `.env.local`, `cyber_library.db`, anything from `pc/vendor/`, or anything from `dist/` in commits.
- Don't write release notes that mention private hostnames, friend names, or token fragments.
- Don't mark a `-pc.N` release as `prerelease: false`.
- Don't bump `tauri.conf.json` version to include `-pc.N` — Tauri's SemVer parser rejects it.
