import pytest

from src.cv_builder.ids import make_person_id
from src.cv_builder.runner import CvBuildRunner


class FakeRepository:
    def __init__(self, work_ids=None, fail_on=None):
        self.work_ids = list(work_ids or [])
        self.fail_on = fail_on
        self.statuses = []
        self.profiles = []
        self.experiences = []
        self.research_outputs = []
        self.funding = []
        self.local_work_requests = []

    def mark_author_status(self, openalex_author_id, person_id, status, last_error=""):
        if self.fail_on == f"status:{status}":
            raise RuntimeError(f"{status} status write failed")
        self.statuses.append((openalex_author_id, person_id, status, last_error))

    def get_local_work_ids_for_author(self, openalex_author_id, limit):
        self.local_work_requests.append((openalex_author_id, limit))
        return self.work_ids[:limit]

    def upsert_profile(self, row):
        if self.fail_on == "profile":
            raise RuntimeError("profile write failed")
        self.profiles.append(row)

    def upsert_experiences(self, rows):
        self.experiences.append(list(rows))

    def upsert_research_outputs(self, rows):
        self.research_outputs.append(list(rows))

    def upsert_funding(self, rows):
        self.funding.append(list(rows))


class FakeOpenAlexClient:
    def __init__(self, authors=None, works=None, author_work_ids=None):
        self.authors = authors or {}
        self.works = works or {}
        self.author_work_ids = author_work_ids or {}
        self.author_requests = []
        self.author_work_requests = []
        self.work_requests = []

    def get_author(self, openalex_author_id):
        self.author_requests.append(openalex_author_id)
        return self.authors.get(openalex_author_id, {})

    def get_author_work_ids(self, openalex_author_id, limit=200):
        self.author_work_requests.append((openalex_author_id, limit))
        return list(self.author_work_ids.get(openalex_author_id, []))[:limit]

    def get_work(self, openalex_work_id):
        self.work_requests.append(openalex_work_id)
        return self.works.get(openalex_work_id, {})


class FakeOrcidClient:
    def __init__(self, records=None):
        self.records = records or {}
        self.requests = []

    def get_record(self, orcid):
        self.requests.append(orcid)
        return self.records.get(orcid, {})


class FakeOrcidResolver:
    def __init__(self, result=("", {})):
        self.result = result
        self.requests = []

    def resolve(self, openalex_author, openalex_works):
        self.requests.append((openalex_author, list(openalex_works)))
        return self.result


class FakeCrossrefClient:
    def __init__(self, works=None):
        self.works = works or {}
        self.requests = []

    def get_work_by_doi(self, doi):
        self.requests.append(doi)
        return self.works.get(doi, {})


class FakeSemanticResolver:
    def __init__(self, confirmed_author=None, supplemental_papers=None):
        self.confirmed_author = confirmed_author or {}
        self.supplemental_papers = supplemental_papers or []
        self.requests = []

    def resolve(self, openalex_author, openalex_works, existing_work_ids):
        self.requests.append((openalex_author, list(openalex_works), set(existing_work_ids)))
        from src.cv_builder.semantic_scholar_resolver import SemanticScholarResolution

        return SemanticScholarResolution(self.confirmed_author, self.supplemental_papers)


