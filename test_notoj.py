"""Tests for notoj — pure-logic and filesystem functions."""

import importlib.machinery
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Import notoj as a module without running __main__
# ---------------------------------------------------------------------------

# Stub curses before loading so the module-level import doesn't fail in
# headless environments.
curses_stub = types.ModuleType("curses")
curses_stub.error = Exception
curses_stub.KEY_DOWN = 258
curses_stub.KEY_UP = 259
curses_stub.KEY_NPAGE = 338
curses_stub.KEY_PPAGE = 339
curses_stub.KEY_BACKSPACE = 263
curses_stub.KEY_LEFT = 260
curses_stub.KEY_RIGHT = 261
curses_stub.KEY_HOME = 262
curses_stub.KEY_END = 360
# Video-attribute constants referenced at module load (and inside draw code).
for _i, _attr in enumerate(("A_NORMAL", "A_BOLD", "A_UNDERLINE", "A_REVERSE",
                            "A_DIM", "A_ITALIC")):
    setattr(curses_stub, _attr, 1 << _i)
curses_stub.color_pair = lambda n: n << 8   # distinct int per pair, for | attrs
sys.modules.setdefault("curses", curses_stub)

_here = os.path.dirname(os.path.abspath(__file__))
_notoj_path = os.path.join(_here, "notoj")
loader = importlib.machinery.SourceFileLoader("notoj", _notoj_path)
notoj = types.ModuleType("notoj")
notoj.__file__ = _notoj_path
loader.exec_module(notoj)

# Helpers to make a minimal note dict.
def make_note(title="", content="", tags=None, modified=0.0, created=0.0, path="/tmp/test.md"):
    return {
        "path": path,
        "title": title,
        "content": content,
        "tags": tags or [],
        "system_tags": [],
        "modificationDate": modified,
        "creationDate": created,
        "id": "test-id",
        "version": "1",
    }


# ---------------------------------------------------------------------------
# yaml_scalar
# ---------------------------------------------------------------------------

class TestYamlScalar(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(notoj.yaml_scalar(""), '""')

    def test_plain_string(self):
        self.assertEqual(notoj.yaml_scalar("hello"), "hello")

    def test_colon_triggers_quote(self):
        result = notoj.yaml_scalar("http://example.com")
        self.assertTrue(result.startswith('"') and result.endswith('"'))

    def test_hash_triggers_quote(self):
        result = notoj.yaml_scalar("foo#bar")
        self.assertTrue(result.startswith('"') and result.endswith('"'))

    def test_yaml_booleans_quoted(self):
        for kw in ("true", "false", "yes", "no", "null", "~"):
            with self.subTest(kw=kw):
                result = notoj.yaml_scalar(kw)
                self.assertTrue(result.startswith('"'), f"{kw!r} not quoted")

    def test_yaml_booleans_case_insensitive(self):
        for kw in ("True", "FALSE", "YES", "Null"):
            with self.subTest(kw=kw):
                result = notoj.yaml_scalar(kw)
                self.assertTrue(result.startswith('"'), f"{kw!r} not quoted")

    def test_leading_single_quote(self):
        result = notoj.yaml_scalar("'foo")
        self.assertTrue(result.startswith('"'))

    def test_leading_percent(self):
        result = notoj.yaml_scalar("%TAG")
        self.assertTrue(result.startswith('"'))

    def test_backslash_and_quote_escaped(self):
        # Colon triggers quoting; embedded quote must be escaped.
        result = notoj.yaml_scalar('note: say "hi"')
        self.assertTrue(result.startswith('"') and result.endswith('"'))
        self.assertIn('\\"hi\\"', result)

    def test_backslash_escaped(self):
        # Colon triggers quoting; embedded backslash must be escaped.
        result = notoj.yaml_scalar("path: a\\b")
        self.assertTrue(result.startswith('"') and result.endswith('"'))
        self.assertIn("\\\\", result)

    def test_normal_no_quotes(self):
        for s in ("hello world", "dentist", "my note", "A little bit on myself"):
            with self.subTest(s=s):
                result = notoj.yaml_scalar(s)
                self.assertFalse(result.startswith('"'), f"{s!r} should not be quoted")


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify(unittest.TestCase):
    def test_slash_becomes_dash(self):
        # "gifts/presents" → "gifts-presents"
        self.assertEqual(notoj.slugify("gifts/presents"), "gifts-presents")

    def test_backslash_becomes_dash(self):
        self.assertEqual(notoj.slugify("a\\b"), "a-b")

    def test_colon_becomes_dash(self):
        self.assertEqual(notoj.slugify("a:b"), "a-b")

    def test_null_byte_becomes_dash(self):
        self.assertEqual(notoj.slugify("a\x00b"), "a-b")

    def test_leading_dot_stripped(self):
        self.assertEqual(notoj.slugify(".hidden"), "hidden")

    def test_trailing_dash_stripped(self):
        # A title that ends with a slash becomes a trailing dash which gets stripped.
        result = notoj.slugify("note/")
        self.assertFalse(result.endswith("-"), f"Trailing dash not stripped: {result!r}")

    def test_multiple_spaces_collapsed(self):
        self.assertEqual(notoj.slugify("a  b   c"), "a b c")

    def test_empty_returns_untitled(self):
        self.assertEqual(notoj.slugify(""), "untitled")

    def test_only_slashes_returns_untitled(self):
        self.assertEqual(notoj.slugify("///"), "untitled")

    def test_url_title(self):
        # Long URL-like title should be preserved (no stripping beyond /, \, :, \0)
        result = notoj.slugify("https://example.com/path")
        self.assertIn("example.com", result)

    def test_arabic_title_preserved(self):
        result = notoj.slugify("سكرابل")
        self.assertEqual(result, "سكرابل")

    def test_comma_and_hyphen_preserved(self):
        # "10-1, 4-10" → "10-1, 4-10" (no stripping of commas, hyphens, spaces)
        self.assertEqual(notoj.slugify("10-1, 4-10"), "10-1, 4-10")

    def test_question_mark_becomes_dash(self):
        # "?" is illegal on Android/FAT storage; a trailing one is stripped.
        self.assertEqual(notoj.slugify("Why tech?"), "Why tech")
        self.assertEqual(notoj.slugify("a?b"), "a-b")

    def test_double_quote_becomes_dash(self):
        # '"' is illegal on Android/Windows storage.
        self.assertEqual(notoj.slugify('say "hi" there'), "say -hi- there")

    def test_windows_android_illegal_chars_become_dash(self):
        # < > | * are all rejected by Android/FAT filesystems.
        for ch in "<>|*":
            self.assertEqual(notoj.slugify(f"a{ch}b"), "a-b",
                             f"char {ch!r} not sanitized")

    def test_control_char_becomes_dash(self):
        # Tabs/newlines collapse via \s; other control chars must still go.
        self.assertEqual(notoj.slugify("a\x07b"), "a-b")

    def test_trailing_dot_stripped(self):
        # Trailing dots are illegal on Windows and stripped by Android.
        result = notoj.slugify("note.")
        self.assertFalse(result.endswith("."), f"Trailing dot not stripped: {result!r}")
        self.assertEqual(result, "note")

    def test_only_illegal_chars_returns_untitled(self):
        self.assertEqual(notoj.slugify('???'), "untitled")


# ---------------------------------------------------------------------------
# derive_title
# ---------------------------------------------------------------------------

class TestDeriveTitle(unittest.TestCase):
    def test_plain_first_line(self):
        self.assertEqual(notoj.derive_title("Hello world\nbody"), "Hello world")

    def test_strips_h1_marker(self):
        self.assertEqual(notoj.derive_title("# Hello world\n"), "Hello world")

    def test_strips_deeper_heading(self):
        self.assertEqual(notoj.derive_title("### Sub heading"), "Sub heading")

    def test_skips_leading_blank_lines(self):
        self.assertEqual(notoj.derive_title("\n\n# Title\n"), "Title")

    def test_hash_without_space_kept(self):
        # Not an ATX heading (no space) — leave it alone.
        self.assertEqual(notoj.derive_title("#hashtag"), "#hashtag")

    def test_empty_body(self):
        self.assertEqual(notoj.derive_title(""), "")

    def test_capped_at_title_max(self):
        long = "# " + "x" * 200
        self.assertEqual(len(notoj.derive_title(long)), notoj.TITLE_MAX)


# ---------------------------------------------------------------------------
# iso_to_ts
# ---------------------------------------------------------------------------

class TestIsoToTs(unittest.TestCase):
    def test_valid_iso(self):
        ts = notoj.iso_to_ts("2013-10-08T13:08:43Z")
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        self.assertEqual(dt.year, 2013)
        self.assertEqual(dt.month, 10)
        self.assertEqual(dt.day, 8)

    def test_empty_string(self):
        self.assertEqual(notoj.iso_to_ts(""), 0.0)

    def test_none(self):
        self.assertEqual(notoj.iso_to_ts(None), 0.0)

    def test_invalid_format(self):
        self.assertEqual(notoj.iso_to_ts("not-a-date"), 0.0)

    def test_partial_iso(self):
        self.assertEqual(notoj.iso_to_ts("2013-10-08"), 0.0)


# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------

class TestParseFrontmatter(unittest.TestCase):
    def _parse(self, text):
        return notoj.parse_frontmatter(text)

    def test_simple_key_value(self):
        fm = "id: abc123\ncreated: 2013-10-08T13:08:43Z\n"
        result = self._parse(fm)
        self.assertEqual(result["id"], "abc123")
        self.assertEqual(result["created"], "2013-10-08T13:08:43Z")

    def test_empty_list_bracket(self):
        result = self._parse("tags: []\n")
        self.assertEqual(result["tags"], [])

    def test_empty_list_block(self):
        result = self._parse("tags:\n")
        self.assertEqual(result["tags"], [])

    def test_list_with_items(self):
        fm = "tags:\n  - foo\n  - bar\n"
        result = self._parse(fm)
        self.assertEqual(result["tags"], ["foo", "bar"])

    def test_inline_flow_list_single(self):
        result = self._parse("tags: [travel]\n")
        self.assertEqual(result["tags"], ["travel"])

    def test_inline_flow_list_multiple(self):
        result = self._parse("tags: [travel, work, urgent]\n")
        self.assertEqual(result["tags"], ["travel", "work", "urgent"])

    def test_inline_flow_list_extra_spaces(self):
        result = self._parse("tags: [ a ,  b ]\n")
        self.assertEqual(result["tags"], ["a", "b"])

    def test_inline_flow_list_trailing_comma(self):
        result = self._parse("tags: [foo, ]\n")
        self.assertEqual(result["tags"], ["foo"])

    def test_inline_flow_list_quoted_comma(self):
        result = self._parse('tags: ["a, b", c]\n')
        self.assertEqual(result["tags"], ["a, b", "c"])

    def test_inline_flow_list_escaped_quote(self):
        # A backslash-escaped quote inside a double-quoted item must not
        # close the quote early and split the item at its comma.
        result = notoj.parse_frontmatter(
            'tags: [plain, "he said \\"hi\\", really", \'single\']')
        self.assertEqual(result["tags"],
                         ["plain", 'he said "hi", really', "single"])

    def test_inline_flow_list_empty(self):
        result = self._parse("tags: [ ]\n")
        self.assertEqual(result["tags"], [])

    def test_quoted_value(self):
        fm = 'title: "10-1, 4-10"\n'
        result = self._parse(fm)
        self.assertEqual(result["title"], "10-1, 4-10")

    def test_quoted_value_with_escaped_quote(self):
        fm = 'title: "say \\"hello\\""\n'
        result = self._parse(fm)
        self.assertEqual(result["title"], 'say "hello"')

    def test_quoted_value_with_escaped_backslash(self):
        fm = 'title: "a\\\\b"\n'
        result = self._parse(fm)
        self.assertEqual(result["title"], "a\\b")

    def test_line_without_colon_skipped(self):
        result = self._parse("justtext\nid: abc\n")
        self.assertNotIn("justtext", result)
        self.assertEqual(result["id"], "abc")

    def test_system_tags_list(self):
        fm = "system_tags:\n  - markdown\n"
        result = self._parse(fm)
        self.assertEqual(result["system_tags"], ["markdown"])

    def test_version_string(self):
        result = self._parse("version: 3\n")
        self.assertEqual(result["version"], "3")

    def test_uuid_style_id(self):
        result = self._parse("id: 07f37aab-cfd6-49ae-b85e-36f7d79419ed\n")
        self.assertEqual(result["id"], "07f37aab-cfd6-49ae-b85e-36f7d79419ed")

    def test_base64_style_id(self):
        result = self._parse("id: agtzaW1wbGUtbm90ZXINCxIETm90ZRia5L8GDA\n")
        self.assertEqual(result["id"], "agtzaW1wbGUtbm90ZXINCxIETm90ZRia5L8GDA")

    def test_title_with_colon_in_value(self):
        # When the raw value after "title:" still has a colon, only partition on first
        fm = "title: foo: bar\n"
        result = self._parse(fm)
        self.assertEqual(result["title"], "foo: bar")


# ---------------------------------------------------------------------------
# load_md
# ---------------------------------------------------------------------------

class TestLoadMd(unittest.TestCase):
    def _write(self, tmp_dir, name, content):
        path = os.path.join(tmp_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_valid_note(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "note.md", (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2026-05-10T07:17:33Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                "My note title\n"
                "\n"
                "Body text.\n"
            ))
            n = notoj.load_md(path)
            self.assertIsNotNone(n)
            self.assertEqual(n["title"], "My note title")
            self.assertEqual(n["id"], "abc")
            self.assertGreater(n["modificationDate"], 0)

    def test_no_frontmatter_delimiter(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "note.md", "Just plain text\n")
            self.assertIsNone(notoj.load_md(path))

    def test_unclosed_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "note.md", "---\nid: abc\n")
            self.assertIsNone(notoj.load_md(path))

    def test_loads_with_utf8_bom(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bom.md")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(
                    "---\n"
                    "id: abc\n"
                    "title: BOM note\n"
                    "modified: 2026-05-10T07:17:33Z\n"
                    "---\n"
                    "\n"
                    "BOM note\n"
                )
            n = notoj.load_md(path)
            self.assertIsNotNone(n)
            self.assertEqual(n["title"], "BOM note")
            self.assertEqual(n["id"], "abc")

    def test_loads_with_crlf_line_endings(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "crlf.md")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(
                    "---\r\n"
                    "id: abc\r\n"
                    "title: CRLF note\r\n"
                    "modified: 2026-05-10T07:17:33Z\r\n"
                    "---\r\n"
                    "\r\n"
                    "CRLF note\r\n"
                )
            n = notoj.load_md(path)
            self.assertIsNotNone(n)
            self.assertEqual(n["title"], "CRLF note")
            self.assertEqual(n["id"], "abc")

    def test_title_from_frontmatter_when_body_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "note.md", (
                "---\n"
                "id: abc\n"
                "title: Fallback Title\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
            ))
            n = notoj.load_md(path)
            self.assertIsNotNone(n)
            self.assertEqual(n["title"], "Fallback Title")

    def test_body_title_overrides_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "note.md", (
                "---\n"
                "id: abc\n"
                "title: Old Title\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                "New Title\n"
            ))
            n = notoj.load_md(path)
            self.assertEqual(n["title"], "New Title")

    def test_unicode_body(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "arabic.md", (
                "---\n"
                "id: abc\n"
                "title: سكرابل\n"
                "created: 2022-08-04T20:19:48Z\n"
                "modified: 2022-08-04T21:04:04Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                "سكرابل\n"
            ))
            n = notoj.load_md(path)
            self.assertIsNotNone(n)
            self.assertEqual(n["title"], "سكرابل")

    def test_tags_list_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "note.md", (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags:\n"
                "  - work\n"
                "  - urgent\n"
                "---\n"
                "\n"
                "Tagged note\n"
            ))
            n = notoj.load_md(path)
            self.assertEqual(n["tags"], ["work", "urgent"])

    def test_nonexistent_file(self):
        self.assertIsNone(notoj.load_md("/nonexistent/path.md"))

    def test_title_truncated_to_max(self):
        long_title = "A" * 100
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, "note.md", (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                + long_title + "\n"
            ))
            n = notoj.load_md(path)
            self.assertEqual(len(n["title"]), notoj.TITLE_MAX)


