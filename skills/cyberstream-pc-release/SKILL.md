---
name: cyberstream-pc-release
description: Cut a CyberStream PC desktop release (Tauri 2 + libmpv). Use when the user asks to publish, release, ship, or build the PC client — e.g. "发个 release", "打个新版本", "发布最新版", "ship 1.21.x". Covers version bump, default backend reset, PyInstaller backend sidecar, MSI build (lite + full), GitHub release with asset upload via REST API. Repo: https://github.com/Purewo/CyberStream.
---

# CyberStream PC Release

## Project facts (load these into context first)

- **Repo root**: `G:\AI\AI_private\Cluade_code_projects\CyberStream-repo` on this machine
- **Three apps in one repo**: `backend/` (Flask), `frontend/` (React+Vite), `pc/` (Tauri 2)
- **PC versioning is dual-tracked**: semver in `pc/src-tauri/tauri.conf.json` + `frontend/package.json` is `1.21.1` style; the **release tag/asset name** carries a `-pc.N` suffix (`v1.21.1-pc.2`). MSI filenames embed the full string.
- **Two MSI variants** ship together every release:
  - `lite` (~14 MB): no embedded backend; user connects to their own NAS/VPS via 「设置 → 后端服务器」
  - `full` (~120 MB): bundles `cyber-backend.exe` (PyInstaller-frozen Flask, listens 127.0.0.1:49152) as a Tauri sidecar
- **MSI naming convention**: `CyberStream_<version>-pc.<n>_<variant>_x64.msi`
- **gh CLI is NOT installed**. Use `git push` for code/tags and the GitHub REST API for releases.
- **HTTPS proxy required for GitHub from this machine**: `http://127.0.0.1:10808` (set both `HTTPS_PROXY` and `HTTP_PROXY`).
- **Bash on this Windows host writes Windows paths**, so use `./tmp/` not `/tmp/` when staging files in repo.

## Hard rules

- Default backend in shipped builds: **empty string** (`PC_DEFAULT_API_BASE = ''`). Never bake a developer's private origin into a public release. If the user explicitly asks for a test-only MSI pinned to a specific URL, do that on a throwaway branch and don't tag/release it.
- Do not skip git hooks, do not force-push, do not amend already-pushed commits.
- The Anthropic / TMDB tokens, the GitHub PAT, and any `.env.local` content must never appear in commits, release notes, or asset metadata. Read them via env vars; if scrubbing is needed, do it before staging.
- Don't modify backend code as part of release work unless a release-blocker bug requires it. Backend version bumps follow `docs/VERSIONING.md` if present.
- Two unrelated Claude sessions sometimes work the same repo concurrently. Inspect `git status` before staging — anything you didn't change probably belongs to the other session; leave it alone.
- Default to action: when the user says "发布", proceed through the workflow without re-asking the standard set of questions (variant, version bump, default backend) — those answers are codified here. Only ask if there's an actual ambiguity for **this** release.

## Workflow

### 0. Triage

```bash
git status --short
git log --oneline <last-pc-release-tag>..HEAD
```

- Decide bump: bug fixes only → patch suffix only (`-pc.<n+1>`), keep core semver. New user-visible feature → bump core semver minor and reset suffix to `-pc.0`.
- Confirm there are no uncommitted untracked files that should be in the release. Watch out for files written by a parallel session.

### 1. Reset default backend to empty (if not already)

`frontend/src/platform/pc.ts`:
```ts
const PC_DEFAULT_API_BASE = '';
```

This forces first-run users into the settings page. The lite build relies on this.

### 2. Bump version

Same `1.21.x` value in both:
- `pc/src-tauri/tauri.conf.json` → `"version"`
- `frontend/package.json` → `"version"`

The `-pc.<n>` suffix only lives in: git tag, release notes filename, MSI asset filename. **Don't put it in tauri.conf.json** — Tauri doesn't accept SemVer prereleases there cleanly.

### 3. Write release notes

`pc/RELEASE_NOTES_<version>-pc.<n>.md`. Follow the structure of the previous notes:

