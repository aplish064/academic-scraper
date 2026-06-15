from src.cv_builder.matching import (
    author_rank_matches,
    names_are_similar,
    normalize_name,
    normalize_title,
    titles_are_similar,
    years_are_compatible,
)


def test_normalize_title_removes_punctuation_and_collapses_spaces():
    assert normalize_title("  A Study: of AI, Systems! ") == "a study of ai systems"


def test_titles_are_similar_accepts_equal_normalized_titles():
    assert titles_are_similar("A Study of AI Systems", "a study: of ai systems")


def test_titles_are_similar_rejects_short_or_different_titles():
    assert not titles_are_similar("AI", "AI")
    assert not titles_are_similar("A Study of AI Systems", "A Different Biology Paper")


def test_normalize_name_removes_punctuation_and_lowercases():
    assert normalize_name("Junyou Zhang") == "junyou zhang"
    assert normalize_name("Zhang, Junyou") == "zhang junyou"


def test_names_are_similar_accepts_token_overlap_and_initial_variant():
    assert names_are_similar("Junyou Zhang", ["Juny Zhang", "J. Zhang"])


def test_names_are_similar_rejects_unrelated_names():
    assert not names_are_similar("Junyou Zhang", ["Michael Smith"])


def test_years_are_compatible_accepts_same_or_missing_year():
    assert years_are_compatible(2020, 2020)
    assert years_are_compatible(2020, None)
    assert not years_are_compatible(2020, 2022)


def test_author_rank_matches_accepts_same_or_nearby_rank():
    assert author_rank_matches(3, 3)
    assert author_rank_matches(3, 4)
    assert not author_rank_matches(3, 7)
