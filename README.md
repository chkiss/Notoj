# notoj

A keyboard-driven terminal notes app: search, create, and browse plain
markdown files without leaving the terminal. Retrieval over organization,
plain files over databases, offline-first, friendly to Vim/Syncthing/CLI
workflows.

## Requirements

- Linux terminal, Python 3.8+ (stdlib only — no pip installs)
- `git` (snapshot history) and `vim` (editing, diffs, conflict resolution)
- Optional: Syncthing for multi-machine sync, an [OMDb API key](https://www.omdbapi.com/apikey.aspx)
  for rating tables, cron for the conflict sentinel

## Install

With GitHub SSH access set up:

```bash
git clone git@github.com:chkiss/Notoj.git ~/Notoj
bash ~/Notoj/install.sh && source ~/.bashrc
```

`install.sh` is idempotent: clones or updates `~/Notoj`, symlinks `notoj`
into `~/.local/bin`, adds it to `$PATH` in your bashrc/zshrc, and installs a
shell function so every launch first pulls the latest repo in the background.

On first launch notoj prompts for your notes directory (created if missing,
saved to `~/.config/notoj/config`) and — if the directory is empty — offers
to import a Simplenote JSON export. Neither prompt appears again.

## Configuration files

| Path | Purpose |
|---|---|
| `~/.config/notoj/config` | `notes_dir=...` — where your notes live |
| `~/.config/notoj/omdb_key` | OMDb API key for `update_ratings.py` (or env `OMDB_API_KEY`) |
| `NOTOJ_NOTES_DIR` (env) | Overrides the notes dir for the companion scripts |

## Using notoj

Run `notoj`. The screen is a note list with a preview pane; the footer always
shows the keys that matter in the current view, and `notoj --help` prints the
full keybinding reference. The essentials:

- `/` filters as you type; Enter opens the best match, or creates a new note
  titled with your query if nothing matches.
- Views: `g t` trash, `g d` duplicates, `g r` resurface (open loops),
  `T` all tags, `t` notes sharing the selected note's tags, `b` backlinks
  (notes whose `[[wikilinks]]` or `[text](note.md)` links point at the
  selected note — the same links Vim's `gf` follows). ESC steps back.
- `h`/`H` diff or browse a note's git history; `u`/`Ctrl-r` undo/redo
  trashes, loop-closes, tag additions, and edits; `?` shows the full key
  reference in-app.

## Note format

Notes are markdown files with YAML frontmatter (`id`, `created`, `modified`,
`title`, `tags`). The contract external tools should know:

- The first body line is the title, and the filename follows it — editing
  that line renames the file automatically.
- Inline `#hashtags` sync into the frontmatter `tags:` field on save.
  Fenced code blocks and `` `code` `` spans are exempt, so backtick a literal
  like `` `#B5B5B5` `` to keep it content. Add `notag: true` to the
  frontmatter to opt a whole note out (pasted configs, channel lists);
  in-app tagging with `#` still works there.
- `modified` and the file mtime are kept equal; scripts that edit notes
  should preserve both or notoj will treat the edit as new activity.

## Open loops (resurfacing)

Tag a note `#loop` and it appears in the resurface view (`g r`), most stale
first — a tickler, not spaced repetition. There you can snooze a week (`z`),
schedule precisely (`S`, e.g. `+2w`, `3mo`, `2026-12-01`), or close the loop
(`x`). Typing `#loop <when>` anywhere in a note's text schedules it from any
device; on save the relative horizon is pinned to an absolute date
(`#loop 3d` → `#loop 2026-06-12`), so re-saving never re-anchors it —
hand-edit that date to reschedule.

## The notes directory, git, and sync

notoj maintains a git repo inside the notes directory and commits every
edit, create, trash, restore, and conflict resolution automatically. It also
keeps a few private files there (auto-gitignored): `.trash/` (trashed
notes), `.notoj_state` (cursor position), `.notoj_review.json` (loop
snoozes).

Syncing the `.md` files with Syncthing works out of the box — external edits
are detected, reloaded, and committed, and sync-conflict copies are surfaced
in the header (`c` resolves them in vimdiff; the discarded version is
committed to history first, so it's always recoverable via `git show`).

**Do not sync the notes' `.git` directory** — each machine commits
independently, and syncing git internals corrupts the repo. In `.stignore`,
above any rule that includes the notes folder (Syncthing is
first-match-wins):

```
/path/to/notes/.git
!/path/to/notes/
```

## Companion scripts

### `update_ratings.py` — rating tables

Maintains a sorted `## Ratings` table (between `ratings:start/end` markers,
idempotent) in `Books.md`, `Movies.md`, and `TV shows.md`, from the plain
`- ` bullets you keep under `##` headings in those notes. Films/shows are
rated via OMDb (RT % for films, IMDb /10 for shows); books get `?` to fill
in by hand. Existing table rows are the source of truth and are preserved.

```bash
python3 update_ratings.py            # refresh all three notes
python3 update_ratings.py --dry-run  # show changes without writing
python3 update_ratings.py PATH       # one note
python3 update_ratings.py --no-new   # re-sort only; don't add titles
```

Bullet conventions: `- Title   # comment` keeps the comment out of the title
(`# ignore` skips the line; use `# ` with a space so the comment isn't
hashtag-synced), and `- Label: A; B; C` is split into one bullet per title
on the next run.

### `conflict_sentinel.py` — sync conflicts beyond the notes dir

notoj's `c` only sees `.md` conflicts inside the notes folder. The sentinel
sweeps **every** Syncthing folder (read from
`~/.local/state/syncthing/config.xml`) for any `*.sync-conflict-*` file and
writes one report note — `⚠ Sync conflicts — <host>.md`, tagged
`#syncconflict` — with a unified diff per conflict. It rewrites the note
only when the conflict set changes and deletes it when everything is clean.
Run it hourly:

```
0 * * * * python3 ~/Notoj/conflict_sentinel.py
```

### `simplenote_convert_to_md.py` — Simplenote import

Converts a Simplenote JSON export into notoj's markdown format (deleted
notes land in `.trash/`). notoj offers this automatically on first launch
into an empty notes dir; standalone:

```bash
python3 simplenote_convert_to_md.py <export_dir> [output_dir]
```

## Development

```bash
python3 test_notoj.py            # core app tests
python3 test_update_ratings.py   # rating-table tests
```
