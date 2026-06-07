"""Tests for update_ratings.py — pure parsing / matching / rendering logic.

The single OMDb network call (omdb_lookup) is exercised with urlopen stubbed;
everything else is pure and runs offline.
"""

import io
import json
import os
import sys
import unittest
from unittest import mock

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
import update_ratings as ur  # noqa: E402


# ---------------------------------------------------------------------------
# parse_bullet
# ---------------------------------------------------------------------------

class TestParseBullet(unittest.TestCase):
    def test_no_comment(self):
        self.assertEqual(ur.parse_bullet("The Dark Knight"),
                         ("The Dark Knight", ""))

    def test_strips_comment(self):
        self.assertEqual(ur.parse_bullet("The Dark Knight   # rewatched, great"),
                         ("The Dark Knight", "rewatched, great"))

    def test_comment_lowercased(self):
        _, comment = ur.parse_bullet("Foo # IGNORE")
        self.assertEqual(comment, "ignore")

    def test_ignore_directive(self):
        title, comment = ur.parse_bullet("Ramin Bahrani (director)   # ignore")
        self.assertEqual(title, "Ramin Bahrani (director)")
        self.assertEqual(comment, "ignore")

    def test_hash_without_leading_space_kept_in_title(self):
        # Only whitespace-then-# starts a comment, so "C#" survives.
        self.assertEqual(ur.parse_bullet("The C# Programming Language"),
                         ("The C# Programming Language", ""))


# ---------------------------------------------------------------------------
# already_known
# ---------------------------------------------------------------------------

class TestAlreadyKnown(unittest.TestCase):
    def test_direct_substring(self):
        self.assertTrue(ur.already_known("Inception", ["Inception", "Tenet"]))

    def test_word_overlap_reordered(self):
        # "Clark, Civilisation" should match "Civilisation (Kenneth Clark)".
        self.assertTrue(
            ur.already_known("Clark, Civilisation",
                             ["Civilisation (Kenneth Clark)"]))

    def test_no_overlap_is_unknown(self):
        self.assertFalse(
            ur.already_known("A Brand Title", ["Civilisation"]))

    def test_empty_bullet_treated_as_known(self):
        # No meaningful words -> skip (don't add as new).
        self.assertTrue(ur.already_known("", []))

    def test_subset_match(self):
        self.assertTrue(ur.already_known("Dune Part Two", ["Dune"]))


# ---------------------------------------------------------------------------
# sort_key
# ---------------------------------------------------------------------------

class TestSortKey(unittest.TestCase):
    def test_placeholders_sort_last(self):
        for v in ("?", "—", ""):
            self.assertEqual(ur.sort_key(v), -1.0)

    def test_no_digits_sorts_last(self):
        self.assertEqual(ur.sort_key("N/A"), -1.0)

    def test_percent(self):
        self.assertEqual(ur.sort_key("94%"), 94.0)

    def test_imdb_scaled_to_100(self):
        # "8.5 (IMDb)" -> 85 so it sits on the same scale as RT %.
        self.assertEqual(ur.sort_key("8.5 (IMDb)"), 85.0)

    def test_plain_number(self):
        self.assertEqual(ur.sort_key("8.1"), 8.1)


# ---------------------------------------------------------------------------
# split_frontmatter
# ---------------------------------------------------------------------------

class TestSplitFrontmatter(unittest.TestCase):
    def test_with_frontmatter(self):
        text = "---\ntitle: Movies\n---\nbody here\n"
        fm, body = ur.split_frontmatter(text)
        self.assertEqual(fm, "---\ntitle: Movies\n---\n")
        self.assertEqual(body, "body here\n")

    def test_without_frontmatter(self):
        text = "no frontmatter\nbody\n"
        fm, body = ur.split_frontmatter(text)
        self.assertEqual(fm, "")
        self.assertEqual(body, text)


# ---------------------------------------------------------------------------
# parse_existing
# ---------------------------------------------------------------------------

class TestParseExisting(unittest.TestCase):
    BLOCK = "\n".join([
        ur.START,
        "## Ratings",
        "",
        ur.LEGEND["movie"],
        "",
        "| Film | Rating |",
        "|---|---|",
        "| The Dark Knight | 94% |",
        "| Inception | 87% |",
        "",
        "*No rating found: Some Film, Another One.*",
        ur.END,
    ])

    def test_reads_rated_rows(self):
        rated, none = ur.parse_existing(self.BLOCK)
        self.assertEqual(rated["The Dark Knight"], "94%")
        self.assertEqual(rated["Inception"], "87%")

    def test_skips_header_and_separator(self):
        rated, _ = ur.parse_existing(self.BLOCK)
        self.assertNotIn("Film", rated)
        self.assertNotIn("---", rated)
        self.assertEqual(len(rated), 2)

    def test_reads_no_rating_list(self):
        _, none = ur.parse_existing(self.BLOCK)
        self.assertEqual(none, ["Some Film", "Another One"])


