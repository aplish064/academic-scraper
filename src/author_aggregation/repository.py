from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from . import schema
from .models import AuthorEntity, AuthorIdentityEdge, AuthorObservation, IngestState, PaperIdentityEdge


SOURCE_CONFIG: Dict[str, tuple] = {
    "openalex": ("academic_db.OpenAlex", "import_time"),
    "semantic": ("academic_db.semantic", "import_time"),
    "arxiv": ("academic_db.arxiv", "updated"),
    "dblp": ("academic_db.dblp", "created_at"),
}

SOURCE_WATERMARK_INDEXES: Dict[str, str] = {
    source: f"idx_author_aggregation_{source}_watermark" for source in SOURCE_CONFIG
}


OBSERVATION_COLUMNS = [
    "observation_id",
    "source",
    "source_row_key",
    "source_paper_id",
    "source_author_id",
    "author_name",
    "normalized_author_name",
    "author_rank",
    "author_role",
    "doi",
    "arxiv_id",
    "dblp_key",
    "semantic_id",
    "openalex_id",
    "title",
    "normalized_title",
    "publication_date",
    "publication_year",
    "venue",
    "institution_id",
    "institution_name",
    "institution_country",
    "raw_affiliation",
    "citation_count",
    "fwci",
    "primary_topic",
    "ccf_class",
    "source_import_time",
    "observed_at",
    "pipeline_run_id",
]

PAPER_EDGE_COLUMNS = [
    "edge_id",
    "left_source",
    "left_source_paper_id",
    "right_source",
    "right_source_paper_id",
    "match_type",
    "confidence",
    "evidence",
    "created_at",
    "pipeline_run_id",
]

AUTHOR_EDGE_COLUMNS = [
    "edge_id",
    "left_observation_id",
    "right_observation_id",
    "left_source",
    "right_source",
    "match_type",
    "paper_edge_id",
    "confidence",
    "evidence",
    "created_at",
    "pipeline_run_id",
]

ENTITY_COLUMNS = [
    "author_entity_id",
    "canonical_name",
    "normalized_canonical_name",
    "source_count",
    "observation_count",
    "paper_count",
    "source_author_ids",
    "sources",
    "first_publication_year",
    "last_publication_year",
    "primary_institution_name",
    "primary_country",
    "created_at",
    "updated_at",
    "pipeline_run_id",
]


def create_clickhouse_client():
    import clickhouse_connect

    return clickhouse_connect.get_client(
        host="localhost",
        port=8123,
        username="default",
        password="",
    )


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


# Keep fallback > UTC epoch even after timezone conversion.
EPOCH_WATERMARK = datetime(1970, 1, 2, 0, 0, 0)


def sql_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def build_source_extract_sql(
    source: str,
    last_watermark: datetime,
    limit: Optional[int],
    overlap_days: int,
    window_end: Optional[datetime] = None,
) -> str:
    table, watermark_expr = SOURCE_CONFIG[source]
    effective_watermark = last_watermark - timedelta(days=overlap_days if source == "arxiv" else 0)
    window_end_clause = ""
    if window_end is not None:
        window_end_clause = f"AND {watermark_expr} < toDateTime('{format_datetime(window_end)}') "
    limit_clause = f" LIMIT {int(limit)}" if limit else ""
    return (
        f"SELECT * FROM {table} "
        f"WHERE {watermark_expr} >= toDateTime('{format_datetime(effective_watermark)}') "
        f"{window_end_clause}"
        f"{limit_clause}"
    )


def build_observation_insert_sql(temp_table: str) -> str:
    columns = ", ".join(OBSERVATION_COLUMNS)
    select_columns = ", ".join(f"tmp.{column}" for column in OBSERVATION_COLUMNS)
    return f"""
INSERT INTO authors_db.author_observations ({columns})
SELECT {select_columns}
FROM {temp_table} tmp
LEFT ANTI JOIN authors_db.author_observations tgt
ON tmp.source_row_key = tgt.source_row_key
""".strip()


def rows_to_dicts(column_names: List[str], result_rows: List[tuple]) -> List[dict]:
    return [dict(zip(column_names, row)) for row in result_rows]