def test_process_author_happy_path_writes_profile_orcid_rows_and_research_outputs_once():
    person_id = make_person_id("A123")
    author = {
        "id": "https://openalex.org/authors/A123",
        "display_name": "Ada Lovelace",
        "orcid": "https://orcid.org/0000-0001-0000-0000",
    }
    orcid_record = {
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
                                    "organization": {"name": "Example University"},
                                }
                            }
                        ]
                    }
                ]
            },
            "fundings": {
                "group": [
                    {
                        "funding-summary": [
                            {
                                "put-code": 9,
                                "title": {"title": {"value": "Research Grant"}},
                                "organization": {"name": "Science Foundation"},
                            }
                        ]
                    }
                ]
            },
        },
    }
    openalex_work = {
        "id": "https://openalex.org/works/W456",
        "title": "OpenAlex title",
        "doi": "https://doi.org/10.1234/example",
        "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
    }
    crossref_work = {
        "title": ["Crossref title"],
        "type": "journal-article",
        "container-title": ["Journal B"],
    }
    repository = FakeRepository(work_ids=["W456"])
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        works={"W456": openalex_work},
        author_work_ids={"A123": ["W456"]},
    )
    orcid_client = FakeOrcidClient(records={"0000-0001-0000-0000": orcid_record})
    crossref_client = FakeCrossrefClient(works={"https://doi.org/10.1234/example": crossref_work})

    result = CvBuildRunner(repository, openalex_client, orcid_client, crossref_client).process_author(
        "https://openalex.org/authors/A123",
        work_limit=25,
    )

    assert result == person_id
    assert repository.statuses == [
        ("A123", person_id, "processing", ""),
        ("A123", person_id, "done", ""),
    ]
    assert repository.local_work_requests == [("A123", 25)]
    assert openalex_client.author_requests == ["A123"]
    assert openalex_client.author_work_requests == [("A123", 25)]
    assert openalex_client.work_requests == ["W456"]
    assert orcid_client.requests == ["0000-0001-0000-0000"]
    assert crossref_client.requests == ["https://doi.org/10.1234/example"]
    assert len(repository.profiles) == 1
    assert repository.profiles[0]["id"] == person_id
    assert len(repository.experiences) == 1
    assert repository.experiences[0][0]["author_id"] == person_id
    assert len(repository.funding) == 1
    assert repository.funding[0][0]["author_id"] == person_id
    assert len(repository.research_outputs) == 1
    assert len(repository.research_outputs[0]) == 1
    assert repository.research_outputs[0][0]["work_title"] == "Crossref title"


def test_process_author_uses_orcid_resolver_when_openalex_has_no_orcid():
    person_id = make_person_id("A123")
    author = {"id": "A123", "display_name": "Ada Lovelace"}
    openalex_work = {
        "id": "W456",
        "title": "OpenAlex title",
        "authorships": [{"author": {"id": "A123", "display_name": "Ada Lovelace"}}],
    }
    orcid_record = {
        "orcid-identifier": {"path": "0000-0001-0000-0000"},
        "person": {"biography": {"content": "Computer pioneer."}},
    }
    repository = FakeRepository()
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        author_work_ids={"A123": ["W456"]},
        works={"W456": openalex_work},
    )
    orcid_resolver = FakeOrcidResolver(("0000-0001-0000-0000", orcid_record))
    runner = CvBuildRunner(
        repository,
        openalex_client,
        FakeOrcidClient(),
        FakeCrossrefClient(),
        orcid_resolver=orcid_resolver,
    )

    result = runner.process_author("A123")

    assert result == person_id
    assert len(orcid_resolver.requests) == 1
    assert orcid_resolver.requests[0][0] == author
    assert orcid_resolver.requests[0][1] == [openalex_work]
    assert repository.profiles[0]["orcid"] == "0000-0001-0000-0000"
    assert repository.profiles[0]["bio"] == "Computer pioneer."


def test_process_author_adds_confirmed_semantic_scholar_supplemental_work():
    person_id = make_person_id("A123")
    author = {
        "id": "A123",
        "display_name": "Ada Lovelace",
        "summary_stats": {"h_index": 42},
    }
    openalex_work = {
        "id": "W456",
        "title": "OpenAlex Paper",
        "cited_by_count": 17,
        "authorships": [{"author": {"id": "A123", "display_name": "Ada Lovelace"}}],
    }
    semantic_paper = {
        "paperId": "S2-123",
        "externalIds": {"DOI": "10.1234/s2"},
        "title": "S2 Paper",
        "year": 2023,
        "venue": "S2 Venue",
        "citationCount": 7,
        "authors": [{"name": "Ada Lovelace"}, {"name": "Grace Hopper"}],
    }
    repository = FakeRepository()
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        author_work_ids={"A123": ["W456"]},
        works={"W456": openalex_work},
    )
    semantic_resolver = FakeSemanticResolver(
        confirmed_author={"authorId": "S2A123"},
        supplemental_papers=[semantic_paper],
    )
    runner = CvBuildRunner(
        repository,
        openalex_client,
        FakeOrcidClient(),
        FakeCrossrefClient(),
        semantic_resolver=semantic_resolver,
    )

    result = runner.process_author("A123")

    assert result == person_id
    assert len(semantic_resolver.requests) == 1
    assert semantic_resolver.requests[0][0] == author
    assert semantic_resolver.requests[0][1] == [openalex_work]
    assert [row["work_title"] for row in repository.research_outputs[0]] == ["OpenAlex Paper", "S2 Paper"]
    s2_row = repository.research_outputs[0][1]
    assert s2_row["citation_count"] == 7
    assert s2_row["source"] == "semantic_scholar"


