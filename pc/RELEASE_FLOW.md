# Release flow · PC client

This is the playbook for cutting a `vX.Y.Z-pc.N` release.

## 1. Bump versions

| File | Field |
|---|---|
| `pc/src-tauri/Cargo.toml` | `[package].version` |
| `pc/src-tauri/tauri.conf.json` | `version` |
| `frontend/package.json` | `version` (optional — keep aligned with backend) |

## 2. Build the MSI

```bash
# from repo root
cd pc/src-tauri
cargo tauri build
```

Output:

```
pc/src-tauri/target/release/bundle/msi/CyberStream_1.21.0_x64_en-US.msi   ~50 MB
```

The MSI bundles `pc/vendor/mpv/*` so the recipient does not need to install
mpv separately. Make sure `pc/vendor/mpv/mpv.exe` exists before building.

NSIS is intentionally disabled in `tauri.conf.json` — the toolchain pulls
`nsis-3.11.zip` from GitHub at build time, which often times out from
regional networks. Re-enable in `bundle.targets` if you need it.

## 3. Smoke test on a clean machine

- Run the MSI on a Windows 11 box that does **not** have CyberStream
  installed.
- Open the app — first run should land on the home page.
- Profile → SYSTEM → 后端服务器 → "运行检测" should report
  `OK · mpv vX.Y.Z · pipe=...`.
- Pick a movie, click any external-player icon (PotPlayer, IINA, VLC…).
  The OS should hand off cleanly without SmartScreen/Edge intercepting.

## 4. Tag

```bash
git tag -a v1.21.0-pc.0 -m "PC client 1.21.0-pc.0 — first installable build"
git push origin v1.21.0-pc.0
```

## 5. Publish the release

Either:

**(a) Web UI** — go to <https://github.com/Purewo/CyberStream/releases/new>,
pick the tag, drag the MSI into the asset uploader.

**(b) `gh` CLI** — install from <https://cli.github.com/>, then:

```bash
gh auth login
gh release create v1.21.0-pc.0 \
  pc/src-tauri/target/release/bundle/msi/CyberStream_1.21.0_x64_en-US.msi \
  --title "CyberStream PC 1.21.0-pc.0" \
  --notes-file pc/RELEASE_NOTES_TEMPLATE.md
```

A reusable notes template lives at `pc/RELEASE_NOTES_TEMPLATE.md`.

## 6. Post-release

- Sanity-check the download link in the top-level READMEs.
- Bump `docs/PC_CLIENT_GOAL.md` status if a milestone moved.
- Open issues for anything you regret shipping; close the milestone.