# ---------------------------------------------------------------------------
# fmt / ago
# ---------------------------------------------------------------------------

class TestFmt(unittest.TestCase):
    def test_none_returns_dash(self):
        self.assertEqual(notoj.fmt(None), "-")

    def test_zero_returns_dash(self):
        # 0 is falsy
        self.assertEqual(notoj.fmt(0), "-")

    def test_valid_timestamp(self):
        ts = datetime(2026, 5, 10, 7, 17, 33, tzinfo=timezone.utc).timestamp()
        result = notoj.fmt(ts)
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")

    def test_string_timestamp(self):
        # Use midday UTC so local-timezone conversion stays within the same year.
        ts = str(datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        result = notoj.fmt(ts)
        self.assertIn("2026", result)


class TestAgo(unittest.TestCase):
    def _ts(self, seconds_ago):
        return datetime.now().timestamp() - seconds_ago

    def test_none_returns_dash(self):
        self.assertEqual(notoj.ago(None), "-")

    def test_zero_returns_dash(self):
        self.assertEqual(notoj.ago(0), "-")

    def test_seconds(self):
        result = notoj.ago(self._ts(30))
        self.assertRegex(result, r"^\d+s$")

    def test_minutes(self):
        result = notoj.ago(self._ts(90))
        self.assertRegex(result, r"^\d+m$")

    def test_hours(self):
        result = notoj.ago(self._ts(7200))
        self.assertRegex(result, r"^\d+h$")

    def test_days(self):
        result = notoj.ago(self._ts(5 * 86400))
        self.assertRegex(result, r"^\d+d$")

    def test_months(self):
        # 100 days > 90-day threshold → months format ("mo", distinct from minutes' "m")
        result = notoj.ago(self._ts(100 * 86400))
        self.assertRegex(result, r"^\d+mo$")

    def test_years_exact(self):
        # 3 years = 36 months = 0 remainder → no trailing "m"
        result = notoj.ago(self._ts(365 * 86400 * 3))
        self.assertRegex(result, r"^\d+y$")

    def test_years_with_months(self):
        # 2.5 years → 2y6mo (30 months ÷ 12 = 2 rem 6)
        result = notoj.ago(self._ts(int(2.5 * 365 * 86400)))
        self.assertRegex(result, r"^\d+y\d+mo$")

    def test_boundary_90_days(self):
        # Just under 90 days → days; just over → months
        under = notoj.ago(self._ts(89 * 86400))
        over = notoj.ago(self._ts(91 * 86400))
        self.assertRegex(under, r"^\d+d$")
        self.assertRegex(over, r"^\d+mo$")

    def test_minutes_and_months_distinguishable(self):
        # 4 minutes and 4 months must not both render as "4m".
        self.assertEqual(notoj.ago(self._ts(4 * 60)), "4m")
        self.assertEqual(notoj.ago(self._ts(4 * 30 * 86400 + 3600)), "4mo")


# ---------------------------------------------------------------------------
# _edit_dist
# ---------------------------------------------------------------------------

class TestEditDist(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(notoj.edit_dist("hello", "hello") if hasattr(notoj, "edit_dist") else notoj._edit_dist("hello", "hello"), 0)

    def _ed(self, a, b):
        return notoj._edit_dist(a, b)

    def test_identical(self):
        self.assertEqual(self._ed("hello", "hello"), 0)

    def test_one_insertion(self):
        self.assertEqual(self._ed("cat", "cats"), 1)

    def test_one_deletion(self):
        self.assertEqual(self._ed("cats", "cat"), 1)

    def test_one_substitution(self):
        self.assertEqual(self._ed("cat", "bat"), 1)

    def test_length_diff_gt_2_returns_99(self):
        self.assertEqual(self._ed("a", "abcde"), 99)

    def test_empty_strings(self):
        self.assertEqual(self._ed("", ""), 0)

    def test_one_empty(self):
        # Length diff of 3 → 99
        self.assertEqual(self._ed("", "abc"), 99)

    def test_two_length_diff_allowed(self):
        # "cat" vs "ca" — diff is 1, should not be 99
        self.assertNotEqual(self._ed("cat", "ca"), 99)


# ---------------------------------------------------------------------------
# sort_notes
# ---------------------------------------------------------------------------

class TestSortNotes(unittest.TestCase):
    def setUp(self):
        now = datetime.now().timestamp()
        self.notes = [
            make_note(title="Zebra", modified=now - 300, created=now - 600, path="/a.md"),
            make_note(title="Apple", modified=now - 100, created=now - 200, path="/b.md"),
            make_note(title="Mango", modified=now - 200, created=now - 400, path="/c.md"),
        ]

    def test_sort_by_title(self):
        result = notoj.sort_notes(self.notes, "title", False)
        titles = [n["title"] for n in result]
        self.assertEqual(titles, ["Apple", "Mango", "Zebra"])

    def test_sort_by_title_reversed(self):
        result = notoj.sort_notes(self.notes, "title", True)
        titles = [n["title"] for n in result]
        self.assertEqual(titles, ["Zebra", "Mango", "Apple"])

    def test_sort_by_modified_desc(self):
        result = notoj.sort_notes(self.notes, "modified", True)
        # Most recently modified first (least seconds ago)
        self.assertEqual(result[0]["title"], "Apple")

    def test_sort_by_created_asc(self):
        # Zebra: created=now-600 (oldest → smallest ts → first ascending)
        # Mango: created=now-400
        # Apple: created=now-200 (most recent)
        result = notoj.sort_notes(self.notes, "created", False)
        self.assertEqual(result[0]["title"], "Zebra")


# ---------------------------------------------------------------------------
# rank_notes / search
# ---------------------------------------------------------------------------

class TestRankNotes(unittest.TestCase):
    def setUp(self):
        now = datetime.now().timestamp()
        self.notes = [
            make_note(title="dentist", content="dentist\nright on country club", modified=now - 86400, path="/dentist.md"),
            make_note(title="gifts/presents", content="gifts/presents\nideas", modified=now - 3600, path="/gifts.md"),
            make_note(title="Hummus recipe", content="Hummus recipe\nchickpeas", modified=now - 86400 * 10, path="/hummus.md"),
            make_note(title="raspberry pi guide", content="raspberry pi guide\nssh setup", modified=now - 86400 * 5, tags=["tech"], path="/pi.md"),
        ]

    def test_empty_query_returns_all(self):
        result = notoj.rank_notes(self.notes, "")
        self.assertEqual(len(result), len(self.notes))

    def test_whitespace_query_returns_all(self):
        result = notoj.rank_notes(self.notes, "   ")
        self.assertEqual(len(result), len(self.notes))

    def test_exact_title_match_ranks_first(self):
        result = notoj.rank_notes(self.notes, "dentist")
        self.assertEqual(result[0]["title"], "dentist")

    def test_partial_title_match(self):
        result = notoj.rank_notes(self.notes, "hummus")
        self.assertEqual(result[0]["title"], "Hummus recipe")

    def test_no_match_returns_empty(self):
        result = notoj.rank_notes(self.notes, "xyzzy")
        self.assertEqual(result, [])

    def test_body_match(self):
        result = notoj.rank_notes(self.notes, "chickpeas")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Hummus recipe")

    def test_tag_match(self):
        result = notoj.rank_notes(self.notes, "tech")
        self.assertEqual(result[0]["title"], "raspberry pi guide")

    def test_quoted_phrase_search(self):
        result = notoj.rank_notes(self.notes, '"raspberry pi"')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "raspberry pi guide")

    def test_quoted_phrase_no_partial(self):
        # "country club" should match body of dentist, not others
        result = notoj.rank_notes(self.notes, '"country club"')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "dentist")

    def test_quoted_phrase_sorted_by_modified(self):
        # Phrase results must come back newest-first, not in input (load) order.
        now = datetime.now().timestamp()
        notes = [
            make_note(title="older", content="alpha beta", modified=now - 1000, path="/o.md"),
            make_note(title="newer", content="alpha beta", modified=now - 10, path="/n.md"),
        ]
        result = notoj.rank_notes(notes, '"alpha beta"')
        self.assertEqual([n["title"] for n in result], ["newer", "older"])

    def test_quoted_phrase_crosses_whitespace(self):
        # The space in the query matches any whitespace run, incl. a newline.
        now = datetime.now().timestamp()
        notes = [
            make_note(title="t", content="buy cat\nfood today", modified=now, path="/a.md"),
            make_note(title="t", content="buy cat    food today", modified=now, path="/b.md"),
        ]
        result = notoj.rank_notes(notes, '"cat food"')
        self.assertEqual(len(result), 2)

    def test_quoted_phrase_matches_into_word(self):
        # Substring into a word still counts: "CAT foods" matches "cat food".
        now = datetime.now().timestamp()
        notes = [make_note(title="CAT foods", content="x", modified=now, path="/a.md")]
        result = notoj.rank_notes(notes, '"cat food"')
        self.assertEqual(len(result), 1)

    def test_quoted_phrase_reorder_and_extra_words_excluded(self):
        now = datetime.now().timestamp()
        notes = [
            make_note(title="t", content="food cat", modified=now, path="/a.md"),
            make_note(title="t", content="catch the food", modified=now, path="/b.md"),
        ]
        result = notoj.rank_notes(notes, '"cat food"')
        self.assertEqual(result, [])

    def test_quoted_empty_phrase_no_match(self):
        # '""' has len==2 so the quoted-phrase branch (len>2) is NOT taken;
        # it falls through to token matching where '""' literally matches nothing.
        result = notoj.rank_notes(self.notes, '""')
        self.assertEqual(result, [])

    def test_recency_bonus(self):
        # gifts was modified 1h ago (within 7d), dentist 1d ago — both match "ideas" is only in gifts
        result = notoj.rank_notes(self.notes, "gifts")
        self.assertEqual(result[0]["title"], "gifts/presents")

    def test_case_insensitive(self):
        result = notoj.rank_notes(self.notes, "HUMMUS")
        self.assertEqual(result[0]["title"], "Hummus recipe")

    def test_fuzzy_match(self):
        # "humms" is 1 edit from "hummus" (length diff = 1, within threshold)
        result = notoj.rank_notes(self.notes, "humms")
        # Should find Hummus recipe via fuzzy title match
        self.assertGreater(len(result), 0)
        self.assertEqual(result[0]["title"], "Hummus recipe")


# ---------------------------------------------------------------------------
# typed_char — printable-key decoding, incl. multibyte UTF-8 reassembly
# ---------------------------------------------------------------------------

class FakeScreen:
    """Minimal stdscr stand-in: getch() returns queued ints in order."""
    def __init__(self, queued=()):
        self._q = list(queued)
    def getch(self):
        return self._q.pop(0)


class TestTypedChar(unittest.TestCase):
    def test_ascii_printable(self):
        self.assertEqual(notoj.typed_char(FakeScreen(), ord("a")), "a")
        self.assertEqual(notoj.typed_char(FakeScreen(), ord(" ")), " ")

    def test_control_and_special_keys_rejected(self):
        for k in (10, 13, 27, 9, 127, curses_stub.KEY_BACKSPACE):
            self.assertIsNone(notoj.typed_char(FakeScreen(), k))

    def test_two_byte_arabic(self):
        # "ب" U+0628 -> 0xD8 0xA8: lead byte arrives via k, continuation via getch.
        ch = "ب"
        lead, cont = ch.encode("utf-8")
        self.assertEqual(notoj.typed_char(FakeScreen([cont]), lead), ch)

    def test_three_byte(self):
        # "あ" U+3042 -> three bytes; two follow the lead.
        ch = "あ"
        b = ch.encode("utf-8")
        self.assertEqual(notoj.typed_char(FakeScreen(list(b[1:])), b[0]), ch)

    def test_four_byte_emoji(self):
        ch = "\U0001f600"  # 😀
        b = ch.encode("utf-8")
        self.assertEqual(notoj.typed_char(FakeScreen(list(b[1:])), b[0]), ch)

    def test_invalid_sequence_returns_none(self):
        # Lead byte expecting a continuation, fed a bogus one -> decode fails.
        self.assertIsNone(notoj.typed_char(FakeScreen([0x00]), 0xD8))


class TestWordBoundary(unittest.TestCase):
    def test_back_from_end(self):
        # "delete previous word" target: start of the word left of the cursor.
        s = "hello world"
        self.assertEqual(notoj.word_boundary(s, len(s), forward=False), 6)

    def test_back_skips_trailing_space(self):
        s = "hello world   "
        self.assertEqual(notoj.word_boundary(s, len(s), forward=False), 6)

    def test_back_from_start_is_zero(self):
        self.assertEqual(notoj.word_boundary("abc", 0, forward=False), 0)

    def test_back_mid_word(self):
        # Cursor inside "world" (after "wor") rubs out back to the word start.
        self.assertEqual(notoj.word_boundary("hello world", 9, forward=False), 6)

    def test_forward_from_start(self):
        self.assertEqual(notoj.word_boundary("hello world", 0, forward=True), 5)

    def test_forward_skips_leading_space(self):
        self.assertEqual(notoj.word_boundary("  hello", 0, forward=True), 7)

    def test_forward_from_end_is_len(self):
        s = "abc"
        self.assertEqual(notoj.word_boundary(s, len(s), forward=True), len(s))


# ---------------------------------------------------------------------------
# EditBuffer — the one readline field behind every text input
# ---------------------------------------------------------------------------

def _feed(queued=()):
    """Zero-arg getch stand-in: queued ints in order, then -1 (idle)."""
    q = list(queued)
    return lambda: q.pop(0) if q else -1


