import unittest

from src.author_aggregation import normalization


class AuthorAggregationNormalizationTests(unittest.TestCase):
    def test_normalize_author_name_lowercases_and_removes_punctuation_noise(self):
        self.assertEqual(normalization.normalize_author_name("  Ada B. Lovelace,  "), "ada b lovelace")

    def test_normalize_author_name_preserves_unicode_letters(self):
        self.assertEqual(normalization.normalize_author_name(" 王 小明 "), "王 小明")

    def test_normalize_title_removes_markup_punctuation_and_collapses_space(self):
        raw = "A <b>Fast</b> Study of $E=mc^2$: Results!"
        self.assertEqual(normalization.normalize_title(raw), "a fast study of emc2 results")

    def test_normalize_doi_removes_url_prefix_and_lowercases(self):
        self.assertEqual(normalization.normalize_doi("https://doi.org/10.1145/ABC.DEF"), "10.1145/abc.def")

    def test_stable_u64_is_deterministic(self):
        first = normalization.stable_u64("openalex", "W1", "1", "alice")
        second = normalization.stable_u64("openalex", "W1", "1", "alice")
        self.assertEqual(first, second)
        self.assertIsInstance(first, int)
        self.assertGreaterEqual(first, 0)

    def test_source_row_key_prefers_author_id_when_present(self):
        key = normalization.build_source_row_key(
            source="openalex",
            source_paper_id="W1",
            author_rank=1,
            source_author_id="A1",
            normalized_author_name="alice",
        )
        self.assertEqual(key, "openalex:W1:1:A1")

    def test_source_row_key_hashes_name_when_author_id_missing(self):
        key = normalization.build_source_row_key(
            source="arxiv",
            source_paper_id="2401.00001",
            author_rank=2,
            source_author_id="",
            normalized_author_name="alice smith",
        )
        self.assertTrue(key.startswith("arxiv:2401.00001:2:name_"))


if __name__ == "__main__":
    unittest.main()
