from src.cv_builder.ids import (
    _normalize,
    make_experience_id,
    make_funding_id,
    make_person_id,
    make_research_output_id,
)
import pytest


def test_make_person_id_is_stable_for_openalex_author_id():
    assert make_person_id("A123") == make_person_id("https://openalex.org/A123")
    assert make_person_id("A123").startswith("person_")


def test_make_person_id_requires_author_identity():
    with pytest.raises(ValueError):
        make_person_id("")


def test_normalize_converts_input_to_string_before_stripping():
    assert _normalize(123) == "123"


def test_normalize_extracts_openalex_id_from_string_containing_url():
    assert _normalize("prefix https://openalex.org/W456") == "w456"


def test_normalize_extracts_final_openalex_path_segment():
    assert _normalize("https://openalex.org/works/W456") == "w456"


def test_normalize_extracts_final_openalex_path_segment_from_embedded_url_with_query():
    assert _normalize("prefix https://openalex.org/works/W456?x=1") == "w456"


def test_child_ids_are_stable_and_person_scoped():
    person_id = make_person_id("A123")
    assert make_research_output_id(person_id, "https://openalex.org/W456") == make_research_output_id(person_id, "W456")
    assert make_experience_id(person_id, "orcid", "Professor", "Example University", "2020", "") == make_experience_id(
        person_id,
        "orcid",
        "Professor",
        "Example University",
        "2020",
        "",
    )
    assert make_funding_id(person_id, "orcid", "award-1", "NSF", "Example Grant") == make_funding_id(
        person_id,
        "orcid",
        "award-1",
        "NSF",
        "Example Grant",
    )


def test_hash_id_serialization_preserves_delimiter_boundaries():
    person_id = make_person_id("A123")
    assert make_experience_id(person_id, "a|b", "c", "d", "e", "f") != make_experience_id(
        person_id,
        "a",
        "b|c",
        "d",
        "e",
        "f",
    )
