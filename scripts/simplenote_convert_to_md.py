#!/usr/bin/env python3
"""
Convert Simplenote JSON notes to Markdown files with YAML frontmatter.

Usage:
    python3 convert_to_md.py <input_dir> [output_dir]

If output_dir is omitted, files are written to <input_dir>/converted/.

Deleted notes (deleted:true in JSON, or sourced from .trash/) are written
to .trash/ inside output_dir regardless of where the source file lived.
The deleted flag is not carried into the YAML — filesystem location is the
sole signal.

Format
------
Each .md file begins with a YAML block:

    ---
    id: <hex key>
    title: "First line of content"
    created: 2021-06-30T15:05:06Z
    modified: 2021-08-04T16:55:20Z
    version: 28
    tags:
      - ibm
    ---

    <content body>

Fields included only when non-empty: title, tags, share_url, publish_url,
system_tags.  syncdate and savedate are internal sync state and are dropped.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TITLE_MAX = 72  # longest real title in corpus is 70 chars; one URL outlier at 1608


def ts_to_iso(ts) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(title: str) -> str:
    """Return a filesystem-safe filename stem derived from a note title."""
    # Replace chars that are unsafe or ambiguous on Linux/macOS
    safe = re.sub(r'[/\\:\0]', '-', title)
    # Normalise whitespace
    safe = re.sub(r'\s+', ' ', safe).strip()
    # Strip leading dots so we don't create hidden files
    safe = safe.lstrip('.')
    return safe or 'untitled'


def unique_stem(dst_dir: Path, stem: str, used: set) -> Path:
    """Return a Path that doesn't collide with already-used output paths."""
    candidate = dst_dir / (stem + '.md')
    if candidate not in used:
        used.add(candidate)
        return candidate
    n = 2
    while True:
        candidate = dst_dir / (f'{stem} ({n}).md')
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1


def yaml_scalar(value: str) -> str:
    """Return value quoted for use as a YAML scalar if it contains special chars."""
    if not value:
        return '""'
    # Characters that can confuse a YAML parser in flow context
    need_quote = any(c in value for c in ':#{}[]|>&*!,')
    need_quote = need_quote or value[0] in ('"', "'", '%', '@', '`')
    need_quote = need_quote or value.lower() in ('true', 'false', 'yes', 'no', 'null', '~')
    if need_quote:
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return value


def extract_hashtags(content: str) -> list[str]:
    """Return unique hashtags found in content, preserving first-occurrence order.

    Matches #word, #word-with-hyphens, #word_with_underscores.
    Requires the character before # to not be a word character or /
    to avoid false positives from URLs and compound words.
    """
    raw = re.findall(r'(?<![/\w])#([a-zA-Z][a-zA-Z0-9_-]*)', content)
    return list(dict.fromkeys(raw))


def build_frontmatter(data: dict) -> str:
    key = data.get("key") or data.get("localkey") or ""
    content = data.get("content") or ""
    tags = list(data.get("tags") or [])
    for t in extract_hashtags(content):
        if t not in tags:
            tags.append(t)
    system_tags = data.get("systemTags") or []
    share_url = data.get("shareURL") or ""
    publish_url = data.get("publishURL") or ""
    version = data.get("version")
    created = ts_to_iso(data.get("creationDate"))
    modified = ts_to_iso(data.get("modificationDate"))

    # Title: first non-empty line of content
    title = ""
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped:
            title = stripped[:TITLE_MAX]
            break

    lines = ["---"]
    lines.append(f"id: {key}")
    if title:
        lines.append(f"title: {yaml_scalar(title)}")
    if created:
        lines.append(f"created: {created}")
    if modified:
        lines.append(f"modified: {modified}")
    if version is not None:
        lines.append(f"version: {version}")
    if tags:
        lines.append("tags:")
        for t in tags:
            lines.append(f"  - {yaml_scalar(t)}")
    else:
        lines.append("tags: []")
    if share_url:
        lines.append(f"share_url: {yaml_scalar(share_url)}")
    if publish_url:
        lines.append(f"publish_url: {yaml_scalar(publish_url)}")
    if system_tags:
        lines.append("system_tags:")
        for t in system_tags:
            lines.append(f"  - {yaml_scalar(t)}")
    lines.append("---")

    return "\n".join(lines)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_deleted(data: dict, in_trash_dir: bool) -> bool:
    return in_trash_dir or bool(data.get("deleted", False))


def note_stem(data: dict, fallback: str) -> str:
    """Derive a filename stem from the first line of content, or fall back to the note key."""
    content = data.get("content") or ""
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped:
            return slugify(stripped[:TITLE_MAX])
    return fallback


def write_md(output_path: Path, data: dict) -> None:
    frontmatter = build_frontmatter(data)
    content = data.get("content") or ""

    if content:
        text = frontmatter + "\n\n" + content
        if not text.endswith("\n"):
            text += "\n"
    else:
        text = frontmatter + "\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)


def convert_dir(input_dir: Path, output_dir: Path) -> None:
    converted = 0
    errors = 0
    used_paths: set[Path] = set()

    # Collect all JSON files from the main dir and .trash subdir
    sources: list[tuple[Path, bool]] = []  # (path, in_trash)
    for json_file in sorted(input_dir.glob("*.json")):
        sources.append((json_file, False))
    trash_in = input_dir / ".trash"
    if trash_in.is_dir():
        for json_file in sorted(trash_in.glob("*.json")):
            sources.append((json_file, True))

    for json_file, in_trash in sources:
        try:
            data = load_json(json_file)
            dst_dir = output_dir / ".trash" if is_deleted(data, in_trash) else output_dir
            fallback = data.get("key") or data.get("localkey") or json_file.stem
            stem = note_stem(data, fallback)
            out_path = unique_stem(dst_dir, stem, used_paths)
            write_md(out_path, data)
            rel_in = json_file.relative_to(input_dir)
            rel_out = out_path.relative_to(output_dir)
            print(f"  {rel_in}  →  {rel_out}")
            converted += 1
        except Exception as exc:
            print(f"  ERROR: {json_file.name}: {exc}")
            errors += 1

    print(f"\n{converted} note(s) converted to {output_dir}")
    if errors:
        print(f"{errors} error(s)")


def main():
    if len(sys.argv) < 2:
        print("Usage: convert_to_md.py <input_dir> [output_dir]")
        sys.exit(1)

    input_dir = Path(sys.argv[1]).expanduser().resolve()
    if not input_dir.is_dir():
        print(f"Error: {input_dir} is not a directory")
        sys.exit(1)

    output_dir = (
        Path(sys.argv[2]).expanduser().resolve()
        if len(sys.argv) > 2
        else input_dir / "converted"
    )

    convert_dir(input_dir, output_dir)


if __name__ == "__main__":
    main()
