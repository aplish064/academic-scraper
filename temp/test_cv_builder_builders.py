import json
from datetime import datetime

from src.cv_builder.builders import (
    build_experience_rows,
    build_funding_rows,
    build_profile_row,
    build_research_output_row,
    clean_text,
    extract_orcid_bio,
    extract_orcid_email,
    normalize_openalex_id,
    normalize_orcid,
)
from src.cv_builder.ids import (
    make_experience_id,
    make_funding_id,
    make_person_id,
    make_research_output_id,
)


def test_helpers_normalize_and_extract_only_reliable_text():
    record = {
        "person": {
            "biography": {"content": "  Computer pioneer.  "},
            "emails": {"email": [{"email": " ada@example.edu "}]},
        }
    }

    assert clean_text("  null  ") == ""
    assert normalize_openalex_id("https://openalex.org/authors/a123") == "A123"
    assert normalize_orcid("https://orcid.org/0000-0002-1825-009x") == "0000-0002-1825-009X"
    assert extract_orcid_bio(record) == "Computer pioneer."
    assert extract_orcid_email(record) == "ada@example.edu"


def test_build_profile_uses_internal_id_openalex_identity_and_orcid_bio_email():
    author = {
        "id": "https://openalex.org/authors/A123",
        "display_name": "Ada Lovelace",
        "orcid": "https://orcid.org/0000-0001-0000-0000",
        "bio": "Do not trust OpenAlex for bio",
        "email": "do-not-use@example.edu",
        "last_known_institutions": [{"country_code": "GB"}],
    }
    record = {
        "orcid-identifier": {"path": "0000-0001-0000-0000"},
        "person": {
            "biography": {"content": "Computer pioneer."},
            "emails": {"email": [{"email": "ada@example.edu"}]},
        },
    }

    row = build_profile_row(author, record)

    assert row["id"] == make_person_id("A123")
    assert row["openalex_id"] == "A123"
    assert row["orcid"] == "0000-0001-0000-0000"
    assert row["name"] == "Ada Lovelace"
    assert row["bio"] == "Computer pioneer."
    assert row["email"] == "ada@example.edu"
    assert row["country"] == "GB"
    assert row["source"] == "openalex+orcid"
    assert row["source_url"] == "https://openalex.org/authors/A123"
    assert isinstance(row["import_time"], datetime)


def test_build_profile_leaves_unavailable_unreliable_fields_empty():
    row = build_profile_row(
        {
            "id": "A123",
            "display_name": "Ada Lovelace",
            "bio": "not from ORCID",
            "email": "not-from-orcid@example.edu",
            "last_known_institutions": [{"display_name": "Example University"}],
        },
        {},
    )

    assert row["bio"] == ""
    assert row["email"] == ""
    assert row["country"] == ""
    assert row["orcid"] == ""
    assert row["source"] == "openalex"


def test_build_profile_row_extracts_openalex_h_index():
    row = build_profile_row(
        {
            "id": "https://openalex.org/A123",
            "display_name": "Ada Lovelace",
            "summary_stats": {"h_index": 42},
        },
        {},
    )
    assert row["h_index"] == 42


def test_build_profile_row_leaves_h_index_none_when_missing():
    row = build_profile_row(
        {"id": "https://openalex.org/A123", "display_name": "Ada Lovelace"},
        {},
    )
    assert row["h_index"] is None


def test_build_profile_row_requires_openalex_author_id():
    assert build_profile_row({"display_name": "No Source ID"}, {}) == {}


