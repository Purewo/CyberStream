# Local recovery backup — 2026-10-20

Target: `https://github.com/Purewo/CyberStream`

Backup branch: `backup/local-recovery-20261020`, based on `630bfb8`.

Scope: current Web/PC working source, isolated Android recovery project,
native FFmpeg AAR, Gradle wrapper, package locks, both original Android APKs,
recovery provenance, three PC source archives and earlier source candidates.
The pre-existing local `cdn_cleanup.py` and its test are included unchanged as
work in progress, not claimed tested/reviewed or deployed by the frontend owner.

This is a preservation snapshot, not a release or a merge into `main`. The
Android verification reported in its handoff was performed before this backup;
the entire mixed Web/PC/backend tree has not been regression-tested together.

Do not delete the checkout or its ignored recovery files merely because this
branch exists. Credentials, `.env.local`, database/account state, browser
profiles, emulator disks, installed PC binaries and caches are intentionally
not uploaded. Original Android APKs are uploaded because they are unique
recovery evidence; rebuilt test APKs remain on the Desktop and can be rebuilt.

Verify the actual remote commit with `git ls-remote origin
refs/heads/backup/local-recovery-20261020`. A local commit alone is not proof
that GitHub received it.
