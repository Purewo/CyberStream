#!/usr/bin/env bash
# CyberStream Setup builder
# ----------------------------------------------------------------------------
# Usage:
#   bash pc/installer/scripts/build_setup.sh full 1.21.1-pc.4
#   bash pc/installer/scripts/build_setup.sh lite 1.21.1-pc.4
#
# 假设：
#   - cargo tauri build 已经成功（target/release/cyberstream-pc.exe + libmpv-2.dll）
#   - 完整版还要求 dist/cyber-backend.exe 存在（pyinstaller 打的 sidecar）
#   - makensis 在 PATH 里（NSIS 3.x）
#
# 这个脚本只做"组装 staging + 调 makensis"。前两段（pyinstaller + cargo build）
# 留给 docs/INSTALLER_BUILD.md 里的命令链或 CI。
set -euo pipefail

VARIANT="${1:?need variant: full|lite}"
APP_VERSION="${2:?need version, e.g. 1.21.1-pc.4}"

if [[ "$VARIANT" != "full" && "$VARIANT" != "lite" ]]; then
  echo "variant must be 'full' or 'lite', got: $VARIANT" >&2
  exit 1
fi

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
INSTALLER_DIR="$REPO_ROOT/pc/installer"
STAGING_DIR="$INSTALLER_DIR/.staging-$VARIANT"
OUT_DIR="$INSTALLER_DIR/dist"
RELEASE_DIR="$REPO_ROOT/pc/src-tauri/target/release"
SIDECAR_SRC="$REPO_ROOT/pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe"

OUT_FILE="$OUT_DIR/CyberStream_${APP_VERSION}_${VARIANT}_x64_setup.exe"

echo "==> Cleaning staging at $STAGING_DIR"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR" "$OUT_DIR"

echo "==> Verifying cargo build artifacts"
for f in "cyberstream-pc.exe" "libmpv-2.dll"; do
  if [[ ! -f "$RELEASE_DIR/$f" ]]; then
    echo "missing: $RELEASE_DIR/$f — run 'cargo tauri build' first" >&2
    exit 1
  fi
  cp "$RELEASE_DIR/$f" "$STAGING_DIR/"
done

if [[ "$VARIANT" == "full" ]]; then
  if [[ ! -f "$SIDECAR_SRC" ]]; then
    echo "missing: $SIDECAR_SRC" >&2
    echo "  build sidecar first:" >&2
    echo "    py -3.10 -m PyInstaller backend/cyber-backend.spec --clean --noconfirm" >&2
    echo "    cp dist/cyber-backend.exe pc/src-tauri/binaries/cyber-backend-x86_64-pc-windows-msvc.exe" >&2
    exit 1
  fi
  cp "$SIDECAR_SRC" "$STAGING_DIR/cyber-backend.exe"
fi

echo "==> Staged contents:"
ls -la "$STAGING_DIR"

echo "==> Running makensis"
# Windows-side absolute paths for makensis
STAGING_WIN="$(cygpath -w "$STAGING_DIR" 2>/dev/null || echo "$STAGING_DIR")"
OUT_WIN="$(cygpath -w "$OUT_FILE" 2>/dev/null || echo "$OUT_FILE")"

# Locate makensis: prefer PATH, fall back to default install dir
MAKENSIS="${MAKENSIS:-makensis}"
if ! command -v "$MAKENSIS" >/dev/null 2>&1; then
  for cand in \
    "/c/Program Files (x86)/NSIS/Bin/makensis.exe" \
    "/c/Program Files/NSIS/Bin/makensis.exe"; do
    if [[ -x "$cand" ]]; then
      MAKENSIS="$cand"
      break
    fi
  done
fi
if ! command -v "$MAKENSIS" >/dev/null 2>&1; then
  echo "makensis not found — install NSIS 3.x and ensure makensis is on PATH" >&2
  exit 1
fi

"$MAKENSIS" \
  -DVARIANT="$VARIANT" \
  -DAPP_VERSION="$APP_VERSION" \
  -DSTAGING_DIR="$STAGING_WIN" \
  -DOUT_FILE="$OUT_WIN" \
  "$INSTALLER_DIR/cyberstream.nsi"

echo ""
echo "==> Done: $OUT_FILE"
ls -la "$OUT_FILE"