def test_build_experience_rows_only_uses_orcid_employments_and_educations():
    person_id = make_person_id("A123")
    record = {
        "orcid-identifier": {"path": "0000-0001-0000-0000"},
        "activities-summary": {
            "employments": {
                "affiliation-group": [
                    {
                        "summaries": [
                            {
                                "employment-summary": {
                                    "put-code": 7,
                                    "role-title": "Professor",
                                    "department-name": "Computer Science",
                                    "organization": {
                                        "name": "Example University",
                                        "address": {"city": "Boston", "region": "MA", "country": "US"},
                                    },
                                    "start-date": {"year": {"value": "2020"}},
                                    "end-date": None,
                                }
                            }
                        ]
                    }
                ]
            },
            "educations": {
                "affiliation-group": [
                    {
                        "summaries": [
                            {
                                "education-summary": {
                                    "put-code": 8,
                                    "role-title": "PhD",
                                    "department-name": "Mathematics",
                                    "organization": {
                                        "name": "Learning Institute",
                                        "address": {"city": "London", "region": "", "country": "GB"},
                                    },
                                    "start-date": {"year": {"value": "2016"}, "month": {"value": "9"}},
                                    "end-date": {"year": {"value": "2019"}, "month": {"value": "6"}},
                                }
                            }
                        ]
                    }
                ]
            },
        },
    }

    rows = build_experience_rows(person_id, record)

    assert len(rows) == 2
    employment = rows[0]
    assert employment["id"] == make_experience_id(
        person_id,
        "orcid",
        "Professor",
        "Example University",
        "2020",
        "",
        external_id="7",
        department_name="Computer Science",
    )
    assert employment["author_id"] == person_id
    assert employment["role_title"] == "Professor"
    assert employment["institution_name"] == "Example University"
    assert employment["department_name"] == "Computer Science"
    assert employment["city"] == "Boston"
    assert employment["affiliation_type"] == "employment"
    assert employment["province"] == "MA"
    assert employment["date_range"] == "2020-"
    assert employment["country"] == "US"
    assert employment["source"] == "orcid"
    assert employment["source_url"] == "https://orcid.org/0000-0001-0000-0000"
    assert isinstance(employment["import_time"], datetime)

    education = rows[1]
    assert education["affiliation_type"] == "education"
    assert education["institution_name"] == "Learning Institute"
    assert education["date_range"] == "2016-09-2019-06"


def test_build_experience_rows_skips_non_orcid_affiliations_and_missing_institutions():
    person_id = make_person_id("A123")
    record = {
        "authorships": [
            {
                "institutions": [
                    {"display_name": "Paper Affiliation University", "country_code": "US"},
                ]
            }
        ],
        "activities-summary": {
            "employments": {
                "affiliation-group": [
                    {"summaries": [{"employment-summary": {"role-title": "Researcher"}}]},
                ]
            }
        },
    }

    assert build_experience_rows(person_id, record) == []


def test_child_builders_skip_blank_person_id():
    record = {
        "activities-summary": {
            "employments": {
                "affiliation-group": [
                    {"summaries": [{"employment-summary": {"organization": {"name": "Example University"}}}]},
                ]
            },
            "fundings": {
                "group": [
                    {"funding-summary": [{"title": {"title": {"value": "Grant"}}}]},
                ]
            },
        }
    }
    work = {"id": "W456", "title": "Reliable title"}

    assert build_experience_rows("", record) == []
    assert build_funding_rows("", record) == []
    assert build_research_output_row("", work, {}) == {}


def test_build_experience_rows_uses_orcid_put_code_to_keep_distinct_rows():
    person_id = make_person_id("A123")
    record = {
        "activities-summary": {
            "employments": {
                "affiliation-group": [
                    {
                        "summaries": [
                            {
                                "employment-summary": {
                                    "put-code": 7,
                                    "role-title": "Professor",
                                    "organization": {"name": "Example University"},
                                    "start-date": {"year": {"value": "2020"}},
                                }
                            },
                            {
                                "employment-summary": {
                                    "put-code": 8,
                                    "role-title": "Professor",
                                    "organization": {"name": "Example University"},
                                    "start-date": {"year": {"value": "2020"}},
                                }
                            },
                        ]
                    }
                ]
            }
        }
    }

    rows = build_experience_rows(person_id, record)

    assert len(rows) == 2
    assert len({row["id"] for row in rows}) == 2