class TestEditBuffer(unittest.TestCase):
    def buf(self, text, pos=None):
        b = notoj.EditBuffer(text)
        if pos is not None:
            b.pos = pos
        return b

    def test_insert_ascii(self):
        b = self.buf("")
        self.assertEqual(b.handle_key(ord("h"), _feed()), "changed")
        self.assertEqual(b.handle_key(ord("i"), _feed()), "changed")
        self.assertEqual((b.text, b.pos), ("hi", 2))

    def test_insert_mid_string(self):
        b = self.buf("hd", pos=1)
        b.handle_key(ord("a"), _feed())
        self.assertEqual((b.text, b.pos), ("had", 2))

    def test_insert_utf8_multibyte(self):
        ch = "ب"
        lead, cont = ch.encode("utf-8")
        b = self.buf("")
        self.assertEqual(b.handle_key(lead, _feed([cont])), "changed")
        self.assertEqual(b.text, ch)

    def test_backspace_mid_string(self):
        b = self.buf("abc", pos=2)
        self.assertEqual(b.handle_key(127, _feed()), "changed")
        self.assertEqual((b.text, b.pos), ("ac", 1))

    def test_backspace_at_start_moves_only(self):
        b = self.buf("abc", pos=0)
        self.assertEqual(b.handle_key(127, _feed()), "moved")
        self.assertEqual(b.text, "abc")

    def test_ctrl_d_deletes_under_cursor(self):
        b = self.buf("abc", pos=1)
        self.assertEqual(b.handle_key(4, _feed()), "changed")
        self.assertEqual((b.text, b.pos), ("ac", 1))

    def test_ctrl_w_deletes_word_back(self):
        b = self.buf("hello world")
        self.assertEqual(b.handle_key(23, _feed()), "changed")
        self.assertEqual((b.text, b.pos), ("hello ", 6))

    def test_ctrl_u_deletes_to_start(self):
        b = self.buf("hello world", pos=6)
        self.assertEqual(b.handle_key(21, _feed()), "changed")
        self.assertEqual((b.text, b.pos), ("world", 0))

    def test_ctrl_k_deletes_to_end(self):
        b = self.buf("hello world", pos=5)
        self.assertEqual(b.handle_key(11, _feed()), "changed")
        self.assertEqual((b.text, b.pos), ("hello", 5))

    def test_cursor_motions(self):
        b = self.buf("abc")
        b.handle_key(curses_stub.KEY_LEFT, _feed())
        self.assertEqual(b.pos, 2)
        b.handle_key(1, _feed())      # Ctrl-a / Home
        self.assertEqual(b.pos, 0)
        b.handle_key(6, _feed())      # Ctrl-f / →
        self.assertEqual(b.pos, 1)
        b.handle_key(5, _feed())      # Ctrl-e / End
        self.assertEqual(b.pos, 3)

    def test_alt_b_f_word_motions(self):
        b = self.buf("hello world")
        self.assertEqual(b.handle_key(27, _feed(), peek=_feed([ord("b")])), "moved")
        self.assertEqual(b.pos, 6)
        self.assertEqual(b.handle_key(27, _feed(), peek=_feed([ord("f")])), "moved")
        self.assertEqual(b.pos, 11)

    def test_alt_d_deletes_word_ahead(self):
        b = self.buf("hello world", pos=6)
        self.assertEqual(b.handle_key(27, _feed(), peek=_feed([ord("d")])), "changed")
        self.assertEqual(b.text, "hello ")

    def test_alt_backspace_deletes_word_back(self):
        b = self.buf("hello world")
        self.assertEqual(b.handle_key(27, _feed(), peek=_feed([127])), "changed")
        self.assertEqual((b.text, b.pos), ("hello ", 6))

    def test_bare_esc_cancels(self):
        b = self.buf("abc")
        self.assertEqual(b.handle_key(27, _feed(), peek=_feed()), "cancel")

    def test_enter_submits(self):
        self.assertEqual(self.buf("abc").handle_key(10, _feed()), "submit")
        self.assertEqual(self.buf("abc").handle_key(13, _feed()), "submit")

    def test_unconsumed_key_returns_none(self):
        # Up/Down aren't editing keys: the caller navigates its list on them.
        b = self.buf("abc")
        self.assertIsNone(b.handle_key(curses_stub.KEY_UP, _feed()))
        self.assertIsNone(b.handle_key(curses_stub.KEY_DOWN, _feed()))
        self.assertEqual(b.text, "abc")


class TestFilterIndices(unittest.TestCase):
    ITEMS = ["alpha", "beta", "alphabet", "gamma"]

    @staticmethod
    def match(it, ql):
        return ql in it.lower()

    def test_empty_query_is_identity(self):
        self.assertEqual(notoj.filter_indices(self.ITEMS, self.match, ""),
                         [0, 1, 2, 3])

    def test_filtered_positions_map_to_originals(self):
        idx = notoj.filter_indices(self.ITEMS, self.match, "alpha")
        self.assertEqual(idx, [0, 2])
        self.assertEqual([self.ITEMS[i] for i in idx], ["alpha", "alphabet"])

    def test_case_insensitive(self):
        self.assertEqual(notoj.filter_indices(self.ITEMS, self.match, "BETA"), [1])

    def test_no_match_empty(self):
        self.assertEqual(notoj.filter_indices(self.ITEMS, self.match, "zzz"), [])


# ---------------------------------------------------------------------------
# search_subset — filter that composes with any view's ordering
# ---------------------------------------------------------------------------

class TestSearchSubset(unittest.TestCase):
    def setUp(self):
        # A deliberately non-relevance order (e.g. loops "most stale first").
        self.notes = [
            make_note(title="zeta report", path="/z.md"),
            make_note(title="alpha report", path="/a.md"),
            make_note(title="gamma notes", path="/g.md"),
        ]

    def test_empty_query_returns_list_unchanged(self):
        self.assertIs(notoj.search_subset(self.notes, "", preserve_order=True),
                      self.notes)
        self.assertIs(notoj.search_subset(self.notes, "  ", preserve_order=False),
                      self.notes)

    def test_filters_to_matches(self):
        out = notoj.search_subset(self.notes, "report", preserve_order=True)
        self.assertEqual([n["title"] for n in out],
                         ["zeta report", "alpha report"])

    def test_preserve_order_keeps_input_order(self):
        # "report" matches zeta and alpha; input order (zeta before alpha) is
        # kept rather than reordered by relevance.
        out = notoj.search_subset(self.notes, "report", preserve_order=True)
        self.assertEqual([n["path"] for n in out], ["/z.md", "/a.md"])

    def test_relevance_order_when_not_preserving(self):
        # "alpha report" is an exact title match -> ranks ahead of "zeta report".
        out = notoj.search_subset(self.notes, "alpha report", preserve_order=False)
        self.assertEqual(out[0]["title"], "alpha report")

    def test_no_match_is_empty(self):
        self.assertEqual(
            notoj.search_subset(self.notes, "xyzzy", preserve_order=True), [])


# ---------------------------------------------------------------------------
# order_notes / sort_label — the unified per-view ordering
# ---------------------------------------------------------------------------

class TestOrderNotes(unittest.TestCase):
    def setUp(self):
        # Base in a deliberate non-modified order (e.g. loops most-stale-first).
        self.base = [
            make_note(title="beta", modified=300, created=1, path="/b.md"),
            make_note(title="alpha", modified=100, created=3, path="/a.md"),
            make_note(title="gamma", modified=200, created=2, path="/g.md"),
        ]

    def _titles(self, lst):
        return [n["title"] for n in lst]

    def test_relevance_no_query_keep_preserves_base_order(self):
        # loops/dups (keep=True): "relevance" at rest leaves the base order.
        out = notoj.order_notes(self.base, "relevance", True, "", keep=True)
        self.assertEqual(self._titles(out), ["beta", "alpha", "gamma"])

    def test_relevance_no_query_nonkeep_is_modified_desc(self):
        # notes/trash (keep=False): "relevance" at rest = modified, newest first.
        out = notoj.order_notes(self.base, "relevance", True, "", keep=False)
        self.assertEqual(self._titles(out), ["beta", "gamma", "alpha"])

    def test_relevance_with_query_filters(self):
        out = notoj.order_notes(self.base, "relevance", True, "alpha", keep=False)
        self.assertEqual(self._titles(out), ["alpha"])

    def test_relevance_query_keep_preserves_order(self):
        # keep=True keeps the base order among matches (no relevance reshuffle).
        out = notoj.order_notes(self.base, "relevance", True, "a", keep=True)
        # "beta"/"alpha"/"gamma" all contain "a"; base order is retained.
        self.assertEqual(self._titles(out), ["beta", "alpha", "gamma"])

    def test_field_sort_applies_in_any_view(self):
        out = notoj.order_notes(self.base, "title", False, "", keep=True)
        self.assertEqual(self._titles(out), ["alpha", "beta", "gamma"])

    def test_field_sort_filters_then_sorts(self):
        out = notoj.order_notes(self.base, "created", False, "a", keep=False)
        # matches all three; sorted by created ascending: beta(1),gamma(2),alpha(3)
        self.assertEqual(self._titles(out), ["beta", "gamma", "alpha"])


class TestSortLabel(unittest.TestCase):
    def test_relevance_at_rest_shows_natural(self):
        self.assertEqual(
            notoj.sort_label("relevance", True, "", "most stale first", False),
            "most stale first")

    def test_relevance_while_searching_plain_view(self):
        self.assertEqual(
            notoj.sort_label("relevance", True, "budget", "modified 🞃", False),
            "relevance")

    def test_relevance_while_searching_keep_view_stays_natural(self):
        # loops/dups filter rather than rerank, so the label stays natural.
        self.assertEqual(
            notoj.sort_label("relevance", True, "budget", "most stale first", True),
            "most stale first")

    def test_field_sort_shows_arrow(self):
        self.assertEqual(notoj.sort_label("title", False, "", "x", False), "title 🞁")
        self.assertEqual(notoj.sort_label("modified", True, "", "x", True), "modified 🞃")


# ---------------------------------------------------------------------------
# extract_hashtags
# ---------------------------------------------------------------------------

class TestExtractHashtags(unittest.TestCase):
    def test_simple_hashtag(self):
        self.assertEqual(notoj.extract_hashtags("hello #world"), ["world"])

    def test_hashtag_at_start(self):
        self.assertEqual(notoj.extract_hashtags("#listoj"), ["listoj"])

    def test_multiple_hashtags(self):
        result = notoj.extract_hashtags("note #foo and #bar")
        self.assertIn("foo", result)
        self.assertIn("bar", result)

    def test_no_digit_start(self):
        # #1 should NOT be captured (pattern requires [a-zA-Z] start)
        result = notoj.extract_hashtags("note #1 and #2")
        self.assertEqual(result, [])

    def test_url_fragment_not_captured(self):
        # A # preceded by / should NOT be captured
        result = notoj.extract_hashtags("https://example.com/path#section")
        self.assertEqual(result, [])

    def test_word_preceded_hash_not_captured(self):
        # #preceded by word char should not be captured
        result = notoj.extract_hashtags("foo#bar")
        self.assertEqual(result, [])

    def test_hashtag_with_underscore_and_dash(self):
        result = notoj.extract_hashtags("#my_tag-name")
        self.assertEqual(result, ["my_tag-name"])

    def test_deduplication(self):
        result = notoj.extract_hashtags("#foo text #foo again")
        self.assertEqual(result.count("foo"), 1)

    def test_order_preserved(self):
        result = notoj.extract_hashtags("#a text #b text #c")
        self.assertEqual(result, ["a", "b", "c"])

    def test_empty_string(self):
        self.assertEqual(notoj.extract_hashtags(""), [])

    def test_code_comment_hash_not_captured(self):
        # "# comment" — starts with space before hash, hash at start of line
        # This should be captured since there's no word char before it.
        result = notoj.extract_hashtags("    # comment")
        # "#" followed by space — no match since tag must start with [a-zA-Z]
        # "# comment" has space after #, so no match
        self.assertEqual(result, [])

    def test_ascii_art_wall_not_captured(self):
        # Solid walls / box rows contain stray border '#' and must be ignored.
        self.assertEqual(notoj.extract_hashtags("############"), [])
        self.assertEqual(notoj.extract_hashtags("#      #c#"), [])
        self.assertEqual(notoj.extract_hashtags("########D###"), [])

    def test_bordered_map_row_not_captured(self):
        # Bordered rows like "#w...gw...#" have a trailing border '#' (stray).
        self.assertEqual(notoj.extract_hashtags("#w...gw.....gw...#"), [])
        self.assertEqual(notoj.extract_hashtags("   1 #w...gw...#"), [])
        # Trailing margin annotation after the closing border.
        self.assertEqual(notoj.extract_hashtags("#g...#.#g.#...gw...#  ╮"), [])

    def test_score_and_year_tags_kept(self):
        # '#' followed by a digit (score/year) is not stray and must not drop
        # the real word-tags on the same line.
        self.assertEqual(
            notoj.extract_hashtags("#Worldle #144 1/6 (100%)"), ["Worldle"])
        self.assertEqual(
            notoj.extract_hashtags("#nye #2019 #bhangra"), ["nye", "bhangra"])

    def test_fenced_code_block_skipped(self):
        text = "real #tag\n```\n#define FOO 1\n#include <x>\n```\n#after"
        self.assertEqual(notoj.extract_hashtags(text), ["tag", "after"])

    def test_inline_code_span_skipped(self):
        self.assertEqual(notoj.extract_hashtags("color is `#B5B5B5` here"), [])
        self.assertEqual(
            notoj.extract_hashtags("set `#LidSwitchIgnoreInhibited` in conf"), [])

    def test_tag_outside_code_span_kept(self):
        self.assertEqual(
            notoj.extract_hashtags("`#sidebar-header` css fix #linux"), ["linux"])

    def test_code_span_with_stray_hash_does_not_poison_line(self):
        # A stray '#' inside backticks no longer marks the whole line as art.
        self.assertEqual(
            notoj.extract_hashtags("`# comment` about #bash"), ["bash"])

    def test_unclosed_backtick_left_alone(self):
        self.assertEqual(notoj.extract_hashtags("a stray ` and #tag"), ["tag"])


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------

class TestFindDuplicates(unittest.TestCase):
    def test_no_duplicates(self):
        notes = [
            make_note(title="Alpha", path="/a.md"),
            make_note(title="Beta", path="/b.md"),
        ]
        result = notoj.find_duplicates(notes)
        self.assertEqual(result, [])

    def test_two_same_title(self):
        notes = [
            make_note(title="dentist", modified=100.0, path="/a.md"),
            make_note(title="dentist", modified=200.0, path="/b.md"),
        ]
        result = notoj.find_duplicates(notes)
        self.assertEqual(len(result), 2)

    def test_case_insensitive_match(self):
        notes = [
            make_note(title="Dentist", modified=100.0, path="/a.md"),
            make_note(title="dentist", modified=200.0, path="/b.md"),
        ]
        result = notoj.find_duplicates(notes)
        self.assertEqual(len(result), 2)

    def test_most_recent_first_in_group(self):
        notes = [
            make_note(title="dentist", modified=100.0, path="/a.md"),
            make_note(title="dentist", modified=200.0, path="/b.md"),
        ]
        result = notoj.find_duplicates(notes)
        self.assertEqual(result[0]["modificationDate"], 200.0)

    def test_three_duplicates(self):
        notes = [
            make_note(title="note", modified=100.0, path="/a.md"),
            make_note(title="note", modified=200.0, path="/b.md"),
            make_note(title="note", modified=300.0, path="/c.md"),
        ]
        result = notoj.find_duplicates(notes)
        self.assertEqual(len(result), 3)

    def test_mixed_duplicates_and_unique(self):
        notes = [
            make_note(title="dup", modified=100.0, path="/a.md"),
            make_note(title="dup", modified=200.0, path="/b.md"),
            make_note(title="unique", modified=300.0, path="/c.md"),
        ]
        result = notoj.find_duplicates(notes)
        self.assertEqual(len(result), 2)
        titles = [n["title"] for n in result]
        self.assertNotIn("unique", titles)


# ---------------------------------------------------------------------------
# atomic_write
# ---------------------------------------------------------------------------

class TestAtomicWrite(unittest.TestCase):
    def test_writes_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.md")
            notoj.atomic_write(path, "hello world")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello world")

    def test_overwrites_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.md")
            with open(path, "w") as f:
                f.write("old content")
            notoj.atomic_write(path, "new content")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "new content")

    def test_no_tmp_file_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.md")
            notoj.atomic_write(path, "data")
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_unicode_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.md")
            notoj.atomic_write(path, "سكرابل")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "سكرابل")


# ---------------------------------------------------------------------------
# sync_hashtags
# ---------------------------------------------------------------------------