def test_process_author_uses_semantic_h_index_when_openalex_h_index_missing():
    person_id = make_person_id("A123")
    author = {"id": "A123", "display_name": "Ada Lovelace"}
    openalex_work = {
        "id": "W456",
        "title": "OpenAlex Paper",
        "authorships": [{"author": {"id": "A123", "display_name": "Ada Lovelace"}}],
    }
    repository = FakeRepository()
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        author_work_ids={"A123": ["W456"]},
        works={"W456": openalex_work},
    )
    semantic_resolver = FakeSemanticResolver(
        confirmed_author={
            "authorId": "S2A123",
            "hIndex": 19,
            "dblp_pid": "should-not-leak",
            "evidence": [{"paperId": "W456"}],
            "status": "confirmed",
        },
    )
    runner = CvBuildRunner(
        repository,
        openalex_client,
        FakeOrcidClient(),
        FakeCrossrefClient(),
        semantic_resolver=semantic_resolver,
    )

    result = runner.process_author("A123")

    assert result == person_id
    profile = repository.profiles[0]
    assert profile["h_index"] == 19
    for forbidden_key in ("semantic_author_id", "dblp_pid", "candidates", "scores", "evidence", "status"):
        assert forbidden_key not in profile


def test_process_author_prefers_openalex_h_index_over_semantic_h_index():
    author = {
        "id": "A123",
        "display_name": "Ada Lovelace",
        "summary_stats": {"h_index": 42},
    }
    openalex_work = {"id": "W456", "title": "OpenAlex Paper"}
    repository = FakeRepository()
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        author_work_ids={"A123": ["W456"]},
        works={"W456": openalex_work},
    )
    semantic_resolver = FakeSemanticResolver(confirmed_author={"authorId": "S2A123", "hIndex": 19})
    runner = CvBuildRunner(
        repository,
        openalex_client,
        FakeOrcidClient(),
        FakeCrossrefClient(),
        semantic_resolver=semantic_resolver,
    )

    runner.process_author("A123")

    assert repository.profiles[0]["h_index"] == 42


def test_process_author_already_processing_does_not_duplicate_processing_status():
    person_id = make_person_id("A123")
    repository = FakeRepository()
    openalex_client = FakeOpenAlexClient(authors={"A123": {"id": "A123", "display_name": "Ada Lovelace"}})
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    result = runner.process_author("A123", already_processing=True)

    assert result == person_id
    assert repository.statuses == [("A123", person_id, "done", "")]


def test_process_author_rejects_malformed_author_id_without_status_write_or_api_call():
    repository = FakeRepository()
    openalex_client = FakeOpenAlexClient(authors={"A123": {"id": "A123", "display_name": "Ada Lovelace"}})
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    assert runner.process_author("bad A123 text") == ""

    assert repository.statuses == []
    assert openalex_client.author_requests == []


def test_process_author_marks_missing_openalex_author_skipped_and_returns_person_id():
    person_id = make_person_id("A123")
    repository = FakeRepository(work_ids=["W456"])
    openalex_client = FakeOpenAlexClient(authors={})
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    result = runner.process_author("A123")

    assert result == person_id
    assert repository.statuses == [
        ("A123", person_id, "processing", ""),
        ("A123", person_id, "skipped", "openalex_author_not_found"),
    ]
    assert repository.profiles == []
    assert repository.experiences == []
    assert repository.funding == []
    assert repository.research_outputs == []
    assert openalex_client.work_requests == []


