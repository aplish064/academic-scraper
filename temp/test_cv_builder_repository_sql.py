import pytest
from datetime import datetime

from src.cv_builder.config import CvBuilderConfig
from src.cv_builder.ids import make_person_id
from src.cv_builder.repository import CvRepository, table_name
from src.cv_builder.schema import CV_TABLES, build_create_database_sql, build_create_table_sql


def make_config(source_database="source_db", cv_database="academic_cv"):
    return CvBuilderConfig(
        clickhouse_host="clickhouse.local",
        clickhouse_port=8123,
        clickhouse_database=source_database,
        clickhouse_user="cv_user",
        clickhouse_password="secret",
        cv_database=cv_database,
        openalex_base_url="https://api.openalex.org",
        orcid_client_id="",
        orcid_client_secret="",
        orcid_base_url="https://pub.orcid.org/v3.0",
        orcid_token_url="https://orcid.org/oauth/token",
        crossref_base_url="https://api.crossref.org",
        crossref_mailto="",
        crossref_user_agent="tests",
        request_timeout=30.0,
    )


class FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class FakeClient:
    def __init__(self, query_results=None):
        self.commands = []
        self.inserts = []
        self.queries = []
        self.query_results = list(query_results or [])

    def command(self, sql):
        self.commands.append(sql)

    def insert(self, table, values, column_names=None):
        self.inserts.append(
            {
                "table": table,
                "values": values,
                "column_names": column_names,
            }
        )

    def query(self, sql, parameters=None):
        self.queries.append({"sql": sql, "parameters": parameters or {}})
        if self.query_results:
            return self.query_results.pop(0)
        return FakeResult([])


def make_repository(client, config=None):
    repository = object.__new__(CvRepository)
    repository.config = config or make_config()
    repository.client = client
    return repository


def test_schema_has_four_cv_tables_and_queue():
    assert set(CV_TABLES) == {
        "personal_profile",
        "education_work_experience",
        "research_outputs",
        "funding_info",
        "author_build_queue",
    }


def test_personal_profile_schema_contains_internal_and_source_ids():
    sql = build_create_table_sql("academic_cv", "personal_profile")
    assert "id String" in sql
    assert "openalex_id String" in sql
    assert "orcid String" in sql
    assert "semantic_author_id String" not in sql
    assert "dblp_pid String" not in sql
    assert "ReplacingMergeTree(import_time)" in sql
    assert "ORDER BY id" in sql


def test_personal_profile_schema_contains_nullable_h_index():
    sql = build_create_table_sql("academic_cv", "personal_profile")

    assert "h_index Nullable(UInt32)" in sql
    assert sql.index("email String") < sql.index("h_index Nullable(UInt32)")
    assert sql.index("h_index Nullable(UInt32)") < sql.index("source String")


def test_child_tables_have_author_id_link():
    for table in ["education_work_experience", "research_outputs", "funding_info"]:
        sql = build_create_table_sql("academic_cv", table)
        assert "author_id String" in sql
        assert "ORDER BY (author_id, id)" in sql


def test_research_outputs_schema_contains_nullable_citation_count():
    sql = build_create_table_sql("academic_cv", "research_outputs")

    assert "citation_count Nullable(UInt32)" in sql
    assert sql.index("publication_date String") < sql.index("citation_count Nullable(UInt32)")
    assert sql.index("citation_count Nullable(UInt32)") < sql.index("authors String")


def test_required_cv_columns_are_present():
    expected_columns = {
        "education_work_experience": [
            "id String",
            "author_id String",
            "role_title String",
            "institution_name String",
            "department_name String",
            "city String",
            "affiliation_type String",
            "province String",
            "date_range String",
            "country String",
            "source String",
            "source_url String",
            "import_time DateTime",
        ],
        "research_outputs": [
            "id String",
            "author_id String",
            "work_title String",
            "work_type String",
            "venue_name String",
            "publication_date String",
            "authors String",
            "source String",
            "source_url String",
            "import_time DateTime",
        ],
        "funding_info": [
            "id String",
            "author_id String",
            "end_date String",
            "award_title String",
            "city String",
            "funder_name String",
            "province String",
            "funding_type String",
            "country String",
            "start_date String",
            "source String",
            "source_url String",
            "import_time DateTime",
        ],
    }

    for table, columns in expected_columns.items():
        sql = build_create_table_sql("academic_cv", table)
        for column in columns:
            assert column in sql


def test_author_build_queue_schema():
    sql = build_create_table_sql("academic_cv", "author_build_queue")
    assert "openalex_author_id String" in sql
    assert "person_id String" in sql
    assert "status String" in sql
    assert "last_error String" in sql
    assert "retry_count UInt16" in sql
    assert "updated_at DateTime64(3)" in sql
    assert "ReplacingMergeTree(updated_at)" in sql
    assert "ORDER BY openalex_author_id" in sql


