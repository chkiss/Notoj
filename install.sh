#!/usr/bin/env bash
set -e

# --md-handler / --no-md-handler: register (or skip registering) notoj as the
# default application for markdown files. Without a flag, an interactive run
# asks; a non-interactive run (curl | bash) skips and prints how to enable.
MD_HANDLER=ask
for arg in "$@"; do
    case "$arg" in
        --md-handler)    MD_HANDLER=yes ;;
        --no-md-handler) MD_HANDLER=no ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

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

# Optionally register notoj as the default application for markdown files:
# a double-clicked .md opens notoj in a terminal, imported (or, if it is
# already a note, just selected). Needs xdg-mime, so headless systems skip it.
if ! command -v xdg-mime >/dev/null 2>&1; then
    [ "$MD_HANDLER" = yes ] && echo "xdg-mime not found — skipping .md handler registration" >&2
    MD_HANDLER=no
fi
if [ "$MD_HANDLER" = ask ]; then
    if [ -t 0 ]; then
        read -r -p "Make notoj the default editor for .md files? [y/N] " reply
        case "$reply" in [Yy]*) MD_HANDLER=yes ;; *) MD_HANDLER=no ;; esac
    else
        MD_HANDLER=no
        echo "Skipping .md handler registration (re-run with --md-handler to enable)"
    fi
fi
if [ "$MD_HANDLER" = yes ]; then
    APP_DIR="$HOME/.local/share/applications"
    mkdir -p "$APP_DIR"
    printf '%s\n' \
        "[Desktop Entry]" \
        "Type=Application" \
        "Name=notoj" \
        "Comment=keyboard-driven terminal notes" \
        "Exec=$BIN_DIR/notoj %f" \
        "Terminal=true" \
        "MimeType=text/markdown;text/x-markdown;" \
        "Categories=Utility;TextEditor;" \
        > "$APP_DIR/notoj.desktop"
    xdg-mime default notoj.desktop text/markdown
    xdg-mime default notoj.desktop text/x-markdown
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "$APP_DIR" || true
    echo "Registered notoj as the default editor for markdown files"
fi

echo "Done. Run: source $RC"