def test_build_research_output_row_prefers_crossref_metadata_and_openalex_authors():
    person_id = make_person_id("A123")
    openalex_work = {
        "id": "https://openalex.org/works/W456",
        "title": "OpenAlex title",
        "type": "article",
        "publication_date": "2024-01-02",
        "authorships": [
            {
                "author": {"id": "https://openalex.org/A123", "display_name": "Ada Lovelace"},
                "institutions": [{"display_name": "Example University"}],
            }
        ],
        "primary_location": {"source": {"display_name": "Journal A"}},
    }
    crossref_work = {
        "title": ["Crossref title"],
        "type": "journal-article",
        "container-title": ["Journal B"],
        "published-print": {"date-parts": [[2024, 1, 3]]},
    }

    row = build_research_output_row(person_id, openalex_work, crossref_work)

    assert row["id"] == make_research_output_id(person_id, "W456")
    assert row["author_id"] == person_id
    assert row["work_title"] == "Crossref title"
    assert row["work_type"] == "journal-article"
    assert row["venue_name"] == "Journal B"
    assert row["publication_date"] == "2024-01-03"
    assert json.loads(row["authors"]) == ["Ada Lovelace"]
    assert row["source"] == "openalex+crossref"
    assert row["source_url"] == "https://openalex.org/works/W456"
    assert isinstance(row["import_time"], datetime)


def test_build_research_output_row_falls_back_to_openalex_and_empty_strings():
    person_id = make_person_id("A123")
    openalex_work = {
        "id": "W456",
        "title": "OpenAlex title",
        "authorships": [],
        "primary_location": {},
    }

    row = build_research_output_row(person_id, openalex_work, {})

    assert row["work_title"] == "OpenAlex title"
    assert row["work_type"] == ""
    assert row["venue_name"] == ""
    assert row["publication_date"] == ""
    assert row["authors"] == "[]"
    assert row["source"] == "openalex"


def test_build_research_output_row_extracts_openalex_citation_count():
    row = build_research_output_row(
        make_person_id("A123"),
        {
            "id": "https://openalex.org/W456",
            "title": "OpenAlex title",
            "cited_by_count": 17,
        },
        {},
    )
    assert row["citation_count"] == 17


def test_build_research_output_row_leaves_citation_count_none_when_missing():
    row = build_research_output_row(
        make_person_id("A123"),
        {"id": "https://openalex.org/W456", "title": "OpenAlex title"},
        {},
    )
    assert row["citation_count"] is None


def test_build_research_output_row_requires_openalex_work_id():
    assert build_research_output_row(make_person_id("A123"), {"title": "No ID"}, {}) == {}


def test_build_funding_rows_uses_orcid_structured_fields_and_stable_ids():
    person_id = make_person_id("A123")
    record = {
        "orcid-identifier": {"path": "0000-0001-0000-0000"},
        "activities-summary": {
            "fundings": {
                "group": [
                    {
                        "funding-summary": [
                            {
                                "put-code": 9,
                                "path": "/0000-0001-0000-0000/funding/9",
                                "title": {"title": {"value": "Analytical Engine Grant"}},
                                "type": "grant",
                                "organization": {
                                    "name": "Science Foundation",
                                    "address": {"city": "Paris", "region": "Ile-de-France", "country": "FR"},
                                },
                                "start-date": {"year": {"value": "2021"}, "month": {"value": "01"}},
                                "end-date": {
                                    "year": {"value": "2022"},
                                    "month": {"value": "12"},
                                    "day": {"value": "31"},
                                },
                            }
                        ]
                    }
                ]
            }
        },
    }

    rows = build_funding_rows(person_id, record)

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == make_funding_id(person_id, "orcid", "9", "Science Foundation", "Analytical Engine Grant")
    assert row["author_id"] == person_id
    assert row["end_date"] == "2022-12-31"
    assert row["award_title"] == "Analytical Engine Grant"
    assert row["city"] == "Paris"
    assert row["funder_name"] == "Science Foundation"
    assert row["province"] == "Ile-de-France"
    assert row["funding_type"] == "grant"
    assert row["country"] == "FR"
    assert row["start_date"] == "2021-01"
    assert row["source"] == "orcid"
    assert row["source_url"] == "https://orcid.org/0000-0001-0000-0000/funding/9"
    assert isinstance(row["import_time"], datetime)


def test_build_funding_rows_skips_empty_unstructured_funding_records():
    person_id = make_person_id("A123")
    record = {
        "activities-summary": {
            "fundings": {
                "group": [
                    {"funding-summary": [{"type": "grant", "organization": {"address": {"country": "US"}}}]},
                ]
            }
        }
    }

    assert build_funding_rows(person_id, record) == []