# ---------------------------------------------------------------------------
# section_titles
# ---------------------------------------------------------------------------

class TestSectionTitles(unittest.TestCase):
    def test_collects_bullets_and_honors_comments(self):
        body = "\n".join([
            "# Movies",
            "",
            "## 2024",
            "- The Dark Knight",
            "- Inception   # great",
            "- Ramin Bahrani (director)   # ignore",
            "",
        ])
        self.assertEqual(ur.section_titles(body, None),
                         ["The Dark Knight", "Inception"])

    def test_excludes_block_span(self):
        block = ur.START + "\n| Film | Rating |\n| Buried Title | 99% |\n" + ur.END
        body = "## 2024\n- Visible Title\n\n" + block + "\n"
        span = ur.find_block(body)
        titles = ur.section_titles(body, span)
        self.assertIn("Visible Title", titles)
        self.assertNotIn("Buried Title", titles)


# ---------------------------------------------------------------------------
# render_block
# ---------------------------------------------------------------------------

class TestRenderBlock(unittest.TestCase):
    def test_sorted_descending_with_markers(self):
        rated = {"Inception": "87%", "The Dark Knight": "94%"}
        block = ur.render_block("Rating", "movie", rated, ["Foo"])
        self.assertTrue(block.startswith(ur.START))
        self.assertTrue(block.rstrip().endswith(ur.END))
        # Higher rating sorts first.
        self.assertLess(block.index("The Dark Knight"), block.index("Inception"))
        self.assertIn("| Film | Rating |", block)
        self.assertIn("*No rating found: Foo.*", block)

    def test_header_label_per_kind(self):
        self.assertIn("| Book | Goodreads |",
                      ur.render_block("Goodreads", "book", {}, []))
        self.assertIn("| Title | IMDb |",
                      ur.render_block("IMDb", "tv", {}, []))

    def test_no_none_line_when_empty(self):
        block = ur.render_block("Rating", "movie", {"A": "50%"}, [])
        self.assertNotIn("No rating found", block)


# ---------------------------------------------------------------------------
# omdb_lookup  (network stubbed)
# ---------------------------------------------------------------------------

def _fake_urlopen(payload):
    """Return a context-manager factory yielding a file-like JSON response."""
    def _open(url, timeout=None):
        return io.BytesIO(json.dumps(payload).encode())
    return _open


class TestOmdbLookup(unittest.TestCase):
    def test_no_key_returns_none_without_network(self):
        with mock.patch.object(ur, "OMDB_KEY", ""):
            with mock.patch.object(ur.urllib.request, "urlopen",
                                   side_effect=AssertionError("should not call")):
                self.assertIsNone(ur.omdb_lookup("Inception", "movie"))

    def test_movie_prefers_rotten_tomatoes(self):
        payload = {"Response": "True", "imdbRating": "8.8",
                   "Ratings": [{"Source": "Rotten Tomatoes", "Value": "87%"}]}
        with mock.patch.object(ur, "OMDB_KEY", "x"), \
             mock.patch.object(ur.urllib.request, "urlopen", _fake_urlopen(payload)):
            self.assertEqual(ur.omdb_lookup("Inception", "movie"), "87%")

    def test_movie_falls_back_to_imdb(self):
        payload = {"Response": "True", "imdbRating": "8.8", "Ratings": []}
        with mock.patch.object(ur, "OMDB_KEY", "x"), \
             mock.patch.object(ur.urllib.request, "urlopen", _fake_urlopen(payload)):
            self.assertEqual(ur.omdb_lookup("Obscure Film", "movie"), "8.8 (IMDb)")

    def test_tv_returns_imdb_rating(self):
        payload = {"Response": "True", "imdbRating": "9.1", "Ratings": []}
        with mock.patch.object(ur, "OMDB_KEY", "x"), \
             mock.patch.object(ur.urllib.request, "urlopen", _fake_urlopen(payload)):
            self.assertEqual(ur.omdb_lookup("The Wire", "tv"), "9.1")

    def test_not_found_returns_none(self):
        payload = {"Response": "False", "Error": "Movie not found!"}
        with mock.patch.object(ur, "OMDB_KEY", "x"), \
             mock.patch.object(ur.urllib.request, "urlopen", _fake_urlopen(payload)):
            self.assertIsNone(ur.omdb_lookup("Nope", "movie"))


if __name__ == "__main__":
    unittest.main()
