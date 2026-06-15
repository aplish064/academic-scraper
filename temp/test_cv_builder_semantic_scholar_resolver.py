from src.cv_builder.semantic_scholar_resolver import SemanticScholarResolver


class FakeSemanticClient:
    def __init__(self, doi_papers=None, title_papers=None, authors=None):
        self.doi_papers = doi_papers or {}
        self.title_papers = title_papers or {}
        self.authors = authors or {}
        self.doi_calls = []
        self.title_calls = []
        self.author_calls = []

    def get_paper_by_doi(self, doi):
        self.doi_calls.append(doi)
        return self.doi_papers.get(doi.lower(), {})

    def search_papers_by_title(self, title):
        self.title_calls.append(title)
        return self.title_papers.get(title, [])

    def get_author(self, author_id):
        self.author_calls.append(author_id)
        return self.authors.get(author_id, {})


def s2_paper(paper_id, title, year, doi="", authors=None):
    external_ids = {}
    if doi:
        external_ids["DOI"] = doi
    return {
        "paperId": paper_id,
        "title": title,
        "year": year,
        "externalIds": external_ids,
        "authors": authors or [],
    }


def s2_author(author_id, name):
    return {"authorId": author_id, "name": name}


def openalex_work(doi="", title="Reliable Paper", year=2024, authorships=None):
    work = {
        "display_name": title,
        "publication_year": year,
        "authorships": authorships or [],
    }
    if doi:
        work["doi"] = doi
    return work


def openalex_authorship(author_id, name):
    return {"author": {"id": author_id, "display_name": name}}


def test_semantic_resolver_rejects_without_work_evidence():
    client = FakeSemanticClient(
        authors={
            "S2A1": {
                "authorId": "S2A1",
                "hIndex": 7,
                "papers": [s2_paper("S2P1", "Name Only Paper", 2024)],
            }
        }
    )

    result = SemanticScholarResolver(client).resolve(
        {"id": "A1", "display_name": "Ada Lovelace"}, [], set()
    )

    assert result.confirmed_author == {}
    assert result.supplemental_papers == []
    assert client.author_calls == []


def test_semantic_resolver_confirms_author_from_two_doi_matches_and_adds_new_paper():
    paper_one = s2_paper(
        "S2P1",
        "Reliable Systems Paper One",
        2021,
        "10.1234/one",
        [s2_author("S2A1", "Ada Lovelace")],
    )
    paper_two = s2_paper(
        "S2P2",
        "Reliable Systems Paper Two",
        2022,
        "10.1234/two",
        [s2_author("S2A1", "A. Lovelace")],
    )
    supplemental = s2_paper(
        "S2P3",
        "New Supplemental Paper",
        2023,
        "10.1234/new",
        [s2_author("S2A1", "Ada Lovelace")],
    )
    confirmed_author = {
        "authorId": "S2A1",
        "hIndex": 11,
        "papers": [paper_one, supplemental],
    }
    client = FakeSemanticClient(
        doi_papers={"10.1234/one": paper_one, "10.1234/two": paper_two},
        authors={"S2A1": confirmed_author},
    )
    works = [
        openalex_work("10.1234/one", "Reliable Systems Paper One", 2021),
        openalex_work("https://doi.org/10.1234/two", "Reliable Systems Paper Two", 2022),
    ]

    result = SemanticScholarResolver(client).resolve(
        {"id": "https://openalex.org/A1", "display_name": "Ada Lovelace"},
        works,
        {"doi:10.1234/one"},
    )

    assert result.confirmed_author["authorId"] == "S2A1"
    assert result.confirmed_author["hIndex"] == 11
    assert result.supplemental_papers == [supplemental]


def test_semantic_resolver_rejects_name_only_without_paper_match():
    client = FakeSemanticClient(
        title_papers={
            "Unmatched OpenAlex Paper": [
                s2_paper(
                    "S2P1",
                    "Different Semantic Scholar Paper",
                    2024,
                    "",
                    [s2_author("S2A1", "Ada Lovelace")],
                )
            ]
        },
        authors={"S2A1": {"authorId": "S2A1", "hIndex": 5, "papers": []}},
    )
    works = [openalex_work("", "Unmatched OpenAlex Paper", 2024)]

    result = SemanticScholarResolver(client).resolve(
        {"id": "A1", "display_name": "Ada Lovelace"}, works, set()
    )

    assert result.confirmed_author == {}
    assert result.supplemental_papers == []
    assert client.author_calls == []


def test_semantic_resolver_does_not_confirm_coauthor_on_shared_paper():
    shared_paper = s2_paper(
        "S2P1",
        "Shared Computing History Paper",
        1952,
        "10.5555/shared",
        [
            s2_author("S2A2", "Grace Hopper"),
            s2_author("S2A1", "A. Lovelace"),
        ],
    )
    client = FakeSemanticClient(
        doi_papers={"10.5555/shared": shared_paper},
        authors={
            "S2A2": {"authorId": "S2A2", "hIndex": 8, "papers": [shared_paper]},
            "S2A1": {"authorId": "S2A1", "hIndex": 9, "papers": [shared_paper]},
        },
    )
    works = [
        openalex_work(
            "10.5555/shared",
            "Shared Computing History Paper",
            1952,
            [
                openalex_authorship("https://openalex.org/A1", "Ada Byron"),
                openalex_authorship("https://openalex.org/A2", "Grace Hopper"),
            ],
        )
    ]

    result = SemanticScholarResolver(client).resolve(
        {"id": "https://openalex.org/A1", "display_name": "Ada Byron"},
        works,
        set(),
    )

    assert result.confirmed_author == {}
    assert result.supplemental_papers == []
    assert client.author_calls == []


def test_semantic_resolver_deduplicates_existing_doi_work():
    matched_paper = s2_paper(
        "S2P1",
        "Reliable Existing Work",
        2020,
        "10.9999/existing",
        [s2_author("S2A1", "Ada Lovelace")],
    )
    duplicate_paper = s2_paper(
        "S2P2",
        "Existing DOI From Author Record",
        2020,
        "https://doi.org/10.9999/existing",
        [s2_author("S2A1", "Ada Lovelace")],
    )
    new_paper = s2_paper(
        "S2P3",
        "Distinct Semantic Scholar Work",
        2024,
        "10.9999/new",
        [s2_author("S2A1", "Ada Lovelace")],
    )
    client = FakeSemanticClient(
        doi_papers={"10.9999/existing": matched_paper},
        authors={
            "S2A1": {
                "authorId": "S2A1",
                "hIndex": 6,
                "papers": [duplicate_paper, new_paper],
            }
        },
    )
    works = [openalex_work("10.9999/existing", "Reliable Existing Work", 2020)]

    result = SemanticScholarResolver(client).resolve(
        {"id": "A1", "display_name": "Ada Lovelace"},
        works,
        {"s2:S2P2"},
    )

    assert result.confirmed_author["authorId"] == "S2A1"
    assert result.supplemental_papers == [new_paper]
