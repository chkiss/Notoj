#!/usr/bin/env bash
set -e

# --md-handler / --no-md-handler: register (or skip registering) notoj as the
# default application for markdown files. Without a flag, an interactive run
# asks; a non-interactive run (curl | bash) skips and prints how to enable.
#
# --auto-update / --no-auto-update: install (or skip) a notoj() shell function
# that pulls this repo in the background on every launch. This one defaults to
# ON: an interactive run asks with yes as the default, and a non-interactive
# run takes it. --no-auto-update declines, at install time or later.
MD_HANDLER=ask
AUTO_UPDATE=ask
for arg in "$@"; do
    case "$arg" in
        --md-handler)     MD_HANDLER=yes ;;
        --no-md-handler)  MD_HANDLER=no ;;
        --auto-update)    AUTO_UPDATE=yes ;;
        --no-auto-update) AUTO_UPDATE=no ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

REPO="https://github.com/chkiss/Notoj.git"
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

# Auto-update on launch. The symlink alone runs notoj perfectly well; the
# shell function only exists to pull first, so declining simply means no
# function is installed. Re-running the installer with the other answer
# switches it either way, which is why an existing function is removed
# before a new one is written.
has_shell_func() { grep -qF 'notoj() { git -C' "$RC" 2>/dev/null; }
remove_shell_func() {
    [ -f "$RC" ] || return 0
    grep -vF 'notoj() { git -C' "$RC" > "$RC.notoj.tmp" && mv "$RC.notoj.tmp" "$RC"
}

if [ "$AUTO_UPDATE" = ask ]; then
    if [ -t 0 ]; then
        if has_shell_func; then
            echo "Auto-update is currently ON (notoj pulls this repo before each launch)."
            read -r -p "Keep pulling updates automatically on launch? [Y/n] " reply
            case "$reply" in [Nn]*) AUTO_UPDATE=no ;; *) AUTO_UPDATE=yes ;; esac
        else
            echo "notoj can pull this repo in the background each time you launch it,"
            echo "so you always run the newest commit. It runs whatever it pulls."
            read -r -p "Pull updates automatically on launch? [Y/n] " reply
            case "$reply" in [Nn]*) AUTO_UPDATE=no ;; *) AUTO_UPDATE=yes ;; esac
        fi
    else
        AUTO_UPDATE=yes          # non-interactive: the default, same as the prompt's
        echo "Enabling launch-time auto-update (re-run with --no-auto-update to turn it off)"
    fi
fi

if [ "$AUTO_UPDATE" = yes ]; then
    if has_shell_func; then
        echo "Auto-update already enabled in $RC"
    else
        echo "" >> "$RC"
        echo "$SHELL_FUNC" >> "$RC"
        echo "Added notoj() auto-update function to $RC"
    fi
elif has_shell_func; then
    remove_shell_func
    echo "Removed the notoj() auto-update function from $RC"
    echo "Update by hand with: git -C $INSTALL_DIR pull"
else
    echo "Auto-update off. Update by hand with: git -C $INSTALL_DIR pull"
fi

# Optionally register notoj as the default application for markdown files:
# a double-clicked .md opens notoj in a terminal, imported (or, if it is
# already a note, just selected). Needs xdg-mime, so headless systems skip it.
if ! command -v xdg-mime >/dev/null 2>&1; then
    [ "$MD_HANDLER" = yes ] && echo "xdg-mime not found, skipping .md handler registration" >&2
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
