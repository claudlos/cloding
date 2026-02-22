#!/bin/bash
set -euo pipefail

# install.sh — Install cloding on macOS/Linux
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/claudlos/cloding/master/install.sh | bash
#
# Environment:
#   CLODING_INSTALL_DIR   Override install directory (default: /usr/local/bin or ~/.local/bin)

REPO="claudlos/cloding"
BINARY_NAME="cloding"

# ── Detect OS and architecture ──
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$OS" in
  linux)  PLATFORM="linux" ;;
  darwin) PLATFORM="darwin" ;;
  *)
    echo "Error: Unsupported OS: $OS"
    echo "For Windows, use: irm https://raw.githubusercontent.com/$REPO/master/install.ps1 | iex"
    exit 1
    ;;
esac

case "$ARCH" in
  x86_64|amd64)  ARCH_SUFFIX="x64" ;;
  aarch64|arm64)  ARCH_SUFFIX="arm64" ;;
  *)
    echo "Error: Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

ASSET_NAME="cloding-${PLATFORM}-${ARCH_SUFFIX}"

# ── Determine install directory ──
if [ -n "${CLODING_INSTALL_DIR:-}" ]; then
  INSTALL_DIR="$CLODING_INSTALL_DIR"
elif [ -w "/usr/local/bin" ]; then
  INSTALL_DIR="/usr/local/bin"
else
  INSTALL_DIR="$HOME/.local/bin"
  mkdir -p "$INSTALL_DIR"
fi

# ── Get latest release tag ──
echo "Fetching latest release..."
LATEST_TAG=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
  | grep '"tag_name"' \
  | sed -E 's/.*"v?([^"]+)".*/\1/')

if [ -z "$LATEST_TAG" ]; then
  echo "Error: Could not determine latest release."
  echo "Check: https://github.com/$REPO/releases"
  exit 1
fi

DOWNLOAD_URL="https://github.com/$REPO/releases/download/v${LATEST_TAG}/${ASSET_NAME}"

echo "Downloading cloding v${LATEST_TAG} (${PLATFORM}/${ARCH_SUFFIX})..."
echo "  ${DOWNLOAD_URL}"

# ── Download to temp file ──
TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

if ! curl -fsSL -o "$TMP_FILE" "$DOWNLOAD_URL"; then
  echo "Error: Download failed."
  echo "Check releases at: https://github.com/$REPO/releases"
  exit 1
fi

chmod +x "$TMP_FILE"

# ── Install ──
if [ -w "$INSTALL_DIR" ]; then
  mv "$TMP_FILE" "${INSTALL_DIR}/${BINARY_NAME}"
else
  echo "Installing to ${INSTALL_DIR} (requires sudo)..."
  sudo mv "$TMP_FILE" "${INSTALL_DIR}/${BINARY_NAME}"
fi

# ── Check if install dir is in PATH ──
case ":$PATH:" in
  *":${INSTALL_DIR}:"*) ;;
  *)
    echo ""
    echo "Note: ${INSTALL_DIR} is not in your PATH."
    echo "Add it to your shell profile:"
    echo "  export PATH=\"${INSTALL_DIR}:\$PATH\""
    ;;
esac

echo ""
echo "✓ cloding v${LATEST_TAG} installed to ${INSTALL_DIR}/${BINARY_NAME}"
echo ""
echo "Get started:"
echo "  export OPENROUTER_API_KEY=sk-or-v1-..."
echo "  cloding"
echo "  cloding setup   # Install all CLI tools (Claude, Gemini, Codex, etc.)"
echo ""
