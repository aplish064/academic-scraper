"""ClickHouse repository for Academic CV Builder rows and queue state."""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import urlsplit

import clickhouse_connect

from src.cv_builder.config import CvBuilderConfig
from src.cv_builder.ids import make_person_id
from src.cv_builder.schema import (
    CV_TABLES,
    build_create_database_sql,
    build_create_table_sql,
    quote_identifier,
)


_OPENALEX_AUTHOR_ID_RE = re.compile(r"^A\d+$", re.IGNORECASE)
_OPENALEX_WORK_ID_RE = re.compile(r"^W\d+$", re.IGNORECASE)
_SOURCE_NUMERIC_ID_RE = re.compile(r"^\d+(?:\.0)?$")
_EMPTY_SENTINELS = {"", "nan", "none", "null", "<na>"}
_QUEUE_STATUSES = {"pending", "processing", "done", "skipped", "failed"}


def table_name(database: str, table: str) -> str:
    """Return a safely quoted ClickHouse qualified table name."""
    return f"{quote_identifier(database)}.{quote_identifier(table)}"


class CvRepository:
    def __init__(self, config: CvBuilderConfig):
        self.config = config
        self.client = clickhouse_connect.get_client(
            host=config.clickhouse_host,
            port=config.clickhouse_port,
            username=config.clickhouse_user,
            password=config.clickhouse_password,
            database=config.clickhouse_database,
        )

    def init_schema(self) -> None:
        self.client.command(build_create_database_sql(self.config.cv_database))
        for table in CV_TABLES:
            self.client.command(build_create_table_sql(self.config.cv_database, table))

    def insert_rows(self, table: str, rows: list[dict]) -> None:
        if table not in CV_TABLES:
            raise ValueError(f"Unknown CV table: {table!r}")
        if not rows:
            return

        columns = [column_name for column_name, _ in CV_TABLES[table]["columns"]]
        column_types = {column_name: column_type for column_name, column_type in CV_TABLES[table]["columns"]}
        values = [
            [
                row[column] if column in row else _default_for_clickhouse_type(column_types[column])
                for column in columns
            ]
            for row in rows
        ]
        self.client.insert(
            table_name(self.config.cv_database, table),
            values,
            column_names=columns,
        )

    def upsert_profile(self, row: dict) -> None:
        self.insert_rows("personal_profile", [row])

    def upsert_experiences(self, rows: list[dict]) -> None:
        self.insert_rows("education_work_experience", rows)

    def upsert_research_outputs(self, rows: list[dict]) -> None:
        self.insert_rows("research_outputs", rows)

    def upsert_funding(self, rows: list[dict]) -> None:
        self.insert_rows("funding_info", rows)

    def get_local_work_ids_for_author(self, openalex_author_id: str, limit: int = 200) -> list[str]:
        normalized_author_id = _normalize_openalex_author_id(openalex_author_id)
        if not normalized_author_id:
            return []

        result = self.client.query(
            f"""
            SELECT DISTINCT uid
            FROM {table_name(self.config.clickhouse_database, "OpenAlex")}
            WHERE author_id != ''
              AND lower(author_id) NOT IN ('nan', 'none', 'null', '<na>')
              AND author_id IN {{author_ids:Array(String)}}
              AND uid != ''
              AND lower(uid) NOT IN ('nan', 'none', 'null', '<na>')
            ORDER BY uid
            LIMIT {{limit:UInt32}}
            """,
            parameters={
                "author_ids": _source_author_id_candidates(normalized_author_id),
                "limit": limit,
            },
        )
        work_ids = []
        seen_work_ids = set()
        for row in result.result_rows:
            work_id = _normalize_openalex_work_id(row[0] if row else "")
            if not work_id or work_id in seen_work_ids:
                continue
            seen_work_ids.add(work_id)
            work_ids.append(work_id)
        return work_ids

    def enqueue_authors_from_openalex(self, limit: int) -> int:
        result = self.client.query(
            f"""
            SELECT DISTINCT author_id
            FROM {table_name(self.config.clickhouse_database, "OpenAlex")}
            WHERE author_id != ''
              AND lower(author_id) NOT IN ('nan', 'none', 'null', '<na>')
            ORDER BY author_id
            LIMIT {{limit:UInt32}}
            """,
            parameters={"limit": limit},
        )

        seen_author_ids = []
        seen_author_id_set = set()
        for row in result.result_rows:
            author_id = _normalize_openalex_author_id(row[0] if row else "")
            if not author_id or author_id in seen_author_id_set:
                continue
            seen_author_id_set.add(author_id)
            seen_author_ids.append(author_id)
        existing_author_ids = self._existing_queue_author_ids(seen_author_id_set)
        rows = []
        now = datetime.now()
        for author_id in seen_author_ids:
            if author_id in existing_author_ids:
                continue
            rows.append(
                {
                    "openalex_author_id": author_id,
                    "person_id": make_person_id(author_id),
                    "status": "pending",
                    "last_error": "",
                    "retry_count": 0,
                    "updated_at": now,
                }
            )

        self.insert_rows("author_build_queue", rows)
        return len(rows)

    def next_pending_author(self) -> str:
        result = self.client.query(
            f"""
            SELECT openalex_author_id, person_id, retry_count
            FROM {table_name(self.config.cv_database, "author_build_queue")} FINAL
            WHERE status = 'pending'
            ORDER BY updated_at, openalex_author_id
            LIMIT 1
            """
        )
        if not result.result_rows:
            return ""
        row = result.result_rows[0]
        author_id = row[0]
        person_id = row[1] if len(row) > 1 and row[1] else make_person_id(author_id)
        retry_count = row[2] if len(row) > 2 else 0
        self._insert_queue_status(author_id, person_id, "processing", "", retry_count)
        return author_id

    def mark_author_status(
        self,
        openalex_author_id: str,
        person_id: str,
        status: str,
        last_error: str = "",
    ) -> None:
        author_id = _normalize_openalex_author_id(openalex_author_id)
        if not author_id:
            raise ValueError(f"Invalid OpenAlex author ID: {openalex_author_id!r}")
        if status not in _QUEUE_STATUSES:
            raise ValueError(f"Invalid queue status: {status!r}")
        retry_count = self._current_retry_count(author_id)
        if status == "failed":
            retry_count += 1
        self._insert_queue_status(author_id, person_id, status, last_error, retry_count)

    def _existing_queue_author_ids(self, author_ids: set[str]) -> set[str]:
        if not author_ids:
            return set()
        result = self.client.query(
            f"""
            SELECT openalex_author_id
            FROM {table_name(self.config.cv_database, "author_build_queue")} FINAL
            WHERE openalex_author_id IN {{author_ids:Array(String)}}
            """,
            parameters={"author_ids": sorted(author_ids)},
        )
        return {row[0] for row in result.result_rows}

    def _current_retry_count(self, openalex_author_id: str) -> int:
        result = self.client.query(
            f"""
            SELECT retry_count
            FROM {table_name(self.config.cv_database, "author_build_queue")} FINAL
            WHERE openalex_author_id = {{author_id:String}}
            LIMIT 1
            """,
            parameters={"author_id": openalex_author_id},
        )
        if not result.result_rows:
            return 0
        return int(result.result_rows[0][0] or 0)

    def _insert_queue_status(
        self,
        openalex_author_id: str,
        person_id: str,
        status: str,
        last_error: str,
        retry_count: int,
    ) -> None:
        self.insert_rows(
            "author_build_queue",
            [
                {
                    "openalex_author_id": openalex_author_id,
                    "person_id": person_id,
                    "status": status,
                    "last_error": last_error,
                    "retry_count": retry_count,
                    "updated_at": datetime.now(),
                }
            ],
        )


