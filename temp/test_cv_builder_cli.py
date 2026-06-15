from dataclasses import dataclass

import pytest


@dataclass
class FakeConfig:
    cv_database: str = "academic_cv_test"


class FakeRepository:
    instances = []
    pending_authors = []
    queued_count = 0

    def __init__(self, config):
        self.config = config
        self.init_schema_calls = 0
        self.enqueue_limits = []
        self.next_pending_calls = 0
        FakeRepository.instances.append(self)

    def init_schema(self):
        self.init_schema_calls += 1

    def enqueue_authors_from_openalex(self, limit):
        self.enqueue_limits.append(limit)
        return self.queued_count

    def next_pending_author(self):
        self.next_pending_calls += 1
        if not self.pending_authors:
            return ""
        return self.pending_authors.pop(0)


class FakeRunner:
    instances = []
    fail_on_author = ""

    def __init__(
        self,
        repository,
        openalex_client,
        orcid_client,
        crossref_client,
        orcid_resolver=None,
        semantic_resolver=None,
    ):
        self.repository = repository
        self.openalex_client = openalex_client
        self.orcid_client = orcid_client
        self.crossref_client = crossref_client
        self.orcid_resolver = orcid_resolver
        self.semantic_resolver = semantic_resolver
        self.process_calls = []
        FakeRunner.instances.append(self)

    def process_author(self, author_id, work_limit=200, already_processing=False):
        if author_id == self.fail_on_author:
            raise RuntimeError(f"failed {author_id}")
        self.process_calls.append(
            {
                "author_id": author_id,
                "work_limit": work_limit,
                "already_processing": already_processing,
            }
        )
        return f"person-{author_id}"


class FakeClient:
    instances = []

    def __init__(self, config):
        self.config = config
        FakeClient.instances.append(self)


@pytest.fixture()
def cli(monkeypatch):
    import src.cv_builder.cli as cli_module

    FakeRepository.instances = []
    FakeRepository.pending_authors = []
    FakeRepository.queued_count = 0
    FakeRunner.instances = []
    FakeRunner.fail_on_author = ""
    FakeClient.instances = []

    monkeypatch.setattr(cli_module, "get_config", lambda: FakeConfig())
    monkeypatch.setattr(cli_module, "CvRepository", FakeRepository)
    monkeypatch.setattr(cli_module, "CvBuildRunner", FakeRunner)
    monkeypatch.setattr(cli_module, "OpenAlexClient", FakeClient)
    monkeypatch.setattr(cli_module, "OrcidClient", FakeClient)
    monkeypatch.setattr(cli_module, "CrossrefClient", FakeClient)
    monkeypatch.setattr(cli_module, "SemanticScholarClient", FakeClient)
    return cli_module


def test_init_schema_initializes_configured_database(cli, capsys):
    assert cli.main(["init-schema"]) == 0

    assert FakeRepository.instances[0].init_schema_calls == 1
    assert capsys.readouterr().out == "initialized academic_cv_test\n"


def test_init_queue_initializes_schema_and_queues_limited_authors(cli, capsys):
    FakeRepository.queued_count = 7

    assert cli.main(["init-queue", "--limit", "25"]) == 0

    repository = FakeRepository.instances[0]
    assert repository.init_schema_calls == 1
    assert repository.enqueue_limits == [25]
    assert capsys.readouterr().out == "queued 7 authors\n"


def test_process_author_builds_runner_and_processes_explicit_author(cli, capsys):
    assert cli.main(["process-author", "A123", "--work-limit", "11"]) == 0

    assert FakeRunner.instances[0].process_calls == [
        {"author_id": "A123", "work_limit": 11, "already_processing": False}
    ]
    assert len(FakeClient.instances) == 4
    assert FakeRunner.instances[0].orcid_resolver is not None
    assert FakeRunner.instances[0].semantic_resolver is not None
    assert capsys.readouterr().out == "processed A123 -> person-A123\n"


def test_process_next_prints_no_pending_authors_without_runner_work(cli, capsys):
    assert cli.main(["process-next"]) == 0

    assert FakeRepository.instances[0].next_pending_calls == 1
    assert FakeRunner.instances[0].process_calls == []
    assert capsys.readouterr().out == "no pending authors\n"


def test_process_next_count_processes_until_count_with_already_processing(cli, capsys):
    FakeRepository.pending_authors = ["A101", "A102", "A103"]

    assert cli.main(["process-next", "--work-limit", "5", "--count", "2"]) == 0

    assert FakeRepository.instances[0].next_pending_calls == 2
    assert FakeRunner.instances[0].process_calls == [
        {"author_id": "A101", "work_limit": 5, "already_processing": True},
        {"author_id": "A102", "work_limit": 5, "already_processing": True},
    ]
    assert capsys.readouterr().out == (
        "processed A101 -> person-A101\n"
        "processed A102 -> person-A102\n"
        "processed_count 2\n"
    )


def test_process_next_count_stops_when_queue_exhausted(cli, capsys):
    FakeRepository.pending_authors = ["A101"]

    assert cli.main(["process-next", "--work-limit", "5", "--count", "3"]) == 0

    assert FakeRepository.instances[0].next_pending_calls == 2
    assert FakeRunner.instances[0].process_calls == [
        {"author_id": "A101", "work_limit": 5, "already_processing": True},
    ]
    assert capsys.readouterr().out == "processed A101 -> person-A101\nprocessed_count 1\n"


def test_process_next_rejects_non_positive_count_before_repository_work(cli):
    with pytest.raises(SystemExit):
        cli.main(["process-next", "--count", "0"])

    assert FakeRepository.instances == []


def test_process_next_rejects_non_positive_work_limit_before_repository_work(cli):
    with pytest.raises(SystemExit):
        cli.main(["process-next", "--work-limit", "-1"])

    assert FakeRepository.instances == []


def test_init_queue_rejects_non_positive_limit_before_repository_work(cli):
    with pytest.raises(SystemExit):
        cli.main(["init-queue", "--limit", "0"])

    assert FakeRepository.instances == []


def test_process_next_propagates_runner_exception_and_stops(cli):
    FakeRepository.pending_authors = ["A101", "A102"]
    FakeRunner.fail_on_author = "A101"

    with pytest.raises(RuntimeError, match="failed A101"):
        cli.main(["process-next", "--count", "2"])

    assert FakeRepository.instances[0].next_pending_calls == 1
    assert FakeRepository.pending_authors == ["A102"]
