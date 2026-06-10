#!/usr/bin/env python3
"""Refresh the `## Ratings` summary tables in the media notes (Books / Movies /
TV shows).

The note is the single source of truth: existing ratings are read back from the
table, so they persist. Any title appearing in the `##` sections but not yet in
the table is treated as NEW:
  - Movies / TV shows: looked up via the OMDb API (set OMDB_API_KEY; free key at
    https://www.omdbapi.com/apikey.aspx). Movies show Rotten Tomatoes %% (IMDb
    fallback); TV shows show IMDb /10.
  - Books: inserted as `?` for you to fill (no free Goodreads API exists).

Idempotent: the table is rewritten between <!-- ratings:start --> / <!-- end -->
markers, so re-running is safe.

Bullet comments: text after a space-then-# is ignored, e.g.
  - The Dark Knight   # rewatched, great
A line is skipped entirely if its comment is an ignore directive:
  - Ramin Bahrani (director)   # ignore   (also: # skip / # hide / # x)
(Use '# ' with a space so notoj doesn't sync the comment as a hashtag.)

Usage:
  OMDB_API_KEY=xxxx python3 update_ratings.py            # all three notes
  python3 update_ratings.py --dry-run                    # show changes only
  python3 update_ratings.py "/path/to/Movies.md"         # one note
"""
import os, re, sys, json, unicodedata, urllib.request, urllib.parse

NOTES_DIR = os.environ.get("NOTOJ_NOTES_DIR") or os.path.expanduser(
    "~/Documents/dokumentoj/notes")


def _load_key():
    k = os.environ.get("OMDB_API_KEY", "")
    if k:
        return k
    try:
        with open(os.path.expanduser("~/.config/notoj/omdb_key")) as f:
            return f.read().strip()
    except OSError:
        return ""


OMDB_KEY = _load_key()

# note filename -> (column header, kind)
CONFIG = {
    "Books.md":    ("Goodreads", "book"),
    "Movies.md":   ("Rating",    "movie"),
    "TV shows.md": ("IMDb",      "tv"),
}
START, END = "<!-- ratings:start -->", "<!-- ratings:end -->"


# ---- parsing -------------------------------------------------------------

def split_frontmatter(text):
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[:end + 5], text[end + 5:]
    return "", text


def find_block(body):
    """Return (start_idx, end_idx) of the ratings block in body, or None.
    Prefers explicit markers; falls back to a `## Ratings` heading up to the
    next `## ` heading."""
    if START in body and END in body:
        s = body.index(START)
        e = body.index(END) + len(END)
        return s, e
    m = re.search(r'^## Ratings\b.*$', body, re.M)
    if not m:
        return None
    s = m.start()
    nxt = re.search(r'^## (?!Ratings)', body[m.end():], re.M)
    e = m.end() + nxt.start() if nxt else len(body)
    return s, e


def parse_existing(block):
    """From an existing ratings block, return ({title: display}, [no_rating])."""
    rated, none = {}, []
    for line in block.splitlines():
        # Cells may contain literal pipes escaped as \| (render_block writes
        # them that way), so a cell is a run of "anything but |, or \|".
        m = re.match(r'\|\s*((?:\\\||[^|])+?)\s*\|\s*((?:\\\||[^|])+?)\s*\|', line)
        if m and m.group(1).lower() not in ("book", "film", "title", "movie", "show"):
            if set(m.group(1)) <= set("-: "):  # the |---|---| separator
                continue
            rated[m.group(1).replace("\\|", "|")] = m.group(2).replace("\\|", "|")
        nm = re.search(r'No rating found:\s*(.+?)\.?\*?\s*$', line)
        if nm:
            none = [t.strip() for t in nm.group(1).split(",") if t.strip()]
    return rated, none


IGNORE_WORDS = ("ignore", "skip", "hide", "no", "x")


def parse_bullet(text):
    """Split a bullet into (title, comment). A comment starts at the first
    whitespace-then-# and is dropped from the title. Using '# ' (hash-space)
    also keeps notoj from syncing it as a tag."""
    m = re.search(r'\s#', text)
    if not m:
        return text.strip(), ""
    title = text[:m.start()].strip()
    comment = text[m.start():].strip().lstrip("#").strip().lower()
    return title, comment


