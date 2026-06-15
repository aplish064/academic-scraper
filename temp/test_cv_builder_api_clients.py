from src.cv_builder.config import CvBuilderConfig
from src.cv_builder.crossref_client import CrossrefClient
from src.cv_builder.openalex_client import OpenAlexClient
from src.cv_builder.orcid_client import OrcidClient
from src.cv_builder.semantic_scholar_client import SemanticScholarClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_calls = []
        self.post_calls = []
        self.get_responses = list(get_responses or [FakeResponse(payload={})])
        self.post_responses = list(post_responses or [FakeResponse(payload={})])

    def get(self, *args, **kwargs):
        self.get_calls.append((args, kwargs))
        return self.get_responses.pop(0)

    def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        return self.post_responses.pop(0)


def make_config(**overrides):
    values = {
        "clickhouse_host": "localhost",
        "clickhouse_port": 8123,
        "clickhouse_database": "academic_db",
        "clickhouse_user": "default",
        "clickhouse_password": "",
        "cv_database": "academic_cv",
        "openalex_base_url": "https://api.openalex.org",
        "orcid_client_id": "client-id",
        "orcid_client_secret": "client-secret",
        "orcid_base_url": "https://pub.orcid.org/v3.0",
        "orcid_token_url": "https://orcid.org/oauth/token",
        "crossref_base_url": "https://api.crossref.org",
        "crossref_mailto": "",
        "crossref_user_agent": "Top-Talent-Academic/1.0",
        "semantic_base_url": "https://api.semanticscholar.org/graph/v1",
        "semantic_api_key": "",
        "request_timeout": 5.0,
    }
    values.update(overrides)
    return CvBuilderConfig(**values)


def test_openalex_client_validates_author_ids_before_request():
    client = OpenAlexClient(make_config())
    session = FakeSession()
    client.session = session

    try:
        client.get_author("A123?select=id")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected invalid OpenAlex author URL to raise ValueError")

    assert session.get_calls == []


def test_openalex_client_accepts_canonical_author_url():
    client = OpenAlexClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(payload={"id": "https://openalex.org/A123"})])
    client.session = session

    assert client.get_author("https://openalex.org/A123") == {"id": "https://openalex.org/A123"}

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.openalex.org/authors/A123"
    assert kwargs["timeout"] == 5.0


def test_openalex_client_returns_empty_for_missing_author():
    client = OpenAlexClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(status_code=404, payload={})])
    client.session = session

    assert client.get_author("A123") == {}


def test_openalex_client_returns_empty_for_missing_work():
    client = OpenAlexClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(status_code=404, payload={})])
    client.session = session

    assert client.get_work("W123") == {}


def test_openalex_client_lists_author_work_ids_with_cursor_pagination():
    client = OpenAlexClient(make_config())
    session = FakeSession(
        get_responses=[
            FakeResponse(
                payload={
                    "results": [
                        {"id": "https://openalex.org/W1"},
                        {"id": "https://openalex.org/W-1"},
                    ],
                    "meta": {"next_cursor": "cursor-2"},
                }
            ),
            FakeResponse(
                payload={
                    "results": [
                        {"id": "https://openalex.org/W2"},
                        {"id": "https://openalex.org/W1"},
                    ],
                    "meta": {"next_cursor": None},
                }
            ),
        ]
    )
    client.session = session

    assert client.get_author_work_ids("https://openalex.org/A123", limit=10) == ["W1", "W2"]

    first_args, first_kwargs = session.get_calls[0]
    second_args, second_kwargs = session.get_calls[1]
    assert first_args[0] == "https://api.openalex.org/works"
    assert first_kwargs["params"] == {
        "filter": "authorships.author.id:A123",
        "select": "id",
        "per-page": 10,
        "cursor": "*",
    }
    assert second_args[0] == "https://api.openalex.org/works"
    assert second_kwargs["params"] == {
        "filter": "authorships.author.id:A123",
        "select": "id",
        "per-page": 9,
        "cursor": "cursor-2",
    }