def test_create_database_sql():
    assert build_create_database_sql("academic_cv") == "CREATE DATABASE IF NOT EXISTS `academic_cv`"


def test_create_database_sql_quotes_valid_identifier():
    sql = build_create_database_sql("academic_cv")
    assert "`academic_cv`" in sql
    assert "IF NOT EXISTS academic_cv" not in sql


def test_invalid_database_rejected_for_create_database_sql():
    with pytest.raises(ValueError):
        build_create_database_sql("x; DROP DATABASE academic_db; --")


def test_invalid_database_rejected_for_create_table_sql():
    with pytest.raises(ValueError):
        build_create_table_sql("academic-cv", "personal_profile")


def test_invalid_table_identifier_rejected_for_create_table_sql():
    for table in ["bad-name", "x; DROP TABLE y; --", "1bad"]:
        with pytest.raises(ValueError):
            build_create_table_sql("academic_cv", table)


def test_table_name_quotes_valid_qualified_name():
    assert table_name("academic_cv", "personal_profile") == "`academic_cv`.`personal_profile`"


def test_table_name_rejects_invalid_identifiers():
    for database, table in [
        ("academic-cv", "personal_profile"),
        ("academic_cv", "bad-name"),
        ("academic_cv", "x; DROP TABLE y; --"),
        ("1bad", "personal_profile"),
    ]:
        with pytest.raises(ValueError):
            table_name(database, table)


def test_repository_connects_with_clickhouse_config(monkeypatch):
    captured = {}

    def fake_get_client(**kwargs):
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setattr("src.cv_builder.repository.clickhouse_connect.get_client", fake_get_client)
    config = make_config(source_database="academic_source", cv_database="cv_target")

    repository = CvRepository(config)

    assert isinstance(repository.client, FakeClient)
    assert captured == {
        "host": "clickhouse.local",
        "port": 8123,
        "username": "cv_user",
        "password": "secret",
        "database": "academic_source",
    }


def test_init_schema_creates_cv_database_and_all_tables():
    client = FakeClient()
    repository = make_repository(client, make_config(cv_database="cv_target"))

    repository.init_schema()

    assert len(client.commands) == 1 + len(CV_TABLES)
    assert client.commands[0] == "CREATE DATABASE IF NOT EXISTS `cv_target`"
    for table in CV_TABLES:
        assert build_create_table_sql("cv_target", table) in client.commands


def test_insert_rows_uses_schema_column_order_and_fills_missing_values():
    client = FakeClient()
    repository = make_repository(client)
    import_time = "2026-06-14 12:34:56"

    repository.insert_rows(
        "personal_profile",
        [
            {
                "name": "Ada Lovelace",
                "id": "person_1",
                "openalex_id": "A123",
                "unknown": "ignored",
                "import_time": import_time,
            }
        ],
    )

    insert = client.inserts[0]
    expected_columns = [column for column, _ in CV_TABLES["personal_profile"]["columns"]]
    assert insert["table"] == "`academic_cv`.`personal_profile`"
    assert insert["column_names"] == expected_columns
    assert insert["values"] == [
        [
            "person_1",
            "A123",
            "",
            "Ada Lovelace",
            "",
            "",
            "",
            None,
            "",
            "",
            import_time,
        ]
    ]


def test_insert_rows_uses_type_correct_defaults_for_missing_typed_columns():
    client = FakeClient()
    repository = make_repository(client)

    repository.insert_rows(
        "author_build_queue",
        [{"openalex_author_id": "A123", "person_id": "person_123", "status": "pending"}],
    )

    row = client.inserts[0]["values"][0]
    assert row[:5] == ["A123", "person_123", "pending", "", 0]
    assert isinstance(row[5], datetime)


def test_insert_rows_noops_for_empty_rows():
    client = FakeClient()
    repository = make_repository(client)

    repository.insert_rows("personal_profile", [])

    assert client.inserts == []


def test_insert_rows_rejects_unknown_table():
    repository = make_repository(FakeClient())

    with pytest.raises(ValueError):
        repository.insert_rows("not_a_table", [{"id": "x"}])


def test_get_local_work_ids_queries_config_source_database_and_normalizes_author_id():
    client = FakeClient([FakeResult([("https://openalex.org/W1",), ("W-1",), ("W2",), ("W2",)])])
    repository = make_repository(client, make_config(source_database="custom_source"))

    work_ids = repository.get_local_work_ids_for_author("https://openalex.org/A123456789", limit=17)

    assert work_ids == ["W1", "W2"]
    query = client.queries[0]
    assert "FROM `custom_source`.`OpenAlex`" in query["sql"]
    assert "academic_db.OpenAlex" not in query["sql"]
    assert query["parameters"] == {
        "author_ids": [
            "A123456789",
            "123456789",
            "123456789.0",
            "https://openalex.org/A123456789",
        ],
        "limit": 17,
    }
    assert "uid != ''" in query["sql"]
    assert "author_id != ''" in query["sql"]
    assert "author_id IN {author_ids:Array(String)}" in query["sql"]
    assert "ORDER BY uid" in query["sql"]


