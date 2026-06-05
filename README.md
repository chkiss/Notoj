# notoj

A keyboard-driven terminal notes app. Search, create, and browse plain-text markdown notes without leaving the terminal.

## Install

After setting up GitHub SSH access on the machine:

```bash
git clone git@github.com:chkiss/Notoj.git ~/Notoj
bash ~/Notoj/install.sh && source ~/.bashrc
```

`install.sh` creates `~/.local/bin` if needed, symlinks the script, adds it to `$PATH`, and installs a shell function that auto-updates the repo on each launch. Safe to run multiple times — skips steps already done.

## First launch

Run `notoj` and it will walk you through setup:

1. **Notes directory** — enter the path where your notes live (created if it doesn't exist)
2. **Simplenote import** — if the directory is empty, you'll be offered the option to import from a Simplenote JSON export:

```
notoj: no notes directory configured.
Notes directory [~/notes]: ~/my-notes

Notes directory is empty. Import from a Simplenote export? [y/N] y
Path to Simplenote export directory: ~/Downloads/simplenote-export
  notes.json  →  my-first-note.md
  ...
42 note(s) converted

[notoj launches]
```

The notes directory is saved to `~/.config/notoj/config`. Neither prompt appears again once notes exist.

## Usage

```
notoj
```

```
notoj --help
```

Print keybindings and exit.

## Keybindings

### Navigation

| Key | Action |
|-----|--------|
| `j` / `↓` | Move down |
| `k` / `↑` | Move up |
| `g g` | Jump to top |
| `G` | Jump to bottom |
| `Ctrl-f` | Page down |
| `Ctrl-b` | Page up |
| `Ctrl-d` | Half-page down |
| `Ctrl-u` | Half-page up |
| `PgDn` / `PgUp` | Scroll preview pane |

### Notes

| Key | Action |
|-----|--------|
| `Enter` | Open note in Vim at top |
| `e` | Open note in Vim at bottom (for appending) |
| `n` | Create a new blank note |
| `d` | Move note to trash |
| `u` | Restore most recently trashed note |

### Search

| Key | Action |
|-----|--------|
| `/` | Enter search mode |
| *(type)* | Filter notes live as you type |
| `Enter` | Open selected note (or create new note titled with query if none match) |
| `ESC` | Exit search mode |

### Sorting

| Key | Action |
|-----|--------|
| `s` | Cycle sort: modified → title → created |
| `r` | Reverse sort order |

### Other

| Key | Action |
|-----|--------|
| `c` | Resolve next Syncthing conflict in vimdiff |
| `q` | Quit |

## Note format

Notes are plain markdown files with a YAML frontmatter block:

```markdown
---
id: <uuid>
created: 2025-01-01T12:00:00Z
modified: 2025-01-01T12:00:00Z
title: My note title
tags:
  - example
---

First line becomes the title.

Body text here. Use #hashtags inline — they are automatically
synced to the frontmatter tags field.
```

The filename is derived from the first line of the body. Renaming a note (editing its first line) renames the file automatically.

## Sync and conflicts

notoj works well with Syncthing. External edits are detected and reloaded automatically. Syncthing sync-conflict files are detected and surfaced in the header; press `c` to resolve them in vimdiff.

A local git repository is maintained in the notes directory for snapshot history. Every edit, create, trash, restore, and conflict resolution is committed automatically.

**Do not sync the notes' `.git` directory.** notoj commits independently on each machine, so syncing `.git` produces constant index/object conflicts and can corrupt the repo. If you use Syncthing, add the notes' `.git` to `.stignore` — and place it *above* any rule that includes the notes folder, since Syncthing is first-match-wins:

```
/path/to/notes/.git
!/path/to/notes/
```

The `.md` files (and the frontmatter version counter) still sync; only git internals stay machine-local.

## Philosophy

- Retrieval over organization — search replaces folders
- Plain files — notes are readable and editable by any tool
- Offline-first — no cloud dependency
- External-tool friendly — Vim, Syncthing, and CLI workflows all work naturally
