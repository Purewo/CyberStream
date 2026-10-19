# Recovery backup

This directory contains irreplaceable client recovery source and evidence.
It is not a disposable build/cache directory.

- Android editable project: `android-20261020/project/` (including the pinned FFmpeg AAR).
- Original Android APKs: `android-20261020/original-apks/`.
- Android recovery provenance and current limitations: `android-20261020/RESTORATION.md`.
- Current PC implementation: repository `pc/` and `frontend/`.
- Earlier PC source snapshots: `CyberStream-PC-recovered-source-20260930*.zip`,
  `pc-source-candidate/`, `shell-source-candidate/`.

Git backup excludes browser profiles, credentials, emulator data, runtime
databases, dependency caches and reproducible build output. Excluded files
remain on the original machine; these rules do not authorize deleting them.

Historical `gitCommitted: false` / `githubPushed: false` fields describe the
date of their original handoff, not the latest backup operation. See
`docs/GITHUB_BACKUP_2026-10-20.md` for the backup branch and scope.