def test_enqueue_authors_from_openalex_uses_source_database_and_sets_person_id():
    client = FakeClient(
        [
            FakeResult(
                [
                    ("A123",),
                    ("5000000003",),
                    ("5000000004.0",),
                    ("",),
                    ("nan",),
                    ("None",),
                    ("https://openalex.org/A456",),
                ]
            ),
            FakeResult([]),
        ]
    )
    repository = make_repository(client, make_config(source_database="seed_db"))

    inserted_count = repository.enqueue_authors_from_openalex(limit=50)

    assert inserted_count == 4
    query = client.queries[0]
    assert "FROM `seed_db`.`OpenAlex`" in query["sql"]
    assert "ORDER BY author_id" in query["sql"]
    assert query["parameters"] == {"limit": 50}
    existing_query = client.queries[1]
    assert "FROM `academic_cv`.`author_build_queue` FINAL" in existing_query["sql"]
    assert existing_query["parameters"] == {"author_ids": ["A123", "A456", "A5000000003", "A5000000004"]}
    insert = client.inserts[0]
    assert insert["table"] == "`academic_cv`.`author_build_queue`"
    assert insert["column_names"] == [column for column, _ in CV_TABLES["author_build_queue"]["columns"]]
    assert insert["values"][0][:5] == ["A123", make_person_id("A123"), "pending", "", 0]
    assert insert["values"][1][:5] == [
        "A5000000003",
        make_person_id("A5000000003"),
        "pending",
        "",
        0,
    ]
    assert insert["values"][2][:5] == [
        "A5000000004",
        make_person_id("A5000000004"),
        "pending",
        "",
        0,
    ]
    assert insert["values"][3][:5] == [
        "A456",
        make_person_id("A456"),
        "pending",
        "",
        0,
    ]


def test_enqueue_authors_from_openalex_does_not_reset_existing_queue_rows():
    client = FakeClient(
        [
            FakeResult([("A123",), ("A456",)]),
            FakeResult([("A123",)]),
        ]
    )
    repository = make_repository(client)

    inserted_count = repository.enqueue_authors_from_openalex(limit=2)

    assert inserted_count == 1
    assert client.inserts[0]["values"][0][:5] == ["A456", make_person_id("A456"), "pending", "", 0]


def test_next_pending_author_returns_empty_string_when_queue_is_empty():
    client = FakeClient([FakeResult([])])
    repository = make_repository(client)

    assert repository.next_pending_author() == ""
    assert "FROM `academic_cv`.`author_build_queue` FINAL" in client.queries[0]["sql"]
    assert "status = 'pending'" in client.queries[0]["sql"]
    assert client.inserts == []


def test_next_pending_author_claims_selected_author_as_processing():
    client = FakeClient([FakeResult([("A123", make_person_id("A123"), 2)])])
    repository = make_repository(client)

    assert repository.next_pending_author() == "A123"

    assert "ORDER BY updated_at, openalex_author_id" in client.queries[0]["sql"]
    insert = client.inserts[0]
    assert insert["values"][0][:5] == ["A123", make_person_id("A123"), "processing", "", 2]


def test_mark_author_status_inserts_queue_row_with_known_columns():
    client = FakeClient([FakeResult([(2,)])])
    repository = make_repository(client)

    repository.mark_author_status("A123", "person_123", "failed", "boom")

    assert client.queries[0]["parameters"] == {"author_id": "A123"}
    insert = client.inserts[0]
    assert insert["table"] == "`academic_cv`.`author_build_queue`"
    assert insert["column_names"] == [column for column, _ in CV_TABLES["author_build_queue"]["columns"]]
    assert insert["values"][0][:5] == ["A123", "person_123", "failed", "boom", 3]


def test_mark_author_status_rejects_invalid_author_id_without_insert():
    client = FakeClient()
    repository = make_repository(client)

    with pytest.raises(ValueError):
        repository.mark_author_status("bad-author", "person_bad", "failed")

    assert client.inserts == []


def test_mark_author_status_rejects_malformed_embedded_author_id_without_insert():
    client = FakeClient()
    repository = make_repository(client)

    with pytest.raises(ValueError):
        repository.mark_author_status("bad A123 text", "person_bad", "failed")

    assert client.inserts == []


def test_mark_author_status_rejects_invalid_status_without_insert():
    client = FakeClient()
    repository = make_repository(client)

    with pytest.raises(ValueError):
        repository.mark_author_status("A123", "person_123", "complete")

    assert client.inserts == []