def test_openalex_client_author_work_ids_honors_limit_without_extra_page():
    client = OpenAlexClient(make_config())
    session = FakeSession(
        get_responses=[
            FakeResponse(
                payload={
                    "results": [{"id": "https://openalex.org/W1"}],
                    "meta": {"next_cursor": "cursor-2"},
                }
            )
        ]
    )
    client.session = session

    assert client.get_author_work_ids("A123", limit=1) == ["W1"]
    assert len(session.get_calls) == 1
    assert session.get_calls[0][1]["params"]["per-page"] == 1


def test_openalex_client_validates_author_work_id_author_before_request():
    client = OpenAlexClient(make_config())
    session = FakeSession()
    client.session = session

    try:
        client.get_author_work_ids("bad A123 text")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected invalid OpenAlex author ID to raise ValueError")

    assert session.get_calls == []


def test_crossref_client_encodes_reserved_doi_characters_and_omits_blank_mailto():
    client = CrossrefClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(payload={"message": {"DOI": "10.1234/a?b#c"}})])
    client.session = session

    assert client.get_work_by_doi("10.1234/a?b#c") == {"DOI": "10.1234/a?b#c"}

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.crossref.org/works/10.1234/a%3Fb%23c"
    assert kwargs["params"] == {}
    assert kwargs["headers"]["User-Agent"] == "Top-Talent-Academic/1.0"


def test_crossref_client_normalizes_common_doi_forms():
    client = CrossrefClient(make_config())
    session = FakeSession(
        get_responses=[
            FakeResponse(payload={"message": {"DOI": "10.1234/example"}}),
            FakeResponse(payload={"message": {"DOI": "10.5678/example"}}),
            FakeResponse(payload={"message": {"DOI": "10.9999/example"}}),
        ]
    )
    client.session = session

    assert client.get_work_by_doi("https://doi.org/10.1234/example") == {"DOI": "10.1234/example"}
    assert client.get_work_by_doi("https://dx.doi.org/10.5678/example") == {"DOI": "10.5678/example"}
    assert client.get_work_by_doi("doi:10.9999/example") == {"DOI": "10.9999/example"}

    assert session.get_calls[0][0][0] == "https://api.crossref.org/works/10.1234/example"
    assert session.get_calls[1][0][0] == "https://api.crossref.org/works/10.5678/example"
    assert session.get_calls[2][0][0] == "https://api.crossref.org/works/10.9999/example"


def test_crossref_client_decodes_percent_encoded_doi_prefix_input_before_request():
    client = CrossrefClient(make_config())
    session = FakeSession(
        get_responses=[
            FakeResponse(payload={"message": {"DOI": "10.1234/a?b#c"}}),
            FakeResponse(payload={"message": {"DOI": "10.1234/a?b#c"}}),
        ]
    )
    client.session = session

    assert client.get_work_by_doi("doi:10.1234/a%3Fb%23c") == {"DOI": "10.1234/a?b#c"}
    assert client.get_work_by_doi("10.1234/a%3Fb%23c") == {"DOI": "10.1234/a?b#c"}

    assert session.get_calls[0][0][0] == "https://api.crossref.org/works/10.1234/a%3Fb%23c"
    assert session.get_calls[1][0][0] == "https://api.crossref.org/works/10.1234/a%3Fb%23c"


def test_crossref_client_returns_empty_for_invalid_doi_without_http():
    client = CrossrefClient(make_config())
    session = FakeSession()
    client.session = session

    assert client.get_work_by_doi("not a doi") == {}
    assert session.get_calls == []


def test_crossref_client_rejects_malformed_doi_prefix_without_http():
    client = CrossrefClient(make_config())
    session = FakeSession()
    client.session = session

    assert client.get_work_by_doi("10.foo/example") == {}
    assert session.get_calls == []


def test_crossref_client_adds_mailto_when_configured():
    client = CrossrefClient(make_config(crossref_mailto="owner@example.com"))
    session = FakeSession(get_responses=[FakeResponse(payload={"message": {}})])
    client.session = session

    client.get_work_by_doi("10.1234/example")

    _, kwargs = session.get_calls[0]
    assert kwargs["params"] == {"mailto": "owner@example.com"}
    assert kwargs["headers"]["User-Agent"].endswith("(mailto:owner@example.com)")


