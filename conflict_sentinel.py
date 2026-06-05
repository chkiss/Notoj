#!/usr/bin/env python3
"""Syncthing conflict sentinel — surface conflicts as a notoj note, with diffs.

notoj's own `c` resolver only sees `*.sync-conflict-*.md` inside the notes folder.
This sweeps EVERY Syncthing folder (read from the Syncthing config) for ANY
`*.sync-conflict-*` file and writes a single notoj note —
`⚠ Sync conflicts — <host>.md` in the notes dir — listing each conflict with a
unified diff (text) or a binary summary. When nothing conflicts, the note is
removed. Idempotent: rewrites only when the conflict set changes, so it won't
spam notoj's git history or Syncthing.

Run from cron (hourly). Host-named output so multiple machines never collide on
the report note itself.
"""
import os, re, socket, difflib, datetime, uuid
import xml.etree.ElementTree as ET

NOTES_DIR = os.environ.get("NOTOJ_NOTES_DIR") or os.path.expanduser(
    "~/Documents/dokumentoj/notes")
ST_CONFIG = os.path.expanduser("~/.local/state/syncthing/config.xml")
HOST = socket.gethostname().split(".")[0]
REPORT = os.path.join(NOTES_DIR, f"⚠ Sync conflicts — {HOST}.md")

CONFLICT_RE = re.compile(
    r'^(.+)\.sync-conflict-\d+-\d+-[A-Z0-9]+(\.[^.]+)?$')
SKIP_DIRS = {".git", ".stversions", ".stfolder"}
MAX_DIFF_LINES = 80


def synced_roots():
    """Folder paths from the Syncthing config (non-paused), ~ expanded."""
    roots = []
    try:
        root = ET.parse(ST_CONFIG).getroot()
    except Exception:
        return [NOTES_DIR]
    for f in root.findall("folder"):
        if f.get("paused") == "true":
            continue
        p = f.get("path", "")
        if p:
            roots.append(os.path.expanduser(p))
    return roots or [NOTES_DIR]


def find_all_conflicts():
    # os.walk (not glob ** ) so hidden dirs like .trash are traversed.
    seen, out = set(), []
    for root in synced_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                m = CONFLICT_RE.match(fn)
                if not m:
                    continue
                p = os.path.join(dirpath, fn)
                if p in seen:
                    continue
                seen.add(p)
                original = os.path.join(dirpath, m.group(1) + (m.group(2) or ""))
                out.append((p, original))
    return sorted(out)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def diff_block(conflict, original):
    if not original or not os.path.exists(original):
        return "_Original is gone — this conflict copy is the only remaining version._"
    a, b = read_text(original), read_text(conflict)
    if a is None or b is None:
        so = os.path.getsize(original) if os.path.exists(original) else 0
        sc = os.path.getsize(conflict)
        return f"_Binary file — current {so:,} B vs conflict {sc:,} B. Compare manually._"
    ud = list(difflib.unified_diff(a, b, "current", "conflict", lineterm=""))
    if not ud:
        return "_Identical to current — safe to delete the conflict copy._"
    if len(ud) > MAX_DIFF_LINES:
        ud = ud[:MAX_DIFF_LINES] + [f"... ({len(ud) - MAX_DIFF_LINES} more diff lines)"]
    return "```diff\n" + "\n".join(ud) + "\n```"


def build_body(conflicts):
    lines = [f"⚠ Sync conflicts — {HOST}", "",
             "#syncconflict",
             "",
             f"{len(conflicts)} Syncthing conflict file(s) found across synced folders. "
             "notoj's own `c` resolver only covers `.md` files in the notes dir — "
             "this note covers everything else too.", ""]
    home = os.path.expanduser("~")
    for conflict, original in conflicts:
        rel = conflict.replace(home, "~")
        lines.append(f"## {os.path.basename(original or conflict)}")
        lines.append(f"`{rel}`")
        lines.append("")
        lines.append(diff_block(conflict, original))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def existing_signature(path):
    """Body of an existing report minus its frontmatter, for change detection."""
    try:
        with open(path, encoding="utf-8") as fh:
            t = fh.read()
    except OSError:
        return None
    if t.startswith("---\n"):
        end = t.find("\n---\n", 4)
        if end != -1:
            return t[end + 5:].lstrip("\n")
    return t


def write_report(body):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nid = str(uuid.uuid1())
    created = now
    if os.path.exists(REPORT):  # preserve id/created if updating
        old = open(REPORT, encoding="utf-8").read()
        mid = re.search(r'^id:\s*(\S+)', old, re.M)
        mcr = re.search(r'^created:\s*(\S+)', old, re.M)
        if mid:
            nid = mid.group(1)
        if mcr:
            created = mcr.group(1)
    fm = (f"---\nid: {nid}\ncreated: {created}\nmodified: {now}\n"
          f"title: ⚠ Sync conflicts — {HOST}\ntags:\n  - syncconflict\n---\n\n")
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(fm + body)


def main():
    conflicts = find_all_conflicts()
    if not conflicts:
        if os.path.exists(REPORT):
            os.remove(REPORT)
            print("no conflicts — removed stale report note")
        else:
            print("no conflicts")
        return
    body = build_body(conflicts)
    if existing_signature(REPORT) == body:
        print(f"{len(conflicts)} conflict(s) — report already current")
        return
    write_report(body)
    print(f"{len(conflicts)} conflict(s) — wrote {REPORT}")


if __name__ == "__main__":
    main()