def _clean_text(value) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).strip().split())
    if text.lower() in _EMPTY_SENTINELS:
        return ""
    return text


def _default_for_clickhouse_type(column_type: str):
    if column_type.startswith("DateTime"):
        return datetime.now()
    if column_type.startswith("UInt"):
        return 0
    return ""


def _normalize_openalex_author_id(value) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    candidate = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    if _OPENALEX_AUTHOR_ID_RE.fullmatch(candidate):
        return candidate
    if _SOURCE_NUMERIC_ID_RE.fullmatch(candidate):
        return f"A{_strip_dot_zero(candidate)}"

    return ""


def _normalize_openalex_work_id(value) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    candidate = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    if _OPENALEX_WORK_ID_RE.fullmatch(candidate):
        return candidate
    if _SOURCE_NUMERIC_ID_RE.fullmatch(candidate):
        return f"W{_strip_dot_zero(candidate)}"
    return ""


def _source_author_id_candidates(normalized_author_id: str) -> list[str]:
    candidates = [normalized_author_id]
    if _OPENALEX_AUTHOR_ID_RE.fullmatch(normalized_author_id):
        numeric = normalized_author_id[1:]
        candidates.extend([numeric, f"{numeric}.0", f"https://openalex.org/{normalized_author_id}"])
    return candidates


def _strip_dot_zero(value: str) -> str:
    return value[:-2] if value.endswith(".0") else value