def section_titles(body, block_span):
    """Rateable titles from `- ` bullets under `## ` sections. Excludes the
    ratings block and any line whose comment is an ignore directive
    (`# ignore` / `# skip` / `# x` …); strips other trailing `# comments`."""
    if block_span:
        body = body[:block_span[0]] + body[block_span[1]:]
    out = []
    for line in body.splitlines():
        m = re.match(r'\s*-\s+(.*\S)', line)
        if not m:
            continue
        title, comment = parse_bullet(m.group(1).strip())
        if not title or any(comment.startswith(w) for w in IGNORE_WORDS):
            continue
        out.append(title)
    return out


# ---- grouped-bullet expansion --------------------------------------------

def split_groups(body, block_span):
    """Rewrite `;`-grouped wishlist bullets into one bullet per film.

    A bullet's `;` is treated as a grouping separator unless the whole bullet is
    itself a valid film on OMDb (rare — almost no title contains a semicolon).
    A leading `Label: ` on the first segment (e.g. "Bollywood from Neel: Lagaan;
    …") is dropped so the film looks up cleanly. The ratings block, commented
    bullets and link lines are left untouched."""
    if block_span:
        s, e = block_span
        chunks = [(body[:s], True), (body[s:e], False), (body[e:], True)]
    else:
        chunks = [(body, True)]
    out = []
    for text, expand in chunks:
        if not expand:
            out.append(text)
            continue
        lines = []
        for line in text.split("\n"):
            m = re.match(r'(\s*)-\s+(.*\S)\s*$', line)
            raw = m.group(2) if m else ""
            if (not m or ";" not in raw or re.search(r'\s#', raw)
                    or "http" in raw.lower()):
                lines.append(line)
                continue
            if omdb_lookup(raw, "movie"):          # whole bullet is a real title
                lines.append(line)
                continue
            indent = m.group(1)
            segs = [s.strip() for s in raw.split(";") if s.strip()]
            if ":" in segs[0]:                     # drop a leading "Label:"
                segs[0] = segs[0].split(":", 1)[1].strip()
            lines += [f"{indent}- {s}" for s in segs if s]
        out.append("\n".join(lines))
    return "".join(out)


# ---- matching ------------------------------------------------------------

STOP = {"the", "and", "for", "with", "from", "her", "his", "into", "una", "los",
        "las", "del", "que", "vol", "part"}


def words(s):
    # Drop parenthetical/bracketed qualifiers (year, language, remake note) so a
    # title and its variant reduce to the same core: "Oldboy (2003)" and
    # "Oldboy (Korean)" both -> {oldboy}, letting the subset check merge them.
    s = re.sub(r'[\(\[].*?[\)\]]', ' ', s)
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return set(w for w in re.findall(r'[a-z0-9]+', s)
               if len(w) > 2 and w not in STOP)


def already_known(bullet, known_titles):
    """True if `bullet` plausibly refers to an already-rated title — by direct
    substring or strong word overlap (handles 'Clark, Civilisation' vs
    'Civilisation (Kenneth Clark)')."""
    bl = bullet.lower()
    bw = words(bullet)
    if not bw:
        return True
    for t in known_titles:
        if not t:
            continue
        if t.lower() in bl:
            return True
        tw = words(t)
        if not tw:
            continue
        if tw <= bw or bw <= tw:
            return True
        inter = bw & tw
        # Require >=2 shared words for the fuzzy branch: a single common word
        # ("last", "beauty", "american") is too weak and wrongly suppressed
        # distinct films (e.g. "Last Night" vs "The Last Waltz"). Genuine
        # one-word dupes are still caught by the substring / subset checks above.
        if len(inter) >= 2 and len(inter) / min(len(bw), len(tw)) >= 0.5:
            return True
    return False


# ---- ratings -------------------------------------------------------------

