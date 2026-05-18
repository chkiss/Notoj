#!/usr/bin/env bash
set -e

REPO="git@github.com:chkiss/Notoj.git"
INSTALL_DIR="$HOME/Notoj"
BIN_DIR="$HOME/.local/bin"
SHELL_FUNC='notoj() { git -C ~/Notoj pull --ff-only -q 2>/dev/null & ~/Notoj/notoj "$@"; }'
PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

# Detect shell rc file
if [ -n "$ZSH_VERSION" ] || [ "$(basename "$SHELL")" = "zsh" ]; then
    RC="$HOME/.zshrc"
else
    RC="$HOME/.bashrc"
fi

# Clone or update repo
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing repo..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    echo "Cloning repo..."
    git clone "$REPO" "$INSTALL_DIR"
fi

# Create bin dir
mkdir -p "$BIN_DIR"

# Create or re-point symlink
ln -sf "$INSTALL_DIR/notoj" "$BIN_DIR/notoj"

# Add PATH export if missing
if ! grep -qF "$PATH_LINE" "$RC" 2>/dev/null; then
    echo "" >> "$RC"
    echo "$PATH_LINE" >> "$RC"
    echo "Added PATH export to $RC"
fi

# Add shell function if missing
if ! grep -qF 'notoj()' "$RC" 2>/dev/null; then
    echo "" >> "$RC"
    echo "$SHELL_FUNC" >> "$RC"
    echo "Added notoj() function to $RC"
fi

echo "Done. Run: source $RC"