def test_semantic_scholar_client_gets_paper_by_doi_with_api_key():
    client = SemanticScholarClient(make_config(semantic_api_key="key-123"))
    session = FakeSession(get_responses=[FakeResponse(payload={"paperId": "S2P1"})])
    client.session = session

    assert client.get_paper_by_doi("10.1234/example") == {"paperId": "S2P1"}

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234%2Fexample"
    assert kwargs["headers"]["x-api-key"] == "key-123"
    assert "authors" in kwargs["params"]["fields"]


def test_semantic_scholar_client_searches_papers_by_title():
    client = SemanticScholarClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(payload={"data": [{"paperId": "S2P1"}]})])
    client.session = session

    assert client.search_papers_by_title("Reliable Paper") == [{"paperId": "S2P1"}]

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.semanticscholar.org/graph/v1/paper/search"
    assert kwargs["params"]["query"] == "Reliable Paper"
    assert kwargs["params"]["limit"] == 5


def test_semantic_scholar_client_gets_author_with_papers():
    client = SemanticScholarClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(payload={"authorId": "S2A1", "papers": []})])
    client.session = session

    assert client.get_author("S2A1") == {"authorId": "S2A1", "papers": []}

    args, kwargs = session.get_calls[0]
    assert args[0] == "https://api.semanticscholar.org/graph/v1/author/S2A1"
    fields = kwargs["params"]["fields"].split(",")
    assert "hIndex" in fields
    assert "aliases" not in fields
    assert "authorId" in fields
    assert "externalIds" in fields
    assert "affiliations" in fields


def test_semantic_scholar_client_returns_empty_for_blank_inputs_without_http():
    client = SemanticScholarClient(make_config())
    session = FakeSession()
    client.session = session

    assert client.get_paper_by_doi(" ") == {}
    assert client.search_papers_by_title("") == []
    assert client.get_author(" ") == {}
    assert session.get_calls == []


def test_semantic_scholar_client_returns_empty_for_missing_paper():
    client = SemanticScholarClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(status_code=404, payload={})])
    client.session = session

    assert client.get_paper_by_doi("10.1234/missing") == {}


def test_semantic_scholar_client_returns_empty_for_missing_author():
    client = SemanticScholarClient(make_config())
    session = FakeSession(get_responses=[FakeResponse(status_code=404, payload={})])
    client.session = session

    assert client.get_author("S2A404") == {}


def test_orcid_client_returns_empty_for_invalid_orcid_without_http():
    client = OrcidClient(make_config())
    session = FakeSession()
    client.session = session

    assert client.get_record("not-an-orcid") == {}
    assert session.post_calls == []
    assert session.get_calls == []


def test_orcid_client_refreshes_token_once_after_unauthorized():
    client = OrcidClient(make_config())
    session = FakeSession(
        post_responses=[
            FakeResponse(payload={"access_token": "old-token", "expires_in": 3600}),
            FakeResponse(payload={"access_token": "new-token", "expires_in": 3600}),
        ],
        get_responses=[
            FakeResponse(status_code=401, payload={}),
            FakeResponse(payload={"orcid-identifier": {"path": "0000-0002-1825-0097"}}),
        ],
    )
    client.session = session

    assert client.get_record("https://orcid.org/0000-0002-1825-0097") == {
        "orcid-identifier": {"path": "0000-0002-1825-0097"}
    }

    assert len(session.post_calls) == 2
    assert len(session.get_calls) == 2
    first_auth = session.get_calls[0][1]["headers"]["Authorization"]
    second_auth = session.get_calls[1][1]["headers"]["Authorization"]
    assert first_auth == "Bearer old-token"
    assert second_auth == "Bearer new-token"


def test_orcid_client_returns_empty_for_missing_record():
    client = OrcidClient(make_config())
    session = FakeSession(
        post_responses=[FakeResponse(payload={"access_token": "token", "expires_in": 3600})],
        get_responses=[FakeResponse(status_code=404, payload={})],
    )
    client.session = session

    assert client.get_record("0000-0002-1825-0097") == {}