class AuthorAggregationRepository:
    def __init__(self, client):
        self.client = client

    def create_schema(self) -> None:
        for sql in schema.all_schema_sql():
            self.client.command(sql)

    def seed_field_dictionary(self) -> None:
        rows = schema.field_dictionary_rows()
        columns = [
            "table_name",
            "column_name",
            "data_type",
            "description",
            "source_mapping",
            "used_for_matching",
            "nullable_policy",
            "example_value",
            "updated_at",
        ]
        values = [[row[column] for column in columns] for row in rows]
        self.client.insert("authors_db.schema_field_dictionary", values, column_names=columns)

    def ensure_source_watermark_indexes(self, materialize: bool = True) -> None:
        for source, (table, watermark_field) in SOURCE_CONFIG.items():
            index_name = SOURCE_WATERMARK_INDEXES[source]
            self.client.command(
                f"ALTER TABLE {table} "
                f"ADD INDEX IF NOT EXISTS {index_name} {watermark_field} "
                "TYPE minmax GRANULARITY 1"
            )
            if materialize:
                self.client.command(
                    f"ALTER TABLE {table} MATERIALIZE INDEX {index_name} SETTINGS mutations_sync = 1"
                )

    def fetch_source_rows(
        self,
        source: str,
        last_watermark: datetime,
        limit: Optional[int],
        overlap_days: int,
        window_end: Optional[datetime] = None,
    ) -> List[dict]:
        sql = build_source_extract_sql(
            source,
            last_watermark,
            limit=limit,
            overlap_days=overlap_days,
            window_end=window_end,
        )
        query_result = self.client.query(sql)
        result_rows = list(getattr(query_result, "result_rows", []) or [])
        if not result_rows:
            return []
        first_row = result_rows[0]
        if isinstance(first_row, dict):
            return result_rows

        column_names = list(getattr(query_result, "column_names", None) or [])
        if not column_names:
            raise ValueError("query result does not include column names for dict conversion")
        return rows_to_dicts(column_names, result_rows)

    def get_ingest_state(self, source: str) -> Optional[IngestState]:
        sql = (
            "SELECT source, source_table, watermark_field, last_watermark, "
            "last_run_id, last_status, last_error, updated_at "
            "FROM authors_db.author_ingest_state "
            f"WHERE source = {sql_quote(source)} "
            "ORDER BY if(last_status = 'success', 0, 1), updated_at DESC LIMIT 1"
        )
        query_result = self.client.query(sql)
        result_rows = list(getattr(query_result, "result_rows", []) or [])
        if not result_rows:
            return None

        row = result_rows[0]
        if isinstance(row, dict):
            return IngestState(
                source=row["source"],
                source_table=row["source_table"],
                watermark_field=row["watermark_field"],
                last_watermark=row["last_watermark"],
                last_run_id=row["last_run_id"],
                last_status=row["last_status"],
                last_error=row["last_error"],
                updated_at=row["updated_at"],
            )

        column_names = list(getattr(query_result, "column_names", None) or [])
        if not column_names:
            raise ValueError("query result does not include column names for ingest state conversion")
        as_dict = rows_to_dicts(column_names, [row])[0]
        return IngestState(
            source=as_dict["source"],
            source_table=as_dict["source_table"],
            watermark_field=as_dict["watermark_field"],
            last_watermark=as_dict["last_watermark"],
            last_run_id=as_dict["last_run_id"],
            last_status=as_dict["last_status"],
            last_error=as_dict["last_error"],
            updated_at=as_dict["updated_at"],
        )

    def get_min_watermark(self, source: str) -> Optional[datetime]:
        table, watermark_field = SOURCE_CONFIG[source]
        sql = (
            f"SELECT min({watermark_field}) "
            f"FROM {table} "
            f"WHERE {watermark_field} > toDateTime('{format_datetime(EPOCH_WATERMARK)}')"
        )
        query_result = self.client.query(sql)
        result_rows = list(getattr(query_result, "result_rows", []) or [])
        if not result_rows:
            return None
        value = result_rows[0][0]
        return value if value else None

    def get_next_watermark(self, source: str, watermark: datetime) -> Optional[datetime]:
        table, watermark_field = SOURCE_CONFIG[source]
        sql = (
            f"SELECT min({watermark_field}) "
            f"FROM {table} "
            f"WHERE {watermark_field} >= toDateTime('{format_datetime(watermark)}')"
        )
        query_result = self.client.query(sql)
        result_rows = list(getattr(query_result, "result_rows", []) or [])
        if not result_rows:
            return None
        value = result_rows[0][0]
        return value if value else None

    def upsert_ingest_state(
        self,
        source: str,
        last_watermark: datetime,
        last_run_id: str,
        last_status: str,
        last_error: str,
        updated_at: datetime,
    ) -> None:
        source_table, watermark_field = SOURCE_CONFIG[source]
        effective_last_watermark = last_watermark if last_watermark is not None else EPOCH_WATERMARK
        columns = [
            "source",
            "source_table",
            "watermark_field",
            "last_watermark",
            "last_run_id",
            "last_status",
            "last_error",
            "updated_at",
        ]
        rows = [
            [
                source,
                source_table,
                watermark_field,
                effective_last_watermark,
                last_run_id,
                last_status,
                last_error,
                updated_at,
            ]
        ]
        self.client.insert("authors_db.author_ingest_state", rows, column_names=columns)

    def insert_observations(self, observations: Iterable[AuthorObservation]) -> None:
        rows = [[asdict(obs)[column] for column in OBSERVATION_COLUMNS] for obs in observations]
        if not rows:
            return

        temp_table = "authors_db.temp_author_observations"
        self.client.command(f"DROP TABLE IF EXISTS {temp_table}")
        self.client.command(f"CREATE TABLE {temp_table} AS authors_db.author_observations ENGINE = Memory")
        self.client.insert(temp_table, rows, column_names=OBSERVATION_COLUMNS)
        self.client.command(build_observation_insert_sql(temp_table))
        self.client.command(f"DROP TABLE IF EXISTS {temp_table}")

    def insert_paper_edges(self, edges: Iterable[PaperIdentityEdge]) -> None:
        rows = [[asdict(edge)[column] for column in PAPER_EDGE_COLUMNS] for edge in edges]
        if rows:
            self.client.insert("authors_db.paper_identity_edges", rows, column_names=PAPER_EDGE_COLUMNS)

    def insert_author_edges(self, edges: Iterable[AuthorIdentityEdge]) -> None:
        rows = [[asdict(edge)[column] for column in AUTHOR_EDGE_COLUMNS] for edge in edges]
        if rows:
            self.client.insert("authors_db.author_identity_edges", rows, column_names=AUTHOR_EDGE_COLUMNS)

    def insert_author_entities(self, entities: Iterable[AuthorEntity]) -> None:
        rows = [[asdict(entity)[column] for column in ENTITY_COLUMNS] for entity in entities]
        if rows:
            self.client.insert("authors_db.author_entities", rows, column_names=ENTITY_COLUMNS)
