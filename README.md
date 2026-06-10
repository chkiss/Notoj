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
| `u` | Undo last trash, loop-close (`x`), tag addition (`#`/`.`), or note edit — most recent first |
| `Ctrl-r` | Redo last undone action |

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

### Tags

| Key | Action |
|-----|--------|
| `#` | Add tags to the selected note (space-separated) — keeps the note's modified date |
| `.` | Repeat the last tag addition on the selected note — keeps the note's modified date |
| `t` | Filter to notes sharing the selected note's tags; `Tab` cycles the filter from all of them through each single tag |
| `T` | Browse all tags, most recently used first; `s` cycles sort (recent → count → name), `Enter` filters the notes list by the chosen tag, `ESC` backs out. From a filter opened this way, `ESC` returns to the tags view with the cursor on that tag |

### Resurface (open loops)

| Key | Action |
|-----|--------|
| `g r` | Toggle resurface view (notes tagged `#loop`, most stale first) |
| `z` | Snooze loop a week (quick "not now") |
| `S` | Schedule loop — set when it next resurfaces (`+2w`, `3mo`, `1y`, `2026-12-01`…) |
| `x` | Mark loop done (removes the `#loop` tag) |

### Other

| Key | Action |
|-----|--------|
| `h` | Diff selected note against its previous version (vimdiff) |
| `H` | Browse full version history with diff preview |
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

Hashtag sync skips fenced ``` code blocks and inline `` `code` `` spans — backtick a literal like `` `#B5B5B5` `` and it stays content, not a tag. For wholesale reference notes (pasted configs, channel lists, color palettes) where every inline `#` is a literal, add `notag: true` to the frontmatter to opt the whole note out of hashtag sync; manual tagging with the `#` key still works on such notes.

## Open loops (resurfacing)

Tag any note `#loop` to turn it into an open loop — something you want to be nudged about again later. Press `g r` to enter the **resurface view**, which lists only `#loop` notes, most stale first (longest since you last touched them). From there:

- `z` snoozes the note for a week — a quick "not now".
- `S` schedules exactly when it should next resurface: relative (`+2w`, `3mo`, `1y`) or an absolute date (`2026-12-01`).
- `x` closes the loop, removing the `#loop` tag. Closing is undoable with `u` (and redoable with `Ctrl-r`), alongside trashes and note edits.

You can also schedule inline, without leaving the note: type `#loop <when>` anywhere in its text — `#loop 3d`, `#loop 2w`, `#loop tomorrow`, or an absolute `#loop 2026-12-01`. On save, a relative horizon is pinned to the date it resolved to (`#loop 3d` becomes `#loop 2026-06-12`), so re-editing the note never re-anchors the reminder; hand-edit that date to reschedule. This works from any device — a note synced in from your phone schedules itself when it lands. Closing the loop with `x` removes the pinned date along with the tag.

This is a **tickler**, not spaced repetition: notes surface when they're due (or overdue), so capture turns into follow-through instead of a pile you never revisit.

## Rating tables (`update_ratings.py`)

`update_ratings.py` keeps a `## Ratings` summary table at the top of your media notes, built from the `- ` bullets you list in them. Keep a running list of films, books, or shows as plain bullets and it turns them into a sorted, rated table.

It works on notes named `Books.md`, `Movies.md`, and `TV shows.md` (in your notes directory) — the filename is how it knows to rate each title as a book, film, or show. A default run updates those three; you can also pass a single note's path. Inside the note, it reads `- ` bullets under any `## ` heading as the titles to rate.

The note is the source of truth: existing ratings are read back from the table and preserved. Any title that appears in a `##` section but isn't yet in the table is treated as new:

- **Movies / TV shows** are looked up via the [OMDb API](https://www.omdbapi.com/apikey.aspx). Movies show Rotten Tomatoes %% (falling back to IMDb /10 where there's no RT page); TV shows show IMDb /10.
- **Books** are inserted as `?` for you to fill in by hand (no free Goodreads API).

The table is rewritten between `<!-- ratings:start -->` / `<!-- ratings:end -->` markers, so re-running is idempotent. Rows are sorted by rating.

```bash
python3 update_ratings.py              # refresh all three notes
python3 update_ratings.py --dry-run    # show changes without writing
python3 update_ratings.py "/path/to/Movies.md"   # one note
python3 update_ratings.py --no-new     # re-sort/migrate only; don't add titles
```

The OMDb key is read from `OMDB_API_KEY` or `~/.config/notoj/omdb_key`; without it, new films/shows also get `?`. The notes directory defaults to `~/Documents/dokumentoj/notes` (override with `NOTOJ_NOTES_DIR`).

In a bullet, text after a space-then-`#` is a comment that's stripped from the title (e.g. `- The Dark Knight   # rewatched`). If the comment is an ignore directive (`# ignore`, `# skip`, `# hide`, `# x`), the whole line is skipped. Use `# ` with a space so notoj doesn't sync the comment as a hashtag.

You can list several films on one bullet separated by `;` (e.g. `- Bollywood from Neel: Lagaan; Queen; Bandit Queen`). On the next run each becomes its own bullet so it gets rated individually, and a leading `Label:` is dropped. The `;` is only treated as a separator when the whole bullet isn't itself a real title on OMDb, so the rare film with a semicolon in its name is left intact.

## Sync and conflicts

notoj works well with Syncthing. External edits are detected and reloaded automatically. Syncthing sync-conflict files are detected and surfaced in the header; press `c` to resolve them in vimdiff. The conflict copy is committed to the snapshot history before it is deleted, so a version discarded during resolution can always be recovered with `git show`.

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