def test_process_author_skips_missing_work_and_still_writes_openalex_rows_without_crossref():
    repository = FakeRepository(work_ids=["W404", "W789"])
    author = {"id": "A123", "display_name": "Ada Lovelace"}
    valid_work = {"id": "W789", "title": "OpenAlex only", "doi": "10.1234/missing"}
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        works={"W404": {}, "W789": valid_work},
    )
    crossref_client = FakeCrossrefClient(works={})
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), crossref_client)

    result = runner.process_author("A123")

    assert result == make_person_id("A123")
    assert openalex_client.work_requests == ["W404", "W789"]
    assert crossref_client.requests == ["10.1234/missing"]
    assert len(repository.research_outputs) == 1
    assert len(repository.research_outputs[0]) == 1
    assert repository.research_outputs[0][0]["work_title"] == "OpenAlex only"
    assert repository.research_outputs[0][0]["source"] == "openalex"
    assert repository.statuses[-1] == ("A123", make_person_id("A123"), "done", "")


def test_process_author_uses_openalex_api_work_candidates_not_present_locally():
    repository = FakeRepository(work_ids=["W200"])
    author = {"id": "A123", "display_name": "Ada Lovelace"}
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        author_work_ids={"A123": ["W100"]},
        works={
            "W100": {"id": "W100", "title": "API work"},
            "W200": {"id": "W200", "title": "Local work"},
        },
    )
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    result = runner.process_author("A123", work_limit=10)

    assert result == make_person_id("A123")
    assert openalex_client.author_work_requests == [("A123", 10)]
    assert repository.local_work_requests == [("A123", 10)]
    assert openalex_client.work_requests == ["W100", "W200"]
    assert [row["work_title"] for row in repository.research_outputs[0]] == ["API work", "Local work"]


def test_process_author_deduplicates_openalex_api_and_local_work_candidates():
    repository = FakeRepository(work_ids=["W1", "W2"])
    author = {"id": "A123", "display_name": "Ada Lovelace"}
    openalex_client = FakeOpenAlexClient(
        authors={"A123": author},
        author_work_ids={"A123": ["W1"]},
        works={
            "W1": {"id": "W1", "title": "Shared work"},
            "W2": {"id": "W2", "title": "Local-only work"},
        },
    )
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    runner.process_author("A123", work_limit=10)

    assert openalex_client.work_requests == ["W1", "W2"]


def test_process_author_marks_invalid_profile_skipped_and_writes_no_child_rows():
    person_id = make_person_id("A123")
    repository = FakeRepository(work_ids=["W456"])
    openalex_client = FakeOpenAlexClient(authors={"A123": {"display_name": "No ID"}})
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    result = runner.process_author("A123")

    assert result == ""
    assert repository.statuses == [
        ("A123", person_id, "processing", ""),
        ("A123", person_id, "skipped", "invalid_profile"),
    ]
    assert repository.profiles == []
    assert repository.experiences == []
    assert repository.funding == []
    assert repository.research_outputs == []
    assert repository.local_work_requests == [("A123", 200)]


def test_process_author_marks_failed_with_exception_type_and_message_then_reraises():
    person_id = make_person_id("A123")
    repository = FakeRepository(fail_on="profile")
    openalex_client = FakeOpenAlexClient(authors={"A123": {"id": "A123", "display_name": "Ada Lovelace"}})
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    with pytest.raises(RuntimeError, match="profile write failed"):
        runner.process_author("A123")

    assert repository.statuses == [
        ("A123", person_id, "processing", ""),
        ("A123", person_id, "failed", "RuntimeError: profile write failed"),
    ]


def test_process_author_preserves_original_exception_when_failed_status_write_fails():
    person_id = make_person_id("A123")
    repository = FakeRepository(fail_on="status:failed")
    openalex_client = FakeOpenAlexClient(authors={"A123": {"id": "A123", "display_name": "Ada Lovelace"}})
    runner = CvBuildRunner(repository, openalex_client, FakeOrcidClient(), FakeCrossrefClient())

    def fail_upsert_profile(_row):
        raise RuntimeError("profile write failed")

    repository.upsert_profile = fail_upsert_profile

    with pytest.raises(RuntimeError, match="profile write failed"):
        runner.process_author("A123")

    assert repository.statuses == [("A123", person_id, "processing", "")]