def sort_key(display):
    if display in ("?", "—", ""):
        return -1.0
    m = re.search(r'[\d.]+', display)
    if not m:
        return -1.0
    v = float(m.group())
    if "%" in display:
        return v
    if "imdb" in display.lower():
        return v * 10          # put IMDb/10 on the 0-100 movie scale
    return v


def omdb_lookup(title, kind):
    if not OMDB_KEY:
        return None
    typ = "series" if kind == "tv" else "movie"
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(
        {"t": title, "type": typ, "apikey": OMDB_KEY})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
    except Exception:
        return None
    if d.get("Response") != "True":
        return None
    if kind == "tv":
        rt = d.get("imdbRating", "N/A")
        return rt if rt not in ("N/A", "") else None
    # movie: prefer Rotten Tomatoes, fall back to IMDb /10
    for r in d.get("Ratings", []):
        if r.get("Source") == "Rotten Tomatoes":
            return r["Value"].replace(".0", "")            # e.g. "92%"
    imdb = d.get("imdbRating", "N/A")
    return f"{imdb} (IMDb)" if imdb not in ("N/A", "") else None


# ---- render --------------------------------------------------------------

LEGEND = {
    "book":  "*Goodreads average /5. † = estimate; ? = needs a rating.*",
    "movie": "*Rotten Tomatoes %, except (IMDb)/10 where a film has no RT page. ? = needs a rating.*",
    "tv":    "*IMDb /10. † = estimate; ? = needs a rating.*",
}


def render_block(col, kind, rated, none):
    esc = lambda s: s.replace("|", "\\|")   # literal pipes would split the table cells
    rows = sorted(rated.items(), key=lambda kv: (-sort_key(kv[1]), kv[0].lower()))
    out = [START, "## Ratings", "", LEGEND[kind], "", f"| {'Book' if kind=='book' else 'Film' if kind=='movie' else 'Title'} | {col} |", "|---|---|"]
    out += [f"| {esc(t)} | {esc(d)} |" for t, d in rows]
    if none:
        out += ["", "*No rating found: " + ", ".join(none) + ".*"]
    out += [END]
    return "\n".join(out)


# ---- main ----------------------------------------------------------------

def process(path, dry, no_new=False):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    fm, body = split_frontmatter(text)
    if not no_new:
        body = split_groups(body, find_block(body))
    span = find_block(body)
    rated, none = parse_existing(body[span[0]:span[1]]) if span else ({}, [])

    known = list(rated) + none
    new = []
    if not no_new:
        for title in section_titles(body, span):
            if "http" in title.lower():   # link lines (grouping handled upstream)
                continue
            if already_known(title, known):
                continue
            if title not in new:
                new.append(title)

    kind = CONFIG.get(os.path.basename(path), ("Rating", "movie"))[1]
    added = []
    for title in new:
        disp = omdb_lookup(title, kind) if kind in ("movie", "tv") else None
        rated[title] = disp or "?"
        added.append(f"{title} → {rated[title]}")

    col = CONFIG.get(os.path.basename(path), ("Rating", "movie"))[0]
    block = render_block(col, kind, rated, none)

    if span:
        new_body = body[:span[0]].rstrip("\n") + "\n\n" + block + "\n" + body[span[1]:].lstrip("\n")
    else:  # no table yet: insert after the title line
        lines = body.split("\n", 2)
        new_body = body  # leave alone if structure unexpected
        if len(lines) >= 1:
            head = lines[0]
            rest = body[len(head):].lstrip("\n")
            new_body = head + "\n\n" + block + "\n\n" + rest

    name = os.path.basename(path)
    if added:
        print(f"{name}: {len(added)} new -> " + "; ".join(added))
    else:
        print(f"{name}: no new titles")
    if not dry and new_body != text[len(fm):]:
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm + new_body)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    no_new = "--no-new" in sys.argv      # migrate/sort only; don't add titles
    paths = args or [os.path.join(NOTES_DIR, n) for n in CONFIG]
    if not OMDB_KEY and not no_new:
        print("(no OMDb key — new films/shows will get '?' too)\n")
    for p in paths:
        if os.path.exists(p):
            process(p, dry, no_new)
        else:
            print(f"skip (not found): {p}")


if __name__ == "__main__":
    main()
