"""ClickHouse schema definitions for Academic CV Builder tables."""

from __future__ import annotations

import re


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


CV_TABLES = {
    "personal_profile": {
        "columns": [
            ("id", "String"),
            ("openalex_id", "String"),
            ("orcid", "String"),
            ("name", "String"),
            ("bio", "String"),
            ("country", "String"),
            ("email", "String"),
            ("source", "String"),
            ("source_url", "String"),
            ("import_time", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(import_time)",
        "order_by": "id",
    },
    "education_work_experience": {
        "columns": [
            ("id", "String"),
            ("author_id", "String"),
            ("role_title", "String"),
            ("institution_name", "String"),
            ("department_name", "String"),
            ("city", "String"),
            ("affiliation_type", "String"),
            ("province", "String"),
            ("date_range", "String"),
            ("country", "String"),
            ("source", "String"),
            ("source_url", "String"),
            ("import_time", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(import_time)",
        "order_by": "(author_id, id)",
    },
    "research_outputs": {
        "columns": [
            ("id", "String"),
            ("author_id", "String"),
            ("work_title", "String"),
            ("work_type", "String"),
            ("venue_name", "String"),
            ("publication_date", "String"),
            ("authors", "String"),
            ("source", "String"),
            ("source_url", "String"),
            ("import_time", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(import_time)",
        "order_by": "(author_id, id)",
    },
    "funding_info": {
        "columns": [
            ("id", "String"),
            ("author_id", "String"),
            ("end_date", "String"),
            ("award_title", "String"),
            ("city", "String"),
            ("funder_name", "String"),
            ("province", "String"),
            ("funding_type", "String"),
            ("country", "String"),
            ("start_date", "String"),
            ("source", "String"),
            ("source_url", "String"),
            ("import_time", "DateTime"),
        ],
        "engine": "ReplacingMergeTree(import_time)",
        "order_by": "(author_id, id)",
    },
    "author_build_queue": {
        "columns": [
            ("openalex_author_id", "String"),
            ("person_id", "String"),
            ("status", "String"),
            ("last_error", "String"),
            ("retry_count", "UInt16"),
            ("updated_at", "DateTime64(3)"),
        ],
        "engine": "ReplacingMergeTree(updated_at)",
        "order_by": "openalex_author_id",
    },
}


def quote_identifier(identifier: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Invalid ClickHouse identifier: {identifier!r}")
    return f"`{identifier}`"


def build_create_database_sql(database: str) -> str:
    return f"CREATE DATABASE IF NOT EXISTS {quote_identifier(database)}"


def build_create_table_sql(database: str, table: str) -> str:
    quoted_database = quote_identifier(database)
    quoted_table = quote_identifier(table)
    table_schema = CV_TABLES[table]
    columns_sql = ",\n    ".join(
        f"{column_name} {column_type}"
        for column_name, column_type in table_schema["columns"]
    )

    return f"""
CREATE TABLE IF NOT EXISTS {quoted_database}.{quoted_table}
(
    {columns_sql}
)
ENGINE = {table_schema["engine"]}
ORDER BY {table_schema["order_by"]}
""".strip()