- 一段开篇说明 (vs the previous version, what's new)
- 「下载选哪个？」 lite vs full table
- 「主要变化」分小节列出 fixes/features
- 「已知坑」
- 「升级指南」

UI strings stay Chinese (Simplified). Code/CLI snippets in English.

### 4. Build the backend sidecar (full build only)

Skip if shipping lite-only.

```bash
cd backend
# Activate the venv that has pyinstaller + waitress + reqs installed.
# The spec file pins the entry point and bundles .env.local handling.
pyinstaller cyber-backend.spec --clean
# Output: backend/dist/cyber-backend.exe (~28 MB)
# Copy to where Tauri's externalBin expects it:
cp dist/cyber-backend.exe ../pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe
```

If `cyber-backend.spec` doesn't exist or your venv is missing pyinstaller, ask the user — don't try to invent the spec.

### 5. Build the lite MSI

```bash
cd pc/src-tauri
# Temporarily strip externalBin from tauri.conf.json so MSI doesn't bundle the sidecar.
# Easiest: keep two conf files (tauri.conf.lite.json) and pass --config, OR sed the array out and restore after.
cargo tauri build --config '{"bundle":{"externalBin":[]}}'
```

Output lands in `pc/src-tauri/target/release/bundle/msi/`. Rename:

```bash
mv 'CyberStream_<v>_x64_en-US.msi' "CyberStream_<v>-pc.<n>_lite_x64.msi"
```

### 6. Build the full MSI

```bash
cd pc/src-tauri
cargo tauri build  # uses tauri.conf.json with externalBin in place
mv 'CyberStream_<v>_x64_en-US.msi' "CyberStream_<v>-pc.<n>_full_x64.msi"
```

`cargo tauri build` will rebuild from scratch when externalBin changes; that's expected and unavoidable.

### 7. Stage everything in git

```bash
git add pc/src-tauri/tauri.conf.json frontend/package.json \
        frontend/src/platform/pc.ts \
        pc/RELEASE_NOTES_<v>-pc.<n>.md
git commit -m "release: <v>-pc.<n>"
git tag "v<v>-pc.<n>"
```

Don't commit MSI files (they're large binaries — they go to GitHub releases as attachments).

### 8. Push (proxy required)

```bash
HTTPS_PROXY=http://127.0.0.1:10808 HTTP_PROXY=http://127.0.0.1:10808 \
  git push origin main
HTTPS_PROXY=http://127.0.0.1:10808 HTTP_PROXY=http://127.0.0.1:10808 \
  git push origin "v<v>-pc.<n>"
```

### 9. Create GitHub release via REST API

`gh` is not installed. Use the PAT and curl. The PAT is supplied by the user; never hardcode. Common pattern:

```bash
TOKEN="$(read_token)"  # ask user once per session
PROXY="http://127.0.0.1:10808"

# Create release
curl -sS -x "$PROXY" -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Purewo/CyberStream/releases \
  -d "$(cat <<JSON
{
  "tag_name": "v<v>-pc.<n>",
  "name": "CyberStream PC <v>-pc.<n>",
  "body": "<contents of release notes file, JSON-escaped>",
  "draft": false,
  "prerelease": true
}
JSON
)" > release.json

UPLOAD_URL=$(node -e "console.log(JSON.parse(require('fs').readFileSync('release.json','utf8')).upload_url.replace(/\{.*\}/,''))")
```

Upload each MSI:

```bash
for f in CyberStream_*-pc.<n>_*_x64.msi; do
  curl -sS -x "$PROXY" -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@$f" \
    "${UPLOAD_URL}?name=${f}"
done
```

Verify in the response that each asset has `state: "uploaded"` and a non-zero `size`.

### 10. Sanity check

```bash
curl -sS -x http://127.0.0.1:10808 \
  https://api.github.com/repos/Purewo/CyberStream/releases/latest \
  | node -e "let s='';process.stdin.on('data',c=>s+=c).on('end',()=>{const d=JSON.parse(s);console.log(d.tag_name);console.log(d.assets.map(a=>a.name+' '+a.size).join('\n'))})"
```

Expected: tag matches, both MSI assets present with sane sizes (lite ~14 MB, full ~120 MB).

## Don't

- Don't run `cargo clean` before a release build "just to be safe" — it adds 10+ minutes for nothing.
- Don't push to a feature branch then expect Tauri's auto-updater (there isn't one yet) to find it. Releases must be tagged on `main`.
- Don't include `.env.local`, `cyber_library.db`, or anything from `pc/vendor/` in the commit. They're in `.gitignore` already; don't override.
- Don't write release notes that mention private hostnames, friend names, or token fragments.
- Don't mark a release `prerelease: false` while the suffix is `-pc.N` — those are still pre-release builds.

## When to ask the user

Almost never. The standard answers:

- Variant → both lite and full
- Version bump → patch suffix unless the changelog has a user-visible feature
- Default backend → empty string
- Proxy → `http://127.0.0.1:10808`
- Tag style → `vX.Y.Z-pc.N`
- Release type → `prerelease: true`

Ask only when:
- A bump straddles backend version too (then `docs/VERSIONING.md` rules apply, may need backend changes)
- Build outputs an MSI that's wildly off the expected size (could indicate missing libmpv or sidecar)
- The user's working tree contains files you didn't author and you can't tell whether they should ship