class TestSyncHashtags(unittest.TestCase):
    def _write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_adds_new_hashtag(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                "My note with #newtag\n"
            ))
            notoj.sync_hashtags(path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("newtag", text)

    def test_does_not_duplicate_existing_tag(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags:\n"
                "  - existing\n"
                "---\n"
                "\n"
                "Note with #existing tag\n"
            ))
            notoj.sync_hashtags(path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertEqual(text.count("existing"), 2)  # once in tags, once in body

    def test_no_hashtags_no_change(self):
        content = (
            "---\n"
            "id: abc\n"
            "created: 2013-10-08T13:08:43Z\n"
            "modified: 2013-10-08T13:08:43Z\n"
            "version: 1\n"
            "tags: []\n"
            "---\n"
            "\n"
            "No hashtags here.\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, content)
            notoj.sync_hashtags(path)
            with open(path, encoding="utf-8") as f:
                result = f.read()
            self.assertEqual(result, content)

    def test_url_hash_not_added_as_tag(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                "See https://example.com/page#section for details.\n"
            ))
            notoj.sync_hashtags(path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("  - section", text)

    def test_no_frontmatter_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, "just plain text #tag")
            notoj.sync_hashtags(path)  # should not raise

    def test_adds_multiple_new_hashtags(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                "Note with #alpha and #beta tags\n"
            ))
            notoj.sync_hashtags(path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("alpha", text)
            self.assertIn("beta", text)

    def test_notag_note_not_synced(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            original = (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "notag: true\n"
                "tags: []\n"
                "---\n"
                "\n"
                "channel list: #acehelp #passthepopcorn\n"
            )
            self._write(path, original)
            notoj.sync_hashtags(path)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), original)

    def test_notag_keeps_manual_tags(self):
        # notag stops the body sweep; tags already in frontmatter stay put.
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, (
                "---\n"
                "id: abc\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "notag: true\n"
                "tags:\n"
                "  - reference\n"
                "---\n"
                "\n"
                "config uses #LidSwitchIgnoreInhibited\n"
            ))
            notoj.sync_hashtags(path)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("  - reference", text)
            self.assertNotIn("LidSwitchIgnoreInhibited\n---", text.split("---")[1])


class TestAddTagsKeepDate(unittest.TestCase):
    def _note(self, d):
        path = os.path.join(d, "note.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "---\nid: abc\ncreated: 2020-01-01T00:00:00Z\n"
                "modified: 2020-01-01T00:00:00Z\nversion: 1\ntags: []\n---\n\nSome note\n"
            )
        os.utime(path, (1_000_000, 1_000_000))
        return path

    def test_preserves_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._note(d)
            added = notoj.add_tags_keep_date(p, ["work"])
            self.assertEqual(added, ["work"])
            self.assertIn("  - work", open(p, encoding="utf-8").read())
            self.assertEqual(os.path.getmtime(p), 1_000_000)

    def test_noop_add_leaves_file_alone(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._note(d)
            notoj.add_tags(p, ["work"])
            os.utime(p, (1_000_000, 1_000_000))
            self.assertEqual(notoj.add_tags_keep_date(p, ["work"]), [])
            self.assertEqual(os.path.getmtime(p), 1_000_000)


class TestRemoveTagsFrontmatter(unittest.TestCase):
    def _note(self, d, tags, body="Some note with `#sidebar-header` inline\n"):
        path = os.path.join(d, "note.md")
        tag_block = "tags:\n" + "".join(f"  - {t}\n" for t in tags) if tags else "tags: []\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "---\nid: abc\ncreated: 2020-01-01T00:00:00Z\n"
                "modified: 2020-01-01T00:00:00Z\nversion: 1\n"
                + tag_block + "---\n\n" + body
            )
        return path

    def test_removes_only_given_tags(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._note(d, ["a", "b", "c"])
            self.assertTrue(notoj.remove_tags_frontmatter(p, ["b"]))
            text = open(p, encoding="utf-8").read()
            self.assertIn("  - a", text)
            self.assertNotIn("  - b", text)
            self.assertIn("  - c", text)

    def test_empties_to_flow_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._note(d, ["only"])
            self.assertTrue(notoj.remove_tags_frontmatter(p, ["only"]))
            self.assertIn("tags: []", open(p, encoding="utf-8").read())

    def test_body_untouched(self):
        # Unlike remove_tag, inline occurrences in the body must survive.
        with tempfile.TemporaryDirectory() as d:
            p = self._note(d, ["sidebar-header"], body="css fix #sidebar-header\n")
            self.assertTrue(notoj.remove_tags_frontmatter(p, ["sidebar-header"]))
            text = open(p, encoding="utf-8").read()
            self.assertIn("css fix #sidebar-header", text)
            self.assertNotIn("  - sidebar-header", text)

    def test_noop_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._note(d, ["a"])
            before = open(p, encoding="utf-8").read()
            self.assertFalse(notoj.remove_tags_frontmatter(p, ["zzz"]))
            self.assertEqual(open(p, encoding="utf-8").read(), before)


class TestNotagFlag(unittest.TestCase):
    def test_true_variants(self):
        for v in ("true", "True", "TRUE", "yes", "1", " true "):
            self.assertTrue(notoj.notag({"notag": v}), v)

    def test_absent_or_false(self):
        for meta in ({}, {"notag": "false"}, {"notag": ""}, {"notag": "no"}):
            self.assertFalse(notoj.notag(meta), meta)


# ---------------------------------------------------------------------------
# parse_tag_input
# ---------------------------------------------------------------------------

class TestParseTagInput(unittest.TestCase):
    def test_space_separated(self):
        self.assertEqual(notoj.parse_tag_input("work urgent"), ["work", "urgent"])

    def test_strips_leading_hash(self):
        self.assertEqual(notoj.parse_tag_input("#work #urgent"), ["work", "urgent"])

    def test_mixed_hash_and_plain(self):
        self.assertEqual(notoj.parse_tag_input("#work urgent"), ["work", "urgent"])

    def test_collapses_extra_whitespace(self):
        self.assertEqual(notoj.parse_tag_input("  a   b  "), ["a", "b"])

    def test_empty_string(self):
        self.assertEqual(notoj.parse_tag_input(""), [])

    def test_whitespace_only(self):
        self.assertEqual(notoj.parse_tag_input("   "), [])

    def test_bare_hashes_dropped(self):
        self.assertEqual(notoj.parse_tag_input("# ## a"), ["a"])

    def test_multiple_leading_hashes_stripped(self):
        self.assertEqual(notoj.parse_tag_input("##tag"), ["tag"])


# ---------------------------------------------------------------------------
# add_tags
# ---------------------------------------------------------------------------

class TestAddTags(unittest.TestCase):
    def _write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _note(self, tags_block="tags: []\n", body="Body text\n"):
        return (
            "---\n"
            "id: abc\n"
            "created: 2013-10-08T13:08:43Z\n"
            "modified: 2013-10-08T13:08:43Z\n"
            "version: 1\n"
            f"{tags_block}"
            "---\n"
            "\n"
            f"{body}"
        )

    def test_adds_to_empty_tags(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, self._note())
            added = notoj.add_tags(path, ["work", "urgent"])
            self.assertEqual(added, ["work", "urgent"])
            text = open(path, encoding="utf-8").read()
            self.assertIn("  - work", text)
            self.assertIn("  - urgent", text)

    def test_merges_with_existing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, self._note(tags_block="tags:\n  - existing\n"))
            added = notoj.add_tags(path, ["new"])
            self.assertEqual(added, ["new"])
            text = open(path, encoding="utf-8").read()
            self.assertIn("  - existing", text)
            self.assertIn("  - new", text)

    def test_skips_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, self._note(tags_block="tags:\n  - work\n"))
            added = notoj.add_tags(path, ["work"])
            self.assertEqual(added, [])
            # File unchanged: tag appears exactly once.
            text = open(path, encoding="utf-8").read()
            self.assertEqual(text.count("  - work"), 1)

    def test_partial_duplicate_adds_only_new(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, self._note(tags_block="tags:\n  - work\n"))
            added = notoj.add_tags(path, ["work", "fresh"])
            self.assertEqual(added, ["fresh"])

    def test_body_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, self._note(body="Important body.\nSecond line.\n"))
            notoj.add_tags(path, ["x"])
            text = open(path, encoding="utf-8").read()
            self.assertIn("Important body.\nSecond line.", text)

    def test_creates_tags_field_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, self._note(tags_block=""))
            added = notoj.add_tags(path, ["x"])
            self.assertEqual(added, ["x"])
            text = open(path, encoding="utf-8").read()
            self.assertIn("tags:", text)
            self.assertIn("  - x", text)

    def test_no_frontmatter_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            self._write(path, "just plain text\n")
            self.assertEqual(notoj.add_tags(path, ["x"]), [])

    def test_missing_file_returns_empty(self):
        self.assertEqual(notoj.add_tags("/no/such/file.md", ["x"]), [])

    def test_empty_tag_list_no_change(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            content = self._note()
            self._write(path, content)
            self.assertEqual(notoj.add_tags(path, []), [])
            self.assertEqual(open(path, encoding="utf-8").read(), content)


# ---------------------------------------------------------------------------
# file_snapshot + incremental_update
# ---------------------------------------------------------------------------

class TestFileSnapshot(unittest.TestCase):
    def test_captures_md_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            with open(path, "w") as f:
                f.write("test")
            snap = notoj.file_snapshot(d)
            self.assertIn(path, snap)

    def test_ignores_non_md_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.txt")
            with open(path, "w") as f:
                f.write("test")
            snap = notoj.file_snapshot(d)
            self.assertNotIn(path, snap)


class TestIncrementalUpdate(unittest.TestCase):
    def _make_note_file(self, d, name, title):
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "---\n"
                f"id: {name}\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2013-10-08T13:08:43Z\n"
                "version: 1\n"
                "tags: []\n"
                "---\n"
                "\n"
                f"{title}\n"
            )
        return path

    def test_mtime_preserving_write_detected(self):
        # add_tags_keep_date restores the mtime after writing; the snapshot
        # must still see the change (via size) so the UI reloads the note.
        with tempfile.TemporaryDirectory() as d:
            self._old = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                p = self._make_note_file(d, "a.md", "Alpha")
                os.utime(p, (1_000_000, 1_000_000))
                snap = notoj.file_snapshot(d)
                notes = [notoj.load_md(p)]
                notoj.add_tags_keep_date(p, ["work"])
                new_snap = notoj.file_snapshot(d)
                self.assertNotEqual(snap, new_snap)
                result, changed = notoj.incremental_update(notes, snap, new_snap)
                self.assertTrue(changed)
                self.assertEqual(result[0]["tags"], ["work"])
            finally:
                notoj.NOTES_DIR = self._old

    def test_no_changes_returns_false(self):
        with tempfile.TemporaryDirectory() as d:
            old_mod = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = self._make_note_file(d, "a.md", "Alpha")
                n = notoj.load_md(path)
                snap = {path: os.path.getmtime(path)}
                notes = [n]
                result, changed = notoj.incremental_update(notes, snap, snap)
                self.assertFalse(changed)
            finally:
                notoj.NOTES_DIR = old_mod

    def test_new_file_detected(self):
        with tempfile.TemporaryDirectory() as d:
            old_mod = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                snap_old = {}
                path = self._make_note_file(d, "a.md", "Alpha")
                snap_new = {path: os.path.getmtime(path)}
                result, changed = notoj.incremental_update([], snap_old, snap_new)
                self.assertTrue(changed)
                self.assertEqual(len(result), 1)
            finally:
                notoj.NOTES_DIR = old_mod

    def test_deleted_file_removed(self):
        with tempfile.TemporaryDirectory() as d:
            old_mod = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = self._make_note_file(d, "a.md", "Alpha")
                n = notoj.load_md(path)
                snap_old = {path: os.path.getmtime(path)}
                os.unlink(path)
                snap_new = {}
                result, changed = notoj.incremental_update([n], snap_old, snap_new)
                self.assertTrue(changed)
                self.assertEqual(result, [])
            finally:
                notoj.NOTES_DIR = old_mod


# ---------------------------------------------------------------------------
# clamp_scroll
# ---------------------------------------------------------------------------

class TestClampScroll(unittest.TestCase):
    def _state(self, cur=0, off=0):
        return {"cur": cur, "off": off}

    def _notes(self, n):
        return [make_note(path=f"/{i}.md") for i in range(n)]

    def test_cursor_clamped_to_max(self):
        state = self._state(cur=10)
        notes = self._notes(3)
        notoj.clamp_scroll(state, notes, 20)
        self.assertEqual(state["cur"], 2)

    def test_cursor_clamped_to_zero(self):
        state = self._state(cur=-5)
        notes = self._notes(5)
        notoj.clamp_scroll(state, notes, 20)
        self.assertEqual(state["cur"], 0)

    def test_offset_moves_down_when_cursor_below_page(self):
        # height=10, page_h=8 (rows 1..h-2). cursor at 8, off=0 → off moves to 1
        state = self._state(cur=8, off=0)
        notes = self._notes(20)
        notoj.clamp_scroll(state, notes, 10)
        self.assertGreater(state["off"], 0)
        self.assertLessEqual(state["cur"], state["off"] + (10 - 2) - 1)

    def test_offset_moves_up_when_cursor_above_window(self):
        state = self._state(cur=2, off=5)
        notes = self._notes(20)
        notoj.clamp_scroll(state, notes, 10)
        self.assertLessEqual(state["off"], state["cur"])

    def test_empty_list(self):
        state = self._state(cur=5, off=3)
        notoj.clamp_scroll(state, [], 20)
        self.assertEqual(state["cur"], 0)

    def test_cursor_stays_in_view(self):
        state = self._state(cur=3, off=3)
        notes = self._notes(10)
        notoj.clamp_scroll(state, notes, 10)
        page_h = 10 - 2
        self.assertGreaterEqual(state["cur"], state["off"])
        self.assertLess(state["cur"], state["off"] + page_h)


# ---------------------------------------------------------------------------
# find_conflicts
# ---------------------------------------------------------------------------

class TestFindConflicts(unittest.TestCase):
    def test_no_conflicts(self):
        with tempfile.TemporaryDirectory() as d:
            notoj.NOTES_DIR = d
            with open(os.path.join(d, "normal.md"), "w") as f:
                f.write("")
            result = notoj.find_conflicts()
            self.assertEqual(result, [])

    def test_detects_conflict_file(self):
        with tempfile.TemporaryDirectory() as d:
            notoj.NOTES_DIR = d
            conflict = os.path.join(d, "note.sync-conflict-20260101-120000-ABCD1234.md")
            with open(conflict, "w") as f:
                f.write("")
            result = notoj.find_conflicts()
            self.assertEqual(len(result), 1)
            original, conflict_path = result[0]
            self.assertEqual(os.path.basename(original), "note.md")
            self.assertEqual(conflict_path, conflict)

    def test_multiple_conflicts_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            notoj.NOTES_DIR = d
            c1 = os.path.join(d, "a.sync-conflict-20260101-110000-AAAA1111.md")
            c2 = os.path.join(d, "b.sync-conflict-20260101-120000-BBBB2222.md")
            for p in [c1, c2]:
                with open(p, "w") as f:
                    f.write("")
            result = notoj.find_conflicts()
            self.assertEqual(len(result), 2)
            # oldest first (sorted by filename)
            self.assertIn("a.sync-conflict", result[0][1])

    def test_non_md_conflict_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            notoj.NOTES_DIR = d
            conflict = os.path.join(d, "note.sync-conflict-20260101-120000-ABCD1234.txt")
            with open(conflict, "w") as f:
                f.write("")
            result = notoj.find_conflicts()
            self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# normalize_external_note
# ---------------------------------------------------------------------------

