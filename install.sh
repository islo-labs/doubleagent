#!/bin/bash
set -e

REPO="islo-labs/doubleagent"
INSTALL_DIR="/usr/local/bin"

# Detect OS and architecture
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

case "$OS" in
  darwin)
    case "$ARCH" in
      arm64|aarch64) TARGET="aarch64-apple-darwin" ;;
      x86_64) echo "Error: macOS x86_64 not supported yet"; exit 1 ;;
      *) echo "Error: Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    ;;
  linux)
    case "$ARCH" in
      x86_64) TARGET="x86_64-unknown-linux-gnu" ;;
      aarch64|arm64) TARGET="aarch64-unknown-linux-gnu" ;;
      *) echo "Error: Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    ;;
  *)
    echo "Error: Unsupported OS: $OS"
    exit 1
    ;;
esac

# Get latest version
VERSION=$(curl -sSL "https://api.github.com/repos/$REPO/releases/latest" | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
VERSION_NUM=${VERSION#v}

FILENAME="doubleagent-${VERSION_NUM}-${TARGET}.tar.gz"
URL="https://github.com/$REPO/releases/download/$VERSION/$FILENAME"

echo "Installing DoubleAgent $VERSION for $TARGET..."

# Download and extract
TMPDIR=$(mktemp -d)
curl -sSL "$URL" -o "$TMPDIR/$FILENAME"
tar -xzf "$TMPDIR/$FILENAME" -C "$TMPDIR"

# Install
if [ -w "$INSTALL_DIR" ]; then
  mv "$TMPDIR/doubleagent" "$INSTALL_DIR/"
else
  sudo mv "$TMPDIR/doubleagent" "$INSTALL_DIR/"
fi

rm -rf "$TMPDIR"

echo "DoubleAgent installed to $INSTALL_DIR/doubleagent"
echo ""

# Check for mise
if ! command -v mise &> /dev/null; then
  echo "Note: mise is recommended for toolchain management."
  echo "Install mise: curl https://mise.run | sh"
  echo ""
fi

echo "Run 'doubleagent --help' to get started"
