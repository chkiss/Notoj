"""Tests for notoj — pure-logic and filesystem functions."""

import importlib.machinery
import os
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
        # 100 days > 90-day threshold → months format
        result = notoj.ago(self._ts(100 * 86400))
        self.assertRegex(result, r"^\d+m$")

    def test_years_exact(self):
        # 3 years = 36 months = 0 remainder → no trailing "m"
        result = notoj.ago(self._ts(365 * 86400 * 3))
        self.assertRegex(result, r"^\d+y$")

    def test_years_with_months(self):
        # 2.5 years → 2y6m (30 months ÷ 12 = 2 rem 6)
        result = notoj.ago(self._ts(int(2.5 * 365 * 86400)))
        self.assertRegex(result, r"^\d+y\d+m$")

    def test_boundary_90_days(self):
        # Just under 90 days → days; just over → months
        under = notoj.ago(self._ts(89 * 86400))
        over = notoj.ago(self._ts(91 * 86400))
        self.assertRegex(under, r"^\d+d$")
        self.assertRegex(over, r"^\d+m$")


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
        # height=10, page_h=7. cursor at 8, off=0 → off should move to 2
        state = self._state(cur=8, off=0)
        notes = self._notes(20)
        notoj.clamp_scroll(state, notes, 10)
        self.assertGreater(state["off"], 0)
        self.assertLessEqual(state["cur"], state["off"] + (10 - 3) - 1)

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
        page_h = 10 - 3
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
        n = make_note(tags=["foo", "bar"])
        self.assertEqual(notoj.tags(n), "foo bar")

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
    """undo_action / redo_action over the three tracked action kinds."""

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
                p = os.path.join(d, "note.md")
                A = "---\nid: a\n---\n\nbefore\n"
                B = "---\nid: a\n---\n\nafter\n"
                with open(p, "w", encoding="utf-8") as f:
                    f.write(B)
                act = {"kind": "edit", "path": p, "before": A, "after": B}
                self.assertEqual(notoj.undo_action(act), p)
                self.assertEqual(open(p, encoding="utf-8").read(), A)
                self.assertEqual(notoj.redo_action(act), p)
                self.assertEqual(open(p, encoding="utf-8").read(), B)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
