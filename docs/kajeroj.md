# Kajeroj

A *kajero* (Esperanto: notebook) is a folder inside the vault that holds the
notes carrying one tag. Opened from the vault root, notoj lists the kajero's
notes alongside every other note. Opened on the kajero folder itself, notoj
sees only those notes. Pointing a second machine's Syncthing at the kajero
folder alone gives it that subset and nothing else.

Syncthing filters by path, never by file contents, and the device that sends
a folder announces every filename in it to every peer, ignored or not. So a
subset that must not leak its neighbours' names has to be a folder of its
own. The tag is how the user says which notes belong there; notoj does the
filing.

## Declaring one

A kajero is a direct subdirectory of the vault containing a marker file,
`.notoj-kajero`, in notoj's `key = value` config syntax:

```
tag = arlyn
```

A missing or empty `tag` falls back to the folder name. The marker syncs
with the folder, so every machine reads the same rule from the folder itself
and there is nothing to configure per machine.

```bash
mkdir ~/notes/arlyn
echo 'tag = arlyn' > ~/notes/arlyn/.notoj-kajero
```

Only direct subdirectories count: a kajero inside a kajero is not one.

## Two ways notoj runs

**At the vault root** (no marker in `notes_dir`): notes are the root's `*.md`
plus each kajero's `*.md`. The tag decides where a note lives:

| Note | Action |
|---|---|
| outside every kajero, tagged for one | moved into it |
| inside a kajero, carrying its tag | stays |
| inside a kajero, tag absent, last committed version had it | moved out to the root: the tag was removed |
| inside a kajero, tag absent, no committed version had it | tagged: it is a new arrival (created on a machine that sees only the kajero, or dropped into the folder by hand) |
| tagged for two kajeroj | left where it is, with a status message |

"Last committed version" is found by the note's `id` in `HEAD` of the vault's
git history, so a note renamed in the same edit is still recognised.

**Inside a kajero** (marker in `notes_dir`): the folder is an ordinary vault
with one addition: new notes, imports and new arrivals without the tag get it.
A note whose tag is removed here is left alone; the vault root files it out
when it next scans, and Syncthing then removes it from this machine.

Moves keep the filename (a collision gets the usual ` (2)` suffix, never an
overwrite), skip notes open in another notoj's editor, and are reported on
the status bar as `moved into arlyn/` or `moved out of arlyn/`.

## Viewing one kajero

Membership is the tag, so the existing tag filter (`#arlyn` in search, or the
tags view) already shows exactly one kajero. There is no separate kajero
filter and no vault switching.

## What else changes

- Links: `[[wikilinks]]`, canonicalization, backlinks and Vim's `gf` resolve
  note names in every kajero as well as the root.
- Trash: a note trashed at the vault root goes to the root `.trash/`. A
  kajero's own `.trash/` (written when notoj runs inside it) is listed in the
  root's trash view too.
- Git: the vault repo tracks kajero folders as ordinary subfolders. A machine
  running notoj inside a kajero keeps its own repo there.
- Syncthing: when a kajero folder is its own Syncthing folder (it holds a
  `.stfolder`) and an enclosing folder is also synced, notoj prepends an
  ignore rule for the kajero to the enclosing folder's `.stignore`, so the two
  folders never overlap. Like the `.git` rule, this is written on every machine
  where both exist, since `.stignore` does not sync.
- The repo stays put: notoj opened on a kajero writes the `.git` rule into
  the kajero's `.stignore` before creating its repo, even if the folder is not
  shared yet, because Syncthing's first scan of a newly shared folder would
  otherwise send the repo to every peer. At the vault root, a kajero that is
  its own Syncthing folder gets the same rule, so a repo sent by another
  machine is never taken in. Both checks also run on every scan.
