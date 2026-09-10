# Performance

What the preview costs to draw, how it got there, and how to change it without
breaking the screen. Numbers are measured against a real vault — 1,260 notes,
68k lines, whose biggest note is 91k characters over 552 lines, 344 of them
realigned table rows.

## How to verify a change to the renderer

Read this before touching `wrap_to_width`, `_md_runs`, `_hit_runs`,
`row_md_states` or `draw_markdown_line`.

Paint every line of the vault through the old renderer and the new one —
unwrapped at several pane widths, wrapped at several more, each with and
without search hits live — and require the same screen out of both.

Two details make it work:

* **Compare the cell map, not the curses calls.** Flatten each draw into
  `column -> (glyphs, attribute)`. A legitimate change to how the drawing is
  batched alters the call sequence without altering the screen; comparing
  calls flags those as failures and buries the real ones. The runs rework
  changed 129,960 draws this way while changing nothing a reader would see.
* **Include token sets that probe the seams**: a token made of `**` markers
  (it can only hit if the markers were *not* dropped), a single character that
  hits everywhere and splits every run, tokens landing inside a `# heading`
  and inside a `` `code span` ``.

This gate caught four real defects during the 2026-09-09 pass. The unit tests
caught none of them — they pin the contracts, but a renderer has too many
inputs for any hand-written set of cases to cover.

The same shape of check applies below the renderer: `disp_width`,
`clip_to_width`, `char_width` over every distinct character in the vault, and
`_reshape` over every line, must all stay byte-identical across a change that
is only meant to make them faster.

## Where the time goes now

A preview frame, 43 rows on screen:

| note | frame |
|---|---|
| median note | 0.06 ms |
| biggest note | 0.44 ms |
| biggest note, query live | 0.52 ms |

Landing on a note for the first time wraps it (~60 ms for the biggest note,
0.08 ms for a median one) and then caches the rows; revisits are free until
the pane width changes or the LRU evicts it. With a query live, arriving on a
note also builds its match list — 14 ms on the biggest note, under 0.1 ms on a
normal one.

## What made it fast (2026-09-09)

Each of these was picked from a profile, not a guess, and the order matters —
several only became visible once the one above it was gone.

* **`char_width` is memoized.** A pure function of one character and the
  busiest function in the program: wrapping the biggest note called it 2.5
  million times, 85% of that note's wrap cost.
* **`wrap_to_width` inlines `disp_width`'s ASCII fast path** at the three
  points it measures. The call was the cost — an ASCII word's width is its
  length — and a realigned table row is mostly padding, so `split(" ")` hands
  the loop one empty word per padding column.
* **`_md_line_arrays` is memoized.** Scrolling asks the same question over and
  over: a `j` moves the window one row, so the other forty rows belong to
  source lines parsed for the previous frame.
* **`_md_logical`** gives the match list the marker-stripped text without
  building a tuple per character — 1.7M of them per rebuild — and returns the
  row untouched when there is nothing to strip.
* **`draw_markdown_line` paints runs, not characters.** Emitting a
  `(logical, drawn, attr)` tuple per character and grouping them afterwards
  was 60% of a frame, with another 15% building the tuples. `_md_runs` groups
  by `(attr, strike)` directly; `_hit_runs` re-cuts those runs at search-hit
  boundaries.
* **`_reshape` uses a compiled Arabic-block search.** It walked every
  character of any non-ASCII row with `ord()`, so one em dash defeated its
  ASCII fast path. Invisible until the runs landed, and then the largest
  single win of the pass: 1.52 ms -> 0.44 ms on the worst frame.

Against the state before the pass: a preview frame 3.6-7.5x faster, the match
list 3.7x, a cold wrap 1.8-2.4x.

## Known remaining costs

Neither is worth fixing at today's vault size. Both are recorded so the next
profile does not rediscover them.

### The alert-gutter scan is O(all notes) per frame

`draw()` computes `gutter` with `any(n.get("title_conflict") for n in notes)`
over the whole filtered list on every redraw. It costs 0.088 ms/frame at 1,260
notes — invisible — but it is the only remaining per-frame work proportional
to vault size, so it would be ~0.7 ms/frame at 10k notes.

Fixing it means caching the flag against the filtered list's identity and
invalidating it wherever a note's `title_conflict` is recomputed. That
invalidation surface is the reason to leave it alone for now: a stale `False`
silently drops the alert marker for a real title conflict, and nothing on
screen would say so.

### The match list is O(whole note) per keypress

With a query live, every `j`/`k` rebuilds `preview_match_list` for the newly
selected note, because the status line shows a total hit count and `n`/`N`
needs every hit. Only a note several times larger than anything in the vault
would justify an incremental or lazy match list.