class TestNormalizeExternalNote(unittest.TestCase):
    def _write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_updates_modified_date(self):
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = os.path.join(d, "my-note.md")
                self._write(path, (
                    "---\n"
                    "id: abc\n"
                    "title: my note\n"
                    "created: 2013-10-08T13:08:43Z\n"
                    "modified: 2000-01-01T00:00:00Z\n"
                    "version: 1\n"
                    "tags: []\n"
                    "---\n"
                    "\n"
                    "my note\n"
                ))
                notoj.normalize_external_note(path)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                self.assertNotIn("2000-01-01", text)
            finally:
                notoj.NOTES_DIR = old_notes

    def test_renames_file_when_title_changes(self):
        # Use a title with "/" so slugify converts it to "-", making the rename visible.
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = os.path.join(d, "old-title.md")
                self._write(path, (
                    "---\n"
                    "id: abc\n"
                    "title: old/title\n"
                    "created: 2013-10-08T13:08:43Z\n"
                    "modified: 2000-01-01T00:00:00Z\n"
                    "version: 1\n"
                    "tags: []\n"
                    "---\n"
                    "\n"
                    "new/title\n"
                ))
                result_path = notoj.normalize_external_note(path)
                self.assertFalse(os.path.exists(path))
                self.assertTrue(os.path.exists(result_path))
                # slugify("new/title") → "new-title"
                self.assertIn("new-title", os.path.basename(result_path))
            finally:
                notoj.NOTES_DIR = old_notes

    def test_no_change_when_title_matches(self):
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = os.path.join(d, "my-note.md")
                now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                content = (
                    "---\n"
                    "id: abc\n"
                    "title: my note\n"
                    "created: 2013-10-08T13:08:43Z\n"
                    f"modified: {now_iso}\n"
                    "version: 1\n"
                    "tags: []\n"
                    "---\n"
                    "\n"
                    "my note\n"
                )
                self._write(path, content)
                # Touch mtime to match modified: field so no change is needed.
                # The file's mtime and the modified field will differ, so it will update;
                # but at least the file should still exist and title unchanged.
                notoj.normalize_external_note(path)
                self.assertTrue(os.path.exists(path))
            finally:
                notoj.NOTES_DIR = old_notes

    def test_no_frontmatter_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = os.path.join(d, "plain.md")
                self._write(path, "just plain text")
                notoj.normalize_external_note(path)  # should not raise
                self.assertTrue(os.path.exists(path))
            finally:
                notoj.NOTES_DIR = old_notes

    def test_backfills_missing_housekeeping_fields(self):
        # An externally-produced note with a partial frontmatter (id/title/tags
        # but no created/modified/version) should have the missing fields
        # filled in so it loads with a real modified date.
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = os.path.join(d, "craigslist-post.md")
                self._write(path, (
                    "---\n"
                    "id: abc\n"
                    "title: Craigslist Post\n"
                    "tags:\n"
                    "  - inventory\n"
                    "---\n"
                    "\n"
                    "# Craigslist Post\n"
                    "\n"
                    "Body with a --- horizontal rule.\n"
                ))
                notoj.normalize_external_note(path)
                n = notoj.load_md(path)
                self.assertIsNotNone(n)
                self.assertGreater(n["modificationDate"], 0)
                self.assertGreater(n["creationDate"], 0)
                self.assertEqual(n["version"], "1")
                # The body's --- rule must survive — only the real frontmatter
                # fence is touched.
                self.assertIn("horizontal rule", n["content"])
                self.assertEqual(n["tags"], ["inventory"])
            finally:
                notoj.NOTES_DIR = old_notes

    def test_canonical_strips_bom_and_crlf_preserving_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "external.md")
            with open(path, "wb") as f:
                f.write(
                    b"\xef\xbb\xbf"  # UTF-8 BOM
                    b"---\r\n"
                    b"id: abc\r\n"
                    b"title: External\r\n"
                    b"---\r\n"
                    b"\r\n"
                    b"External\r\n"
                )
            os.utime(path, (1_000_000_000, 1_000_000_000))
            notoj.ensure_canonical(path)
            with open(path, "rb") as f:
                raw = f.read()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r", raw)
            self.assertTrue(raw.startswith(b"---\n"))
            # mtime preserved so the cleanup doesn't read as a fresh edit.
            self.assertEqual(int(os.path.getmtime(path)), 1_000_000_000)

    def test_canonical_no_rewrite_when_already_clean(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "clean.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("---\nid: abc\ntitle: Clean\n---\n\nClean\n")
            before = os.stat(path).st_mtime_ns
            notoj.ensure_canonical(path)
            # Untouched file: same mtime (no rewrite).
            self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_canonical_then_adopt_does_not_double_front(self):
        # A BOM+CRLF file with a partial frontmatter must be canonicalized and
        # backfilled — never given a second frontmatter block.
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = os.path.join(d, "post.md")
                with open(path, "wb") as f:
                    f.write(
                        b"\xef\xbb\xbf"
                        b"---\r\n"
                        b"id: abc\r\n"
                        b"title: Post\r\n"
                        b"tags: []\r\n"
                        b"---\r\n"
                        b"\r\n"
                        b"Post\r\n"
                    )
                notoj.ensure_canonical(path)
                notoj.ensure_frontmatter(path)  # must be a no-op now
                notoj.normalize_external_note(path)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                self.assertEqual(text.count("\n---\n"), 1)  # single fence
                n = notoj.load_md(path)
                self.assertIsNotNone(n)
                self.assertEqual(n["title"], "Post")
                self.assertGreater(n["modificationDate"], 0)
            finally:
                notoj.NOTES_DIR = old_notes

    def test_backfill_is_idempotent(self):
        # After backfilling, a second pass must make no further changes — i.e.
        # the file is no longer rewritten on every scan.
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                path = os.path.join(d, "post.md")
                self._write(path, (
                    "---\n"
                    "id: abc\n"
                    "title: Post\n"
                    "tags: []\n"
                    "---\n"
                    "\n"
                    "Post\n"
                ))
                notoj.normalize_external_note(path)
                with open(path, encoding="utf-8") as f:
                    first = f.read()
                notoj.normalize_external_note(path)
                with open(path, encoding="utf-8") as f:
                    second = f.read()
                self.assertEqual(first, second)
            finally:
                notoj.NOTES_DIR = old_notes

    def test_rename_collision_handled(self):
        """When the new filename already exists, should number it."""
        # Use "/" in titles so slugify produces a predictable "-" slug.
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                # Pre-create the destination slug "new-title.md"
                dest = os.path.join(d, "new-title.md")
                self._write(dest, (
                    "---\n"
                    "id: other\n"
                    "title: new/title\n"
                    "created: 2013-10-08T13:08:43Z\n"
                    "modified: 2000-01-01T00:00:00Z\n"
                    "version: 1\n"
                    "tags: []\n"
                    "---\n"
                    "\n"
                    "new/title\n"
                ))
                path = os.path.join(d, "old-title.md")
                self._write(path, (
                    "---\n"
                    "id: abc\n"
                    "title: old/title\n"
                    "created: 2013-10-08T13:08:43Z\n"
                    "modified: 2000-01-01T00:00:00Z\n"
                    "version: 1\n"
                    "tags: []\n"
                    "---\n"
                    "\n"
                    "new/title\n"
                ))
                result_path = notoj.normalize_external_note(path)
                # "new-title.md" is taken so should produce "new-title (2).md"
                self.assertTrue(os.path.exists(dest))  # original untouched
                self.assertIn("(2)", os.path.basename(result_path))
            finally:
                notoj.NOTES_DIR = old_notes


# ---------------------------------------------------------------------------
# title / content / tags helpers
# ---------------------------------------------------------------------------

class TestNoteHelpers(unittest.TestCase):
    def test_title_from_field(self):
        n = make_note(title="My Title")
        self.assertEqual(notoj.title(n), "My Title")

    def test_title_fallback_to_content(self):
        n = make_note(title="", content="First line\nSecond line")
        self.assertEqual(notoj.title(n), "First line")

    def test_title_untitled_when_empty(self):
        n = make_note(title="", content="")
        self.assertEqual(notoj.title(n), "(untitled)")

    def test_title_untitled_when_whitespace_content(self):
        n = make_note(title="", content="   \n   ")
        self.assertEqual(notoj.title(n), "(untitled)")

    def test_content_returns_body(self):
        n = make_note(content="body text")
        self.assertEqual(notoj.content(n), "body text")

    def test_content_empty(self):
        n = make_note(content="")
        self.assertEqual(notoj.content(n), "")

    def test_tags_joined(self):
        # tags() applies the configured display order (default: frequency
        # high->low, ties alphabetical). With no frequency data loaded both
        # tags rank equal, so the alphabetical tie-break decides.
        n = make_note(tags=["foo", "bar"])
        notoj.TAG_FREQ = {}
        self.assertEqual(notoj.tags(n), "bar foo")

    def test_tags_ordered_by_frequency(self):
        n = make_note(tags=["rare", "common"])
        notoj.TAG_FREQ = {"common": 50, "rare": 2}
        try:
            self.assertEqual(notoj.tags(n), "common rare")
        finally:
            notoj.TAG_FREQ = {}

    def test_tags_empty(self):
        n = make_note(tags=[])
        self.assertEqual(notoj.tags(n), "")

    def test_is_recent_within_hour(self):
        n = make_note(modified=datetime.now().timestamp() - 1800)
        self.assertTrue(notoj.is_recent(n))

    def test_is_recent_over_hour(self):
        n = make_note(modified=datetime.now().timestamp() - 7200)
        self.assertFalse(notoj.is_recent(n))

    def test_is_recent_no_date(self):
        n = make_note(modified=0)
        self.assertFalse(notoj.is_recent(n))


# ---------------------------------------------------------------------------
# Resurface: find_loops / snooze / schedule / parse_when / remove_tag
# ---------------------------------------------------------------------------

class TestFindLoops(unittest.TestCase):
    def _loop(self, nid, modified, tags=("loop",)):
        return make_note(title=nid, tags=list(tags), modified=modified, path=f"/tmp/{nid}.md")

    def test_only_loop_tagged_surface(self):
        now = 1_000_000.0
        looped = make_note(title="a", tags=["loop"], modified=now - 100, path="/tmp/a.md")
        other = make_note(title="b", tags=["inventory"], modified=now, path="/tmp/b.md")
        looped["id"], other["id"] = "a", "b"
        loops = notoj.find_loops([looped, other], {}, now=now)
        self.assertEqual([n["id"] for n in loops], ["a"])

    def test_most_stale_first(self):
        now = 1_000_000.0
        n_old = make_note(title="old", tags=["loop"], modified=now - 9999, path="/tmp/old.md")
        n_new = make_note(title="new", tags=["loop"], modified=now - 10, path="/tmp/new.md")
        n_old["id"], n_new["id"] = "old", "new"
        loops = notoj.find_loops([n_new, n_old], {}, now=now)
        self.assertEqual([n["id"] for n in loops], ["old", "new"])

    def test_snoozed_into_future_excluded(self):
        now = 1_000_000.0
        n = make_note(title="x", tags=["loop"], modified=now - 50, path="/tmp/x.md")
        n["id"] = "x"
        review = {"x": {"due": now + 86400}}
        self.assertEqual(notoj.find_loops([n], review, now=now), [])

    def test_due_in_past_included(self):
        now = 1_000_000.0
        n = make_note(title="x", tags=["loop"], modified=now - 50, path="/tmp/x.md")
        n["id"] = "x"
        review = {"x": {"due": now - 10}}
        self.assertEqual(len(notoj.find_loops([n], review, now=now)), 1)


class TestSnoozeLoop(unittest.TestCase):
    def test_fixed_horizon_does_not_grow(self):
        now = 1_000_000.0
        review = {}
        d1 = notoj.snooze_loop(review, "x", now=now)
        # snooze again from the new "now" — still the same fixed horizon
        d2 = notoj.snooze_loop(review, "x", now=now + 1)
        self.assertEqual(d1, notoj.SNOOZE_DAYS)
        self.assertEqual(d2, notoj.SNOOZE_DAYS)

    def test_sets_due(self):
        now = 1_000_000.0
        review = {}
        notoj.snooze_loop(review, "x", now=now)
        self.assertEqual(review["x"]["due"], now + notoj.SNOOZE_DAYS * 86400)


class TestParseWhen(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000.0

    def test_relative_days(self):
        self.assertEqual(notoj.parse_when("+10d", self.now), self.now + 10 * 86400)

    def test_bare_number_is_days(self):
        self.assertEqual(notoj.parse_when("14", self.now), self.now + 14 * 86400)

    def test_weeks(self):
        self.assertEqual(notoj.parse_when("2w", self.now), self.now + 14 * 86400)

    def test_months(self):
        self.assertEqual(notoj.parse_when("3mo", self.now), self.now + 90 * 86400)

    def test_years(self):
        self.assertEqual(notoj.parse_when("1y", self.now), self.now + 365 * 86400)

    def test_keyword_tomorrow(self):
        self.assertEqual(notoj.parse_when("tomorrow", self.now), self.now + 86400)

    def test_keyword_someday(self):
        self.assertEqual(notoj.parse_when("someday", self.now), self.now + 365 * 86400)

    def test_iso_date(self):
        ts = notoj.parse_when("2026-12-01", self.now)
        self.assertEqual(
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"), "2026-12-01"
        )

    def test_garbage_returns_none(self):
        self.assertIsNone(notoj.parse_when("whenever-ish", self.now))

    def test_empty_returns_none(self):
        self.assertIsNone(notoj.parse_when("", self.now))


class TestScheduleLoop(unittest.TestCase):
    def test_sets_explicit_due(self):
        review = {}
        notoj.schedule_loop(review, "x", 123456.0)
        self.assertEqual(review["x"]["due"], 123456.0)


class TestReviewRoundTrip(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            old = notoj.REVIEW_FILE
            notoj.REVIEW_FILE = os.path.join(d, ".notoj_review.json")
            try:
                notoj.save_review({"x": {"due": 5.0}})
                self.assertEqual(notoj.load_review(), {"x": {"due": 5.0}})
            finally:
                notoj.REVIEW_FILE = old

    def test_load_missing_returns_empty(self):
        old = notoj.REVIEW_FILE
        notoj.REVIEW_FILE = "/no/such/review.json"
        try:
            self.assertEqual(notoj.load_review(), {})
        finally:
            notoj.REVIEW_FILE = old


class TestRemoveTag(unittest.TestCase):
    def _note(self, tags_block="tags:\n  - loop\n", body="Find a tax CPA #loop\n"):
        return (
            "---\n"
            "id: abc\n"
            "created: 2013-10-08T13:08:43Z\n"
            "modified: 2013-10-08T13:08:43Z\n"
            "version: 1\n"
            f"{tags_block}"
            "---\n"
            "\n"
            f"{body}"
        )

    def test_removes_frontmatter_and_inline(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._note())
            self.assertTrue(notoj.remove_tag(path, "loop"))
            text = open(path, encoding="utf-8").read()
            self.assertNotIn("- loop", text)
            self.assertNotIn("#loop", text)
            self.assertIn("Find a tax CPA", text)

    def test_keeps_other_tags(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._note(tags_block="tags:\n  - loop\n  - debt\n"))
            notoj.remove_tag(path, "loop")
            text = open(path, encoding="utf-8").read()
            self.assertIn("  - debt", text)
            self.assertNotIn("  - loop", text)

    def test_absent_tag_no_change(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            content = self._note(tags_block="tags:\n  - debt\n", body="No loop here.\n")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.assertFalse(notoj.remove_tag(path, "loop"))
            self.assertEqual(open(path, encoding="utf-8").read(), content)

    def test_does_not_strip_loophole(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._note(body="Mind the #loophole and #loop\n"))
            notoj.remove_tag(path, "loop")
            text = open(path, encoding="utf-8").read()
            self.assertIn("#loophole", text)
            self.assertNotIn("and #loop\n", text)

    def test_close_then_reopen_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._note(tags_block="tags:\n  - loop\n", body="Renew passport\n"))
            self.assertTrue(notoj.remove_tag(path, "loop"))
            self.assertNotIn("- loop", open(path, encoding="utf-8").read())
            self.assertTrue(notoj.reopen_loop(path))
            self.assertIn("  - loop", open(path, encoding="utf-8").read())

    def test_reopen_preserves_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "note.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._note(tags_block="tags: []\n", body="Body\n"))
            notoj.reopen_loop(path, mod_ts=1_000_000.0)
            self.assertEqual(int(os.path.getmtime(path)), 1_000_000)

    def test_reopen_missing_file(self):
        self.assertFalse(notoj.reopen_loop("/no/such/file.md"))


class TestUndoRedoActions(unittest.TestCase):
    """undo_action / redo_action over every tracked action kind
    (trash, loop, edit, tags, defer)."""

    def _setdirs(self, d):
        self._old = (notoj.NOTES_DIR, notoj.TRASH_DIR)
        notoj.NOTES_DIR = d
        notoj.TRASH_DIR = os.path.join(d, ".trash")

    def _restore(self):
        notoj.NOTES_DIR, notoj.TRASH_DIR = self._old

    def _loopnote(self, path, body="Renew passport #loop\n"):
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "---\nid: abc\ncreated: 2020-01-01T00:00:00Z\n"
                "modified: 2020-01-01T00:00:00Z\nversion: 1\ntags:\n  - loop\n---\n\n"
                + body
            )

    def test_edit_undo_redo(self):
        with tempfile.TemporaryDirectory() as d:
            self._setdirs(d)
            try:
                # An edit changed the title before→after, so on disk the
                # post-edit file is after.md (check_rename renamed it).
                p_before = os.path.join(d, "before.md")
                p_after = os.path.join(d, "after.md")
                A = "---\nid: a\n---\n\nbefore\n"
                B = "---\nid: a\n---\n\nafter\n"
                with open(p_after, "w", encoding="utf-8") as f:
                    f.write(B)
                act = {"kind": "edit", "path": p_after, "before": A, "after": B}
                # Undo restores the old content AND the matching filename.
                self.assertEqual(notoj.undo_action(act), p_before)
                self.assertEqual(open(p_before, encoding="utf-8").read(), A)
                self.assertFalse(os.path.exists(p_after))
                # Redo brings back both the new content and filename.
                self.assertEqual(notoj.redo_action(act), p_after)
                self.assertEqual(open(p_after, encoding="utf-8").read(), B)
                self.assertFalse(os.path.exists(p_before))
            finally:
                self._restore()

    def test_loop_undo_redo(self):
        with tempfile.TemporaryDirectory() as d:
            self._setdirs(d)
            try:
                p = os.path.join(d, "note.md")
                self._loopnote(p)
                notoj.remove_tag(p, "loop")  # simulate the x that produced the record
                act = {"kind": "loop", "path": p, "mod": 1_000_000.0}
                notoj.undo_action(act)
                self.assertIn("  - loop", open(p, encoding="utf-8").read())
                notoj.redo_action(act)
                self.assertNotIn("  - loop", open(p, encoding="utf-8").read())
            finally:
                self._restore()

    def test_tags_undo_redo(self):
        with tempfile.TemporaryDirectory() as d:
            self._setdirs(d)
            try:
                p = os.path.join(d, "note.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(
                        "---\nid: abc\ncreated: 2020-01-01T00:00:00Z\n"
                        "modified: 2020-01-01T00:00:00Z\nversion: 1\n"
                        "tags:\n  - keep\n---\n\nSome note\n"
                    )
                added = notoj.add_tags(p, ["work", "idea"])
                self.assertEqual(added, ["work", "idea"])
                act = {"kind": "tags", "path": p, "added": added, "mod": 1_000_000.0}
                # Undo drops only the added tags and restores the mtime.
                self.assertEqual(notoj.undo_action(act), p)
                text = open(p, encoding="utf-8").read()
                self.assertIn("  - keep", text)
                self.assertNotIn("  - work", text)
                self.assertNotIn("  - idea", text)
                self.assertEqual(os.path.getmtime(p), 1_000_000.0)
                # Redo re-adds them.
                self.assertEqual(notoj.redo_action(act), p)
                text = open(p, encoding="utf-8").read()
                self.assertIn("  - work", text)
                self.assertIn("  - idea", text)
            finally:
                self._restore()

    def test_trash_undo_redo(self):
        with tempfile.TemporaryDirectory() as d:
            self._setdirs(d)
            try:
                p = os.path.join(d, "note.md")
                self._loopnote(p)
                dest = notoj.do_trash(p)
                self.assertFalse(os.path.exists(p))
                self.assertTrue(os.path.exists(dest))
                act = {"kind": "trash", "orig": p, "trash": dest}
                focus = notoj.undo_action(act)  # restore
                self.assertEqual(focus, p)
                self.assertTrue(os.path.exists(p))
                self.assertIsNone(notoj.redo_action(act))  # re-trash hides note
                self.assertFalse(os.path.exists(p))
                self.assertTrue(os.path.exists(act["trash"]))
            finally:
                self._restore()

    def test_defer_undo_redo(self):
        # "defer" backs both snooze (z) and schedule (S): they only differ in
        # how the due date is computed, so one undo path covers both.
        with tempfile.TemporaryDirectory() as d:
            old = notoj.REVIEW_FILE
            notoj.REVIEW_FILE = os.path.join(d, ".notoj_review.json")
            try:
                now = 1_000_000.0
                # Snooze a loop with no prior review entry: undo removes the
                # entry entirely (the loop falls back to "due"); redo re-snoozes
                # and persists.
                review = {}
                notoj.snooze_loop(review, "n1", now=now)
                after = dict(review["n1"])
                act = {"kind": "defer", "id": "n1", "path": "/x/n1.md",
                       "before": None, "after": after}
                self.assertEqual(notoj.undo_action(act, review), "/x/n1.md")
                self.assertNotIn("n1", review)
                self.assertEqual(notoj.redo_action(act, review), "/x/n1.md")
                self.assertEqual(review["n1"], after)
                self.assertEqual(notoj.load_review()["n1"], after)

                # Schedule (S) a loop that was already snoozed: the new due date
                # overwrites the old entry, and undo restores the original
                # rather than deleting it.
                prior = {"due": now + 7 * 86400}
                review2 = {"n2": dict(prior)}
                before = dict(review2["n2"])
                notoj.schedule_loop(review2, "n2", now + 99 * 86400)
                act2 = {"kind": "defer", "id": "n2", "path": "/x/n2.md",
                        "before": before, "after": dict(review2["n2"])}
                notoj.undo_action(act2, review2)
                self.assertEqual(review2["n2"], prior)
            finally:
                notoj.REVIEW_FILE = old

    def test_do_restore_dedupes_when_original_taken(self):
        with tempfile.TemporaryDirectory() as d:
            self._setdirs(d)
            try:
                p = os.path.join(d, "note.md")
                self._loopnote(p)
                dest = notoj.do_trash(p)
                self._loopnote(p)  # a new note now occupies the original name
                restored = notoj.do_restore(dest, p)
                self.assertNotEqual(restored, p)
                self.assertTrue(os.path.exists(restored))
                self.assertTrue(os.path.exists(p))
            finally:
                self._restore()


class TestVersionIncrement(unittest.TestCase):
    """version is an edit counter: bumped on local content save (check_rename),
    preserved on adopting an external/synced edit (normalize_external_note)."""

    def _note(self, version="5", title="Foo", body="Foo\nbody\n", modified="2020-01-01T00:00:00Z"):
        return (
            "---\nid: abc\n"
            f"title: {title}\n"
            "created: 2013-10-08T13:08:43Z\n"
            f"modified: {modified}\n"
            f"version: {version}\n"
            "tags: []\n---\n\n" + body
        )

    def test_check_rename_increments(self):
        with tempfile.TemporaryDirectory() as d:
            old = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                p = os.path.join(d, "Foo.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(self._note(version="5"))
                notoj.check_rename({"path": p})
                self.assertEqual(notoj.load_md(p)["version"], "6")
            finally:
                notoj.NOTES_DIR = old

    def test_check_rename_increments_successively(self):
        with tempfile.TemporaryDirectory() as d:
            old = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                p = os.path.join(d, "Foo.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(self._note(version="5"))
                notoj.check_rename({"path": p})
                notoj.check_rename({"path": p})
                self.assertEqual(notoj.load_md(p)["version"], "7")
            finally:
                notoj.NOTES_DIR = old

    def test_check_rename_non_numeric_resets_to_one(self):
        with tempfile.TemporaryDirectory() as d:
            old = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                p = os.path.join(d, "Foo.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(self._note(version="abc"))
                notoj.check_rename({"path": p})
                self.assertEqual(notoj.load_md(p)["version"], "1")
            finally:
                notoj.NOTES_DIR = old

    def test_normalize_preserves_version(self):
        with tempfile.TemporaryDirectory() as d:
            old = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                p = os.path.join(d, "Foo.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(self._note(version="5", modified="2000-01-01T00:00:00Z"))
                os.utime(p, None)  # bump mtime so normalize sees a change to adopt
                notoj.normalize_external_note(p)
                text = open(p, encoding="utf-8").read()
                self.assertIn("version: 5", text)
                self.assertNotIn("2000-01-01", text)  # modified did update
            finally:
                notoj.NOTES_DIR = old


# ---------------------------------------------------------------------------
# ensure_id
# ---------------------------------------------------------------------------

class TestEnsureId(unittest.TestCase):
    def _write(self, path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_inserts_missing_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "n.md")
            self._write(p, "---\ntitle: foo\ntags: []\n---\n\nfoo\n")
            old_mtime = os.path.getmtime(p) - 5000
            os.utime(p, (old_mtime, old_mtime))
            notoj.ensure_id(p)
            n = notoj.load_md(p)
            self.assertTrue(n["id"])
            # mtime preserved so the insertion doesn't read as an edit
            self.assertAlmostEqual(os.path.getmtime(p), old_mtime, places=3)

    def test_replaces_empty_id_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "n.md")
            self._write(p, "---\nid:\ntitle: foo\ntags: []\n---\n\nfoo\n")
            notoj.ensure_id(p)
            text = open(p, encoding="utf-8").read()
            self.assertEqual(text.count("\nid:"), 1)  # old empty id: line is gone
            self.assertTrue(notoj.load_md(p)["id"])

    def test_keeps_existing_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "n.md")
            body = "---\nid: abc123\ntitle: foo\ntags: []\n---\n\nfoo\n"
            self._write(p, body)
            notoj.ensure_id(p)
            self.assertEqual(open(p, encoding="utf-8").read(), body)


# ---------------------------------------------------------------------------
# rename_to_title
# ---------------------------------------------------------------------------

class TestRenameToTitle(unittest.TestCase):
    def _write_note(self, d, fname, title_text):
        p = os.path.join(d, fname)
        with open(p, "w", encoding="utf-8") as f:
            f.write(
                "---\nid: abc\n"
                f"title: {title_text}\n"
                "created: 2013-10-08T13:08:43Z\n"
                "modified: 2020-01-01T00:00:00Z\n"
                "version: 1\ntags: []\n---\n\n"
                f"{title_text}\n"
            )
        return p

    def test_already_matching_name_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_note(d, "foo.md", "foo")
            self.assertEqual(notoj.rename_to_title(p), p)

    def test_renames_to_slug(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_note(d, "stale-name.md", "fresh title")
            result = notoj.rename_to_title(p)
            self.assertFalse(os.path.exists(p))
            self.assertEqual(os.path.basename(result), "fresh title.md")

    def test_collision_gets_numbered(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_note(d, "foo.md", "other note")
            p = self._write_note(d, "stale.md", "foo")
            result = notoj.rename_to_title(p)
            self.assertEqual(os.path.basename(result), "foo (2).md")

    def test_numbered_variant_of_own_slug_stays_put(self):
        with tempfile.TemporaryDirectory() as d:
            self._write_note(d, "foo.md", "foo")
            p = self._write_note(d, "foo (2).md", "foo")
            self.assertEqual(notoj.rename_to_title(p), p)


# ---------------------------------------------------------------------------
# prune_review
# ---------------------------------------------------------------------------

class TestPruneReview(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000.0
        loop = make_note(title="loop note", tags=["loop"], path="/l.md")
        loop["id"] = "live"
        plain = make_note(title="plain", tags=[], path="/p.md")
        plain["id"] = "untagged"
        self.notes = [loop, plain]

    def test_keeps_future_snooze_on_live_loop(self):
        review = {"live": {"due": self.now + 100}}
        self.assertFalse(notoj.prune_review(review, self.notes, self.now))
        self.assertIn("live", review)

    def test_drops_expired_snooze(self):
        review = {"live": {"due": self.now - 100}}
        self.assertTrue(notoj.prune_review(review, self.notes, self.now))
        self.assertEqual(review, {})

    def test_drops_untagged_and_missing_notes(self):
        review = {
            "untagged": {"due": self.now + 100},
            "gone": {"due": self.now + 100},
        }
        self.assertTrue(notoj.prune_review(review, self.notes, self.now))
        self.assertEqual(review, {})

    def test_drops_malformed_entries(self):
        review = {"live": "not-a-dict"}
        self.assertTrue(notoj.prune_review(review, self.notes, self.now))
        self.assertEqual(review, {})


# ---------------------------------------------------------------------------
# normalize_external_note: modified comes from the file mtime, mtime preserved
# ---------------------------------------------------------------------------

class TestNormalizeUsesEditTime(unittest.TestCase):
    def test_modified_set_to_file_mtime_not_now(self):
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                p = os.path.join(d, "my-note.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(
                        "---\nid: abc\ntitle: my note\n"
                        "created: 2013-10-08T13:08:43Z\n"
                        "modified: 2000-01-01T00:00:00Z\n"
                        "version: 1\ntags: []\n---\n\nmy note\n"
                    )
                # Pretend the external edit happened a day ago.
                edit_ts = datetime.now().timestamp() - 86400
                os.utime(p, (edit_ts, edit_ts))
                edit_iso = datetime.fromtimestamp(edit_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                notoj.normalize_external_note(p)
                text = open(p, encoding="utf-8").read()
                self.assertIn(f"modified: {edit_iso}", text)
                # And the mtime is restored, so mtime == modified stays stable.
                self.assertAlmostEqual(os.path.getmtime(p), edit_ts, places=3)
            finally:
                notoj.NOTES_DIR = old_notes

    def test_second_pass_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            old_notes = notoj.NOTES_DIR
            notoj.NOTES_DIR = d
            try:
                p = os.path.join(d, "my-note.md")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(
                        "---\nid: abc\ntitle: my note\n"
                        "created: 2013-10-08T13:08:43Z\n"
                        "modified: 2000-01-01T00:00:00Z\n"
                        "version: 1\ntags: []\n---\n\nmy note\n"
                    )
                edit_ts = datetime.now().timestamp() - 86400
                os.utime(p, (edit_ts, edit_ts))
                notoj.normalize_external_note(p)
                first = open(p, encoding="utf-8").read()
                first_mtime = os.path.getmtime(p)
                notoj.normalize_external_note(p)
                self.assertEqual(open(p, encoding="utf-8").read(), first)
                self.assertAlmostEqual(os.path.getmtime(p), first_mtime, places=3)
            finally:
                notoj.NOTES_DIR = old_notes


# ---------------------------------------------------------------------------
# ensure_frontmatter preserves the file mtime
# ---------------------------------------------------------------------------

class TestEnsureFrontmatterMtime(unittest.TestCase):
    def test_adoption_preserves_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "plain.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write("just some text\n")
            old_ts = datetime.now().timestamp() - 50000
            os.utime(p, (old_ts, old_ts))
            notoj.ensure_frontmatter(p)
            n = notoj.load_md(p)
            self.assertIsNotNone(n)
            self.assertAlmostEqual(os.path.getmtime(p), old_ts, places=3)
            # created/modified reflect the original mtime, not adoption time
            self.assertAlmostEqual(n["modificationDate"], old_ts, delta=1.0)


# ---------------------------------------------------------------------------
# schedule_inline_loop ("#loop <when>" typed in a note body)
# ---------------------------------------------------------------------------

class TestScheduleInlineLoop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self._old_review = notoj.REVIEW_FILE
        notoj.REVIEW_FILE = os.path.join(self.dir, ".notoj_review.json")

    def tearDown(self):
        notoj.REVIEW_FILE = self._old_review
        self._tmp.cleanup()

    def _note(self, body, note_id="abc"):
        p = os.path.join(self.dir, "n.md")
        id_line = f"id: {note_id}\n" if note_id else ""
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"---\n{id_line}title: t\ntags: []\n---\n\n{body}")
        return p

    def _body(self, p):
        text = open(p, encoding="utf-8").read()
        return text[text.find("\n---\n", 4) + 5:]

    def test_relative_horizon_pinned_to_date(self):
        p = self._note("call the bank #loop 3d soon\n")
        expected = datetime.fromtimestamp(
            notoj.parse_when("3d")).strftime("%Y-%m-%d")
        self.assertTrue(notoj.schedule_inline_loop(p))
        self.assertIn(f"#loop {expected} soon", self._body(p))
        review = notoj.load_review()
        self.assertEqual(review["abc"]["src"], expected)
        self.assertEqual(review["abc"]["due"], notoj.parse_when(expected))

    def test_absolute_date_applied_once_so_snooze_survives(self):
        p = self._note("renew passport #loop 2030-01-15\n")
        self.assertFalse(notoj.schedule_inline_loop(p))  # no body rewrite
        review = notoj.load_review()
        self.assertEqual(review["abc"]["src"], "2030-01-15")
        # Snooze in-app (different due), then an ordinary re-save runs the
        # scheduler again: the snooze must NOT be clobbered (src unchanged).
        snoozed = notoj.parse_when("2030-01-15") + 7 * 86400
        review["abc"]["due"] = snoozed
        notoj.save_review(review)
        notoj.schedule_inline_loop(p)
        self.assertEqual(notoj.load_review()["abc"]["due"], snoozed)

    def test_hand_edited_date_reschedules(self):
        p = self._note("renew passport #loop 2030-01-15\n")
        notoj.schedule_inline_loop(p)
        p2 = self._note("renew passport #loop 2030-06-01\n")
        notoj.schedule_inline_loop(p2)
        review = notoj.load_review()
        self.assertEqual(review["abc"]["src"], "2030-06-01")
        self.assertEqual(review["abc"]["due"], notoj.parse_when("2030-06-01"))

    def test_trailing_punctuation_tolerated(self):
        p = self._note("ping Sam #loop 2w.\n")
        expected = datetime.fromtimestamp(
            notoj.parse_when("2w")).strftime("%Y-%m-%d")
        self.assertTrue(notoj.schedule_inline_loop(p))
        self.assertIn(f"#loop {expected}.", self._body(p))

    def test_unparseable_token_ignored(self):
        p = self._note("#loop cleanup ideas\n")
        self.assertFalse(notoj.schedule_inline_loop(p))
        self.assertEqual(notoj.load_review(), {})
        self.assertIn("#loop cleanup ideas", self._body(p))

    def test_bare_loop_tag_ignored(self):
        p = self._note("just an open loop #loop\n")
        self.assertFalse(notoj.schedule_inline_loop(p))
        self.assertEqual(notoj.load_review(), {})

    def test_fenced_code_ignored(self):
        p = self._note("```\n#loop 3d\n```\n")
        self.assertFalse(notoj.schedule_inline_loop(p))
        self.assertEqual(notoj.load_review(), {})

    def test_other_tag_prefix_not_matched(self):
        p = self._note("#loops 3d is not a horizon\n")
        self.assertFalse(notoj.schedule_inline_loop(p))
        self.assertEqual(notoj.load_review(), {})

    def test_first_valid_horizon_wins(self):
        p = self._note("#loop 3d\nlater also #loop 9d\n")
        notoj.schedule_inline_loop(p)
        expected = datetime.fromtimestamp(
            notoj.parse_when("3d")).strftime("%Y-%m-%d")
        self.assertEqual(notoj.load_review()["abc"]["src"], expected)
        self.assertIn("#loop 9d", self._body(p))  # second left as text

    def test_note_without_id_ignored(self):
        p = self._note("#loop 3d\n", note_id=None)
        self.assertFalse(notoj.schedule_inline_loop(p))
        self.assertEqual(notoj.load_review(), {})

    def test_remove_tag_strips_pinned_date(self):
        p = self._note("call the bank #loop 2026-06-12 soon\n")
        self.assertTrue(notoj.remove_tag(p, "loop"))
        body = self._body(p)
        self.assertNotIn("#loop", body)
        self.assertNotIn("2026-06-12", body)
        self.assertIn("call the bank", body)
        self.assertIn("soon", body)


# ---------------------------------------------------------------------------
# nav_delta / clamp_list (shared list navigation)
# ---------------------------------------------------------------------------

class TestNavDelta(unittest.TestCase):
    def test_single_row(self):
        for k in (ord("j"), curses_stub.KEY_DOWN):
            self.assertEqual(notoj.nav_delta(k, 20), 1)
        for k in (ord("k"), curses_stub.KEY_UP):
            self.assertEqual(notoj.nav_delta(k, 20), -1)

    def test_half_page(self):
        self.assertEqual(notoj.nav_delta(4, 20), 10)    # Ctrl-d
        self.assertEqual(notoj.nav_delta(21, 20), -10)  # Ctrl-u

    def test_full_page_minus_overlap(self):
        self.assertEqual(notoj.nav_delta(6, 20), 19)    # Ctrl-f
        self.assertEqual(notoj.nav_delta(2, 20), -19)   # Ctrl-b

    def test_bottom(self):
        self.assertEqual(notoj.nav_delta(ord("G"), 20), notoj.NAV_BOTTOM)

    def test_non_motion_key(self):
        self.assertIsNone(notoj.nav_delta(ord("x"), 20))

    def test_tiny_page_floors_at_one(self):
        self.assertEqual(notoj.nav_delta(4, 1), 1)
        self.assertEqual(notoj.nav_delta(6, 1), 1)
        self.assertEqual(notoj.nav_delta(21, 0), -1)

    def test_nav_keys_match_decoder(self):
        for k in notoj.NAV_KEYS:
            self.assertIsNotNone(notoj.nav_delta(k, 20), k)


class TestClampList(unittest.TestCase):
    def test_clamps_cursor_to_bounds(self):
        st = {"cur": 99, "off": 0}
        notoj.clamp_list(st, 10, 5)
        self.assertEqual(st["cur"], 9)
        st = {"cur": -3, "off": 0}
        notoj.clamp_list(st, 10, 5)
        self.assertEqual(st["cur"], 0)

    def test_scrolls_down_to_keep_cursor_visible(self):
        st = {"cur": 9, "off": 0}
        notoj.clamp_list(st, 10, 5)
        self.assertEqual(st["off"], 5)

    def test_scrolls_up_to_keep_cursor_visible(self):
        st = {"cur": 2, "off": 6}
        notoj.clamp_list(st, 10, 5)
        self.assertEqual(st["off"], 2)

    def test_empty_list(self):
        st = {"cur": 4, "off": 3}
        notoj.clamp_list(st, 0, 5)
        self.assertEqual(st["cur"], 0)
        self.assertEqual(st["off"], 0)


# ---------------------------------------------------------------------------
# fit_hints (footer bar)
# ---------------------------------------------------------------------------

class TestFitHints(unittest.TestCase):
    SEGS = [(3, "s/r sort"), (2, "/ search"), (2, "⮐/e open"), (1, "q quit")]

    def test_fits_all_when_wide(self):
        self.assertEqual(notoj.fit_hints(self.SEGS, 200),
                         "s/r sort  / search  ⮐/e open  q quit")

    def test_drops_worst_priority_first(self):
        out = notoj.fit_hints(self.SEGS, 30)
        self.assertNotIn("sort", out)
        self.assertIn("q quit", out)

    def test_ties_drop_rightmost_first(self):
        out = notoj.fit_hints(self.SEGS, 25)
        # both priority-2 segments can't fit; ⮐/e open (rightmost) goes first
        self.assertIn("/ search", out)
        self.assertNotIn("open", out)

    def test_always_keeps_last_segment(self):
        self.assertEqual(notoj.fit_hints(self.SEGS, 3), "q quit")

    def test_skips_empty_texts(self):
        self.assertEqual(notoj.fit_hints([(1, "a b"), (2, ""), (1, "c d")], 80),
                         "a b  c d")


# ---------------------------------------------------------------------------
# tag_counts / filter_by_tags / tagf helpers (t and T views)
# ---------------------------------------------------------------------------

class TestTagStats(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(notoj.tag_stats([]), {})

    def test_no_tags(self):
        self.assertEqual(notoj.tag_stats([make_note("a"), make_note("b")]), {})

    def test_counts_and_latest_modified(self):
        notes = [
            make_note("a", tags=["work", "idea"], modified=100),
            make_note("b", tags=["work"], modified=300),
            make_note("c", tags=["idea", "work"], modified=200),
        ]
        self.assertEqual(notoj.tag_stats(notes),
                         {"work": (3, 300), "idea": (2, 200)})

    def test_missing_tags_field(self):
        n = make_note("a")
        n["tags"] = None
        self.assertEqual(notoj.tag_stats([n]), {})


class TestSortTagStats(unittest.TestCase):
    STATS = {"old-heavy": (10, 100), "fresh": (2, 900), "mid": (2, 500)}

    def test_recent_default_newest_first(self):
        items = notoj.sort_tag_stats(self.STATS, "recent")
        self.assertEqual([t for t, _, _ in items], ["fresh", "mid", "old-heavy"])

    def test_count_most_used_first(self):
        items = notoj.sort_tag_stats(self.STATS, "count")
        self.assertEqual([t for t, _, _ in items], ["old-heavy", "fresh", "mid"])

    def test_name_alphabetical(self):
        items = notoj.sort_tag_stats(self.STATS, "name")
        self.assertEqual([t for t, _, _ in items], ["fresh", "mid", "old-heavy"])

    def test_recent_ties_break_on_count_then_name(self):
        stats = {"b": (1, 500), "a": (1, 500), "big": (9, 500)}
        items = notoj.sort_tag_stats(stats, "recent")
        self.assertEqual([t for t, _, _ in items], ["big", "a", "b"])


class TestFilterByTags(unittest.TestCase):
    def setUp(self):
        self.a = make_note("a", tags=["work", "idea"])
        self.b = make_note("b", tags=["work"])
        self.c = make_note("c", tags=[])
        self.notes = [self.a, self.b, self.c]

    def test_single_tag(self):
        self.assertEqual(notoj.filter_by_tags(self.notes, ["work"]), [self.a, self.b])

    def test_all_tags_anded(self):
        self.assertEqual(notoj.filter_by_tags(self.notes, ["work", "idea"]), [self.a])

    def test_empty_active_matches_all(self):
        self.assertEqual(notoj.filter_by_tags(self.notes, []), self.notes)

    def test_no_match(self):
        self.assertEqual(notoj.filter_by_tags(self.notes, ["nope"]), [])

    def test_preserves_input_order(self):
        self.assertEqual(notoj.filter_by_tags([self.b, self.a], ["work"]), [self.b, self.a])


class TestTagfHelpers(unittest.TestCase):
    def test_active_all(self):
        tf = {"tags": ["a", "b", "c"], "idx": -1}
        self.assertEqual(notoj.tagf_active(tf), ["a", "b", "c"])

    def test_active_single(self):
        tf = {"tags": ["a", "b", "c"], "idx": 1}
        self.assertEqual(notoj.tagf_active(tf), ["b"])

    def test_label_all(self):
        tf = {"tags": ["a", "b"], "idx": -1}
        self.assertEqual(notoj.tagf_label(tf), "#a #b")

    def test_label_single_parenthesizes_inactive(self):
        tf = {"tags": ["a", "b", "c"], "idx": 1}
        self.assertEqual(notoj.tagf_label(tf), "(#a) #b (#c)")

    def test_cycle_wraps_to_all(self):
        # Mirrors the Tab handler: -1 -> 0 -> ... -> len-1 -> -1
        tf = {"tags": ["a", "b"], "idx": -1}
        seen = []
        for _ in range(4):
            tf["idx"] = tf["idx"] + 1 if tf["idx"] + 1 < len(tf["tags"]) else -1
            seen.append(tf["idx"])
        self.assertEqual(seen, [0, 1, -1, 0])


# ---------------------------------------------------------------------------
# KEYMAP / build_help / help_rows (? overlay and --help)
# ---------------------------------------------------------------------------

class TestKeymap(unittest.TestCase):
    def test_structure(self):
        for section, entries in notoj.KEYMAP:
            self.assertTrue(section)
            self.assertTrue(entries)
            for _action, key, desc in entries:
                self.assertTrue(key, (section, desc))
                self.assertTrue(desc, (section, key))

    def test_build_help_covers_every_key_and_section(self):
        # Wrapping splits descriptions across lines, but never reorders
        # words — compare whitespace-normalized.
        flat = " ".join(notoj.build_help(width=80).split())
        for section, entries in notoj.KEYMAP:
            self.assertIn(" ".join(section.split()), flat)
            for _action, key, desc in entries:
                self.assertIn(key, flat)
                self.assertIn(" ".join(desc.split()), flat)

    def test_build_help_is_the_help_constant(self):
        self.assertEqual(notoj.HELP, notoj.build_help())

    def test_wraps_to_width(self):
        for width in (60, 80, 120):
            for line in notoj.build_help(width=width).splitlines():
                self.assertLessEqual(len(line), width, (width, line))

    def test_continuation_lines_indent_under_description(self):
        # The long ESC description must wrap onto unkeyed lines aligned to
        # the description column (4 + HELP_KEY_W spaces).
        text = notoj.build_help(width=80)
        lines = text.splitlines()
        b_i = next(i for i, l in enumerate(lines)
                   if l.startswith("    b           backlinks:"))
        indent = " " * (4 + notoj.HELP_KEY_W)
        nxt = lines[b_i + 1]
        self.assertTrue(nxt.startswith(indent) and nxt[len(indent)] != " ",
                        f"expected wrapped continuation, got: {nxt!r}")

    def test_help_rows_flatten_and_wrap(self):
        rows = notoj.help_rows(80)
        kinds = [r[0] for r in rows]
        # KEYMAP sections plus the config-pointer trailer (section-styled,
        # may wrap to several rows on narrow widths).
        self.assertGreaterEqual(kinds.count("section"), len(notoj.KEYMAP) + 1)
        self.assertEqual(kinds.count("blank"), len(notoj.KEYMAP))
        # the trailer names the config file
        self.assertIn(notoj.CONFIG_FILE,
                      " ".join(r[2] for r in rows if r[0] == "section"))
        # continuation rows exist and carry an empty key
        self.assertTrue(any(r[0] == "entry" and r[1] == "" for r in rows))
        # every entry row's text is non-empty
        self.assertTrue(all(r[2] for r in rows if r[0] == "entry"))
        # narrower width -> more wrapped rows, and no lost words
        self.assertGreater(len(notoj.help_rows(50)), len(rows))
        flat80 = " ".join(r[2] for r in rows if r[0] == "entry")
        flat50 = " ".join(r[2] for r in notoj.help_rows(50) if r[0] == "entry")
        self.assertEqual(flat80.split(), flat50.split())


# ---------------------------------------------------------------------------
# Note links / backlinks (b view)
# ---------------------------------------------------------------------------

class TestResolveLinkTarget(unittest.TestCase):
    def test_appends_md(self):
        self.assertEqual(notoj.resolve_link_target("My note"), "My note.md")

    def test_keeps_existing_md(self):
        self.assertEqual(notoj.resolve_link_target("My note.md"), "My note.md")
        self.assertEqual(notoj.resolve_link_target("UPPER.MD"), "UPPER.MD")

    def test_strips_angle_brackets_and_whitespace(self):
        self.assertEqual(notoj.resolve_link_target(" <My note> "), "My note.md")

    def test_rejects_urls_and_empty(self):
        self.assertIsNone(notoj.resolve_link_target("https://example.com/x"))
        self.assertIsNone(notoj.resolve_link_target("ftp://host/file"))
        self.assertIsNone(notoj.resolve_link_target("  "))
        self.assertIsNone(notoj.resolve_link_target("<>"))


class TestExtractLinks(unittest.TestCase):
    def test_wikilink(self):
        self.assertEqual(notoj.extract_links("see [[Other note]] for more"),
                         ["Other note.md"])

    def test_markdown_link(self):
        self.assertEqual(notoj.extract_links("see [that](Other note.md) too"),
                         ["Other note.md"])

    def test_image_and_url_links_ignored(self):
        self.assertEqual(notoj.extract_links("[site](https://example.com)"), [])

    def test_dedup_in_order(self):
        text = "[[B]] then [[A]] then [x](B.md)"
        self.assertEqual(notoj.extract_links(text), ["B.md", "A.md"])

    def test_fenced_code_skipped(self):
        text = "[[Real]]\n```\n[[fake]]\n```\n[[Also real]]"
        self.assertEqual(notoj.extract_links(text), ["Real.md", "Also real.md"])

    def test_multiple_on_one_line(self):
        self.assertEqual(notoj.extract_links("[[A]] and [b](B)"), ["A.md", "B.md"])


class TestLinkingLines(unittest.TestCase):
    def test_finds_matching_lines_case_insensitive(self):
        text = "intro\nsee [[my note]] here\nnothing\n[x](My Note.md) again\n"
        self.assertEqual(notoj.linking_lines(text, "My note.md"),
                         ["see [[my note]] here", "[x](My Note.md) again"])

    def test_other_links_do_not_match(self):
        self.assertEqual(notoj.linking_lines("see [[Other]]", "My note.md"), [])


class TestFindBacklinks(unittest.TestCase):
    def test_backlinks_by_filename_newest_first(self):
        target = make_note("My note", path="/n/My note.md")
        a = make_note("A", content="see [[My note]]", path="/n/A.md", modified=100)
        b = make_note("B", content="[x](My note.md)", path="/n/B.md", modified=300)
        c = make_note("C", content="no links", path="/n/C.md", modified=200)
        out = notoj.find_backlinks([target, a, b, c], target)
        self.assertEqual([n["path"] for n in out], ["/n/B.md", "/n/A.md"])

    def test_self_link_excluded(self):
        target = make_note("My note", content="[[My note]]", path="/n/My note.md")
        self.assertEqual(notoj.find_backlinks([target], target), [])


class VimSearchPatternTests(unittest.TestCase):
    def test_empty_query_is_none(self):
        self.assertIsNone(notoj.vim_search_pattern(""))
        self.assertIsNone(notoj.vim_search_pattern("   "))
        self.assertIsNone(notoj.vim_search_pattern(None))

    def test_tokens_are_ored_case_insensitive_literal(self):
        self.assertEqual(notoj.vim_search_pattern("cat food"), r"\c\Vcat\|food")
        self.assertEqual(notoj.vim_search_pattern("foo"), r"\c\Vfoo")

    def test_quoted_phrase_spans_whitespace_across_lines(self):
        # \_s (not \s) so the gap can straddle a line break, like the search.
        self.assertEqual(notoj.vim_search_pattern('"cat food"'), r"\c\Vcat\_s\+food")
        self.assertEqual(
            notoj.vim_search_pattern('"a  b   c"'), r"\c\Va\_s\+b\_s\+c"
        )

    def test_backslash_is_escaped_for_very_nomagic(self):
        self.assertEqual(notoj.vim_search_pattern(r"back\slash"), r"\c\Vback\\slash")

    def test_position_args_set_pattern_then_jump(self):
        # The pattern goes in via `let @/` (never a failing /pat that would
        # leave a stale register), and the cursor jumps via the quiet search().
        args = notoj._vim_position_args(src=True, end=False, search=r"\c\Vfoo")
        self.assertEqual(args[:4], ["-c", r"let @/ = '\c\Vfoo'", "-c", "set hlsearch"])
        self.assertIn("search(@/, 'cw')", args[-1])
        self.assertIn("NotojOpenAtTitle", args[-1])  # fallback when no hit

    def test_position_args_at_end_only_highlight(self):
        args = notoj._vim_position_args(src=True, end=True, search=r"\c\Vfoo")
        self.assertEqual(
            args, ["-c", r"let @/ = '\c\Vfoo'", "-c", "set hlsearch", "-c", "normal G"]
        )
        self.assertFalse(any("search(@/" in a for a in args))

    def test_position_args_no_search_uses_title(self):
        self.assertEqual(
            notoj._vim_position_args(src=True, end=False, search=None),
            ["-c", "call NotojOpenAtTitle()"],
        )

    def test_position_args_quotes_escaped_for_let(self):
        args = notoj._vim_position_args(src=False, end=True, search=r"\c\Vit's")
        self.assertIn(r"let @/ = '\c\Vit''s'", args)


@unittest.skipUnless(
    shutil.which("vim"), "vim not installed"
)
class VimSearchIntegrationTests(unittest.TestCase):
    """Drive a real (headless) Vim with notoj's own args and read back @/ and the
    cursor — guarding against the regression where a fuzzily-ranked note with no
    literal hit left `n` searching a stale pattern."""

    def _run(self, body, search, end=False):
        d = tempfile.mkdtemp()
        try:
            note = os.path.join(d, "note.md")
            with open(note, "w", encoding="utf-8") as f:
                f.write(body)
            out = os.path.join(d, "out")
            # -i NONE: never touch (or read) the user's real ~/.viminfo, so the
            # search register starts empty and the test can't pollute it.
            args = (["vim", "-N", "-u", "NONE", "-i", "NONE"]
                    + notoj._vim_position_args(src=False, end=end, search=search)
                    + ["-c", 'call writefile([@/, line("."), col(".")], "%s")' % out,
                       "-c", "qa!", note])
            subprocess.run(args, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(out, encoding="utf-8") as f:
                reg, line, col = f.read().splitlines()
            return reg, int(line), int(col)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_register_set_and_cursor_on_first_match(self):
        body = "alpha\nbeta economics here\ngamma\n"
        pat = notoj.vim_search_pattern("economics")
        reg, line, _ = self._run(body, pat)
        self.assertEqual(reg, pat)        # @/ is our pattern, ready for `n`
        self.assertEqual(line, 2)         # landed on the match

    def test_no_literal_hit_keeps_real_pattern_no_stale(self):
        # The note ranked for "economics" but contains only "economic" — exactly
        # the fuzzy case that used to fall back to a stale viminfo pattern.
        body = "alpha\neconomic theory\ngamma\n"
        pat = notoj.vim_search_pattern("economics")
        reg, line, _ = self._run(body, pat)
        self.assertEqual(reg, pat)        # `n` would report *this* pattern, not junk
        self.assertEqual(line, 1)         # title fallback (no NotojOpenAtTitle here)

    def test_phrase_matches_across_a_line_break(self):
        body = "intro\nthe cat\nfood bowl\n"
        pat = notoj.vim_search_pattern('"cat food"')
        reg, line, _ = self._run(body, pat)
        self.assertEqual(reg, pat)
        self.assertEqual(line, 2)         # line holding the start of the phrase


class TestUndoPersistence(unittest.TestCase):
    def setUp(self):
        self._saved_log = notoj.UNDO_LOG
        self._saved_sess = notoj.SESSION_ID
        self._d = tempfile.mkdtemp()
        notoj.UNDO_LOG = os.path.join(self._d, "undo.jsonl")
        notoj.SESSION_ID = "111-1000"

    def tearDown(self):
        notoj.UNDO_LOG = self._saved_log
        notoj.SESSION_ID = self._saved_sess
        shutil.rmtree(self._d, ignore_errors=True)

    def _act(self, name, sess="111-1000"):
        return {"kind": "edit", "path": f"/n/{name}.md",
                "before": "a", "after": "b", "sess": sess}

    def test_replay_reconstructs_stacks(self):
        a, b = self._act("a"), self._act("b")
        recs = [
            {"t": "session", "ev": "launch"},
            {"t": "act", "act": a},
            {"t": "act", "act": b},
            {"t": "undo"},                 # b -> redo
        ]
        undo, redo = notoj.replay_log(recs)
        self.assertEqual(undo, [a])
        self.assertEqual(redo, [b])

    def test_action_clears_redo(self):
        a, b, c = self._act("a"), self._act("b"), self._act("c")
        recs = [{"t": "act", "act": a}, {"t": "act", "act": b},
                {"t": "undo"}, {"t": "act", "act": c}]
        undo, redo = notoj.replay_log(recs)
        self.assertEqual(undo, [a, c])
        self.assertEqual(redo, [])         # the new action invalidated redo

    def test_journal_roundtrip(self):
        a, b = self._act("a"), self._act("b")
        notoj.log_event({"t": "act", "act": a})
        notoj.log_event({"t": "act", "act": b})
        notoj.log_event({"t": "undo"})
        undo, redo = notoj.load_undo()
        self.assertEqual(undo, [a])
        self.assertEqual(redo, [b])

    def test_persist_off_when_no_log(self):
        notoj.UNDO_LOG = ""
        self.assertFalse(notoj.undo_persist_on())
        notoj.log_event({"t": "act", "act": self._act("a")})   # no-op, no crash
        self.assertEqual(notoj.load_undo(), ([], []))

    def test_torn_trailing_line_ignored(self):
        notoj.log_event({"t": "act", "act": self._act("a")})
        with open(notoj.UNDO_LOG, "a", encoding="utf-8") as f:
            f.write('{"t": "act", "act": {"kin')   # crash mid-append, no newline
        undo, _redo = notoj.load_undo()
        self.assertEqual(len(undo), 1)             # the good line still loads

    def test_compact_trims_to_cap(self):
        old_cap = notoj.UNDO_LOG_CAP
        notoj.UNDO_LOG_CAP = 5
        try:
            for i in range(40):
                notoj.log_event({"t": "act", "act": self._act(str(i))})
            with open(notoj.UNDO_LOG) as fh:
                before_lines = len(fh.read().splitlines())
            notoj.compact_log()
            with open(notoj.UNDO_LOG) as fh:
                after_lines = len(fh.read().splitlines())
            self.assertLess(after_lines, before_lines)
            undo, redo = notoj.load_undo()
            self.assertEqual(len(undo), 5)
            self.assertEqual(undo[-1]["path"], "/n/39.md")   # newest survives
            self.assertEqual(redo, [])
        finally:
            notoj.UNDO_LOG_CAP = old_cap

    def test_edit_stale_guard(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", dir=self._d,
                                         delete=False) as f:
            p = f.name
            f.write("hi")
        os.utime(p, (1000.0, 1000.0))
        fresh = {"kind": "edit", "path": p, "mtime": 1000.0}
        self.assertFalse(notoj._edit_stale(fresh))        # mtime matches
        os.utime(p, (5000.0, 5000.0))                     # external edit
        self.assertTrue(notoj._edit_stale(fresh))
        gone = {"kind": "edit", "path": p + ".nope", "mtime": 1000.0}
        self.assertTrue(notoj._edit_stale(gone))          # missing file
        no_mtime = {"kind": "edit", "path": p}            # legacy act, no stamp
        self.assertFalse(notoj._edit_stale(no_mtime))

    def test_session_alive(self):
        self.assertTrue(notoj.session_alive(f"{os.getpid()}-1000"))
        self.assertFalse(notoj.session_alive("999999999-1000"))
        self.assertFalse(notoj.session_alive("garbage"))


class TestPoolMsg(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(notoj.pool_msg({"_msg_pool": [], "_msg_idx": 0}))
        self.assertIsNone(notoj.pool_msg({}))

    def test_single_message_is_bare(self):
        self.assertEqual(notoj.pool_msg({"_msg_pool": ["hello"], "_msg_idx": 0}),
                         "hello")

    def test_joined_whole_when_it_fits(self):
        pool = ["one", "two", "three"]
        # Plenty of width: shown whole on one line, joined, no counter.
        self.assertEqual(notoj.pool_msg({"_msg_pool": pool, "_msg_idx": 0}, 80),
                         "one" + notoj.MSG_JOIN + "two" + notoj.MSG_JOIN + "three")
        # No width given: also whole (the loop passes a width; this is a guard).
        self.assertNotIn("(1/3)", notoj.pool_msg({"_msg_pool": pool, "_msg_idx": 0}))

    def test_rotates_with_counter_when_too_narrow(self):
        pool = ["one", "two", "three"]
        # Width too small for the joined form: fall back to (i/n) rotation.
        self.assertEqual(notoj.pool_msg({"_msg_pool": pool, "_msg_idx": 0}, 8),
                         "(1/3) one")
        self.assertEqual(notoj.pool_msg({"_msg_pool": pool, "_msg_idx": 2}, 8),
                         "(3/3) three")

    def test_idx_wraps(self):
        pool = ["a", "b"]
        # idx past the end wraps via modulo (rotation never indexes out of range)
        self.assertEqual(notoj.pool_msg({"_msg_pool": pool, "_msg_idx": 3}, 1),
                         "(2/2) b")


class TestLaunch(unittest.TestCase):
    def setUp(self):
        notoj.launch.missing = None

    def test_success_returns_true_and_clears_nothing(self):
        self.assertTrue(notoj.launch(["true"]))
        self.assertIsNone(notoj.launch.missing)

    def test_missing_program_returns_false_and_records_name(self):
        self.assertFalse(notoj.launch(["notoj-no-such-editor-xyz"]))
        self.assertIn("notoj-no-such-editor-xyz", notoj.launch.missing)

    def test_nonzero_exit_is_not_a_launch_failure(self):
        # The program ran (exit 1); that's the editor's business, not a missing
        # binary — launch reports success so no false "can't launch" message.
        self.assertTrue(notoj.launch(["false"]))
        self.assertIsNone(notoj.launch.missing)


class TestParseSpan(unittest.TestCase):
    def test_units(self):
        self.assertEqual(notoj.parse_span("1h"), 3600)
        self.assertEqual(notoj.parse_span("12h"), 12 * 3600)
        self.assertEqual(notoj.parse_span("1d"), 86400)
        self.assertEqual(notoj.parse_span("1w"), 7 * 86400)
        self.assertEqual(notoj.parse_span("1mo"), 30 * 86400)
        self.assertEqual(notoj.parse_span("1y"), 365 * 86400)

    def test_spellings_and_whitespace(self):
        self.assertEqual(notoj.parse_span(" 3 days "), 3 * 86400)
        self.assertEqual(notoj.parse_span("2weeks"), 14 * 86400)
        self.assertEqual(notoj.parse_span("6 hours"), 6 * 3600)

    def test_default_spans_all_parse_and_ascend(self):
        secs = [notoj.parse_span(t) for t in notoj.DATE_GRADIENT_SPANS.split(",")]
        self.assertNotIn(None, secs)
        self.assertEqual(secs, sorted(secs))
        # one more default color than there are edges (the "older" bucket)
        self.assertEqual(len(notoj.DATE_GRADIENT_COLORS.split(",")), len(secs) + 1)

    def test_bad_input(self):
        for bad in ("", "abc", "5", "1m", "h"):   # bare number / minutes / unitless
            self.assertIsNone(notoj.parse_span(bad))


class TestDateAttr(unittest.TestCase):
    def test_picks_bucket_by_age(self):
        # sentinel attrs so we can assert which bucket was chosen
        notoj._date_gradient = [(3600, "fresh"), (86400, "day"), (None, "old")]
        try:
            now = 1_000_000.0
            self.assertEqual(notoj.date_attr(now - 60, now), "fresh")     # 1 min
            self.assertEqual(notoj.date_attr(now - 7200, now), "day")     # 2 h
            self.assertEqual(notoj.date_attr(now - 200000, now), "old")   # >1 day
            self.assertEqual(notoj.date_attr(0, now), "old")             # undated
        finally:
            notoj._date_gradient = None

    def test_fallback_without_gradient(self):
        notoj._date_gradient = None
        now = 1_000_000.0
        self.assertEqual(notoj.date_attr(now - 60, now), curses_stub.color_pair(1))
        self.assertEqual(notoj.date_attr(now - 99999, now), curses_stub.color_pair(2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
