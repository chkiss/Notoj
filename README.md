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

It also offers to make notoj the default application for markdown files, so
double-clicking a `.md` in a file manager opens notoj in a terminal and
imports it (a file already in the notes directory is just selected). The
prompt only appears on interactive runs; pass `--md-handler` to enable it
non-interactively or `--no-md-handler` to never ask. It installs a desktop
entry at `~/.local/share/applications/notoj.desktop` and registers it with
`xdg-mime` — delete the file and re-run `xdg-mime default <your-editor>.desktop
text/markdown` to undo.

On first launch notoj prompts for your notes directory (created if missing,
saved to `~/.config/notoj/config`) and — if the directory is empty — offers
to import a Simplenote JSON export. Neither prompt appears again.

## Configuration files

| Path | Purpose |
|---|---|
| `~/.config/notoj/config` | `notes_dir` plus optional editor, display, color and key-remap settings — see [`config.example`](config.example) |
| `~/.config/notoj/omdb_key` | OMDb API key for `update_ratings.py` (or env `OMDB_API_KEY`) |
| `NOTOJ_NOTES_DIR` (env) | Overrides the notes dir for the companion scripts |

`~/.config/notoj/config` is plain `key = value` lines (`#` comments); booleans
take `true/false/yes/no/on/off/1/0`. The main options:

| Key | Default | What it does |
|---|---|---|
| `notes_dir` | *(set on first run)* | Where notes live — required |
| `default_editor` | `vim` | Editor for opening/creating notes (`$NOTOJ_VIM` wins over it) |
| `tag_editor.<tag>` | — | Per-tag editor override — e.g. open `#arabic` notes in mlterm, `#hindi` in a GUI editor |
| `render_markdown` | `true` | Render light markdown in the preview pane (master switch) |
| `markdown_asterisk` | `true` | Style `*italic*` / `**bold**` |
| `markdown_underscore_italic` | `false` | Style `_italic_` (off leaves `snake_case` alone) |
| `markdown_underscore_bold` | `false` | Style `__bold__` (off leaves `__dunder__` alone) |
| `reshape_arabic` | `true` | Pre-shape Arabic-script text in the list and preview so it isn't isolated |
| `preview_wrap` | `true` | Word-wrap the preview body; off clips each line at the pane edge |
| `preview_tags` | `always` | Show a `#tag` row atop the preview when the search matched a tag — `always`, `narrow` (only when the list's tags column is hidden), `never` |
| `preview_scroll` | `page` | Lines PgDn/PgUp scroll any preview pane — `page`, or a line count |
| `list_max_w` | `80` | Max width of the left list panel; extra width goes to the preview |
| `tag_display_order` | `freq` | Tag order for display — `freq`, `freq_asc`, `name`, `stored` |
| `undo.persist` | `true` | Keep the undo history across sessions |
| `color.<slot>` | — | Colors for `accent`, `date`, `tag`, `preview`, `header`, `match`, `match_fuzzy`, `match_focus_fg`/`_bg`, `footer_bg`, plus the `date_gradient` |
| `key.<action>` | — | Remap any key, including the `g_` chords |

[`config.example`](config.example) documents every option in full.

## Using notoj

Run `notoj`. The screen is a note list with a preview pane; the footer always
shows the keys that matter in the current view, and `notoj --help` prints the
full keybinding reference. The essentials:

- `/` filters as you type; Enter opens the best match, or creates a new note
  titled with your query if nothing matches. The header says what the selected
  note actually matched and how often — `matched: cat (3), food (0)` — with a
  `~word` naming the spelling behind a near-miss, so a result never leaves you
  guessing why it's there. Matches are highlighted in
  magenta, and the preview pane opens on the first one rather than at the top
  of the note — the hit you're on is shown as a band, the rest as text, and
  `n`/`N` step through them (`o` creates a new note). Enter then opens the note
  in Vim *at that hit*, not back at the first one, with `n`/`N` carrying on
  from there (a quoted `"phrase"` is matched across line breaks too).
- Views: `g t` trash, `g d` duplicates, `g r` resurface (open loops),
  `T` all tags, `t` notes sharing the selected note's tags, `b` backlinks
  (notes whose `[[wikilinks]]` or `[text](note.md)` links point at the
  selected note — the same links Vim's `gf` follows). ESC steps back.
- `h`/`m`/`l` jump to the top/middle/bottom of the visible page in any list;
  at the `#` tag prompt, `Tab` completes against the tags you already use.
- `g h`/`H` diff or browse a note's git history; `u`/`Ctrl-r` undo/redo
  trashes, loop-closes, tag additions, and edits — and, with `undo.persist`
  on (the default), across sessions too, prompting before it reaches into a
  previous session's changes; `?` shows the full key reference in-app.

### Importing a file

`notoj path/to/draft.md` copies that markdown file into the notes directory,
adopts it as a note, and opens with it selected. Adoption is the same pipeline
an incoming Syncthing file goes through: a BOM and CRLF endings are stripped,
missing frontmatter is filled in, the title comes from the first body line and
the file is renamed to match it, and inline `#hashtags` sync into `tags:`.
The note's `created`/`modified` come from the source file's mtime, so an old
draft keeps its real dates rather than looking like it was written today. The
original is left where it is (`--move` removes it once the copy is committed),
and an existing note is never overwritten — a clashing name imports as
`name (2).md`. Several files can be named at once; the first is selected.

Every import records its provenance in a footer line appended to the note —
`copied from /path/to/draft.md, original untouched`, or
`moved from /path/to/draft.md` under `--move` — without touching the
mtime-derived dates. A path that is already inside the notes directory is not
re-imported: notoj simply opens with that note selected, which makes
`notoj FILE.md` safe to register as the system handler for markdown files
(`install.sh` offers this, or forces it with `--md-handler`).

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
