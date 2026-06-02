#!/usr/bin/env python3
"""Export OpenAlex author rows from ClickHouse to text or JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, TextIO

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8123
DEFAULT_USERNAME = "default"
DEFAULT_PASSWORD = ""
DEFAULT_DATABASE = "academic_db"
DEFAULT_TABLE = "OpenAlex"
DEFAULT_AUTHOR_BATCH_SIZE = 100

QUERY_COLUMNS: Sequence[str] = (
    "author_id",
    "author",
    "uid",
    "doi",
    "title",
    "rank",
    "journal",
    "citation_count",
    "tag",
    "state",
    "institution_id",
    "institution_name",
    "institution_country",
    "institution_type",
    "raw_affiliation",
    "fwci",
    "citation_percentile",
    "primary_topic",
    "is_retracted",
    "publication_date",
    "import_time",
)

REQUIRED_RECORD_FIELDS: Sequence[str] = (
    "author_id",
    "author",
    "uid",
    "doi",
    "title",
    "rank",
    "journal",
    "citation_count",
    "tag",
    "state",
    "institution_id",
    "institution_name",
    "institution_country",
    "institution_type",
    "raw_affiliation",
    "fwci",
    "citation_percentile",
    "primary_topic",
    "is_retracted",
    "publication_date",
    "import_time",
)

REQUIRED_OUTPUT_TOP_FIELDS: Sequence[str] = ("author_id", "author", "record_count", "records")


def quote_identifier(identifier: str) -> str:
    """Return a safely quoted ClickHouse identifier."""

    safe = identifier.replace("`", "``")
    return f"`{safe}`"


def _normalize_limit(value: Optional[int]) -> Optional[int]:
    """Normalize an optional positive integer limit."""

    if value is None:
        return None
    try:
        int_value = int(value)
    except (TypeError, ValueError):
        return None

    if int_value <= 0:
        return None

    return int_value


def _normalize_author_batch_size(value: Optional[int]) -> int:
    normalized = _normalize_limit(value)
    return normalized if normalized is not None else DEFAULT_AUTHOR_BATCH_SIZE


def _escape_author_id_value(author_id: Any) -> str:
    return str(author_id).replace("'", "''")


def build_query(
    database: str,
    table: str,
    author_id: Optional[str] = None,
    query_limit: Optional[int] = None,
) -> str:
    """Build the single ordered query used for extraction."""

    columns = ", ".join(quote_identifier(col) for col in QUERY_COLUMNS)
    where_clauses: List[str] = []
    where_clauses.append(f"{quote_identifier('author_id')} != ''")
    where_clauses.append(f"{quote_identifier('author_id')} IS NOT NULL")
    if author_id:
        escaped_author_id = _escape_author_id_value(author_id)
        where_clauses.append(f"{quote_identifier('author_id')} = '{escaped_author_id}'")

    where_clause = " WHERE " + " AND ".join(where_clauses)

    query = (
        f"SELECT {columns}"
        f" FROM {quote_identifier(database)}.{quote_identifier(table)}"
        f"{where_clause}"
        f" ORDER BY {quote_identifier('author_id')}, {quote_identifier('doi')}, {quote_identifier('rank')}"
    )

    normalized_limit = _normalize_limit(query_limit)
    if normalized_limit is not None:
        query += f" LIMIT {normalized_limit}"

    return query


def build_author_id_in_query(
    database: str,
    table: str,
    author_ids: Sequence[str],
    query_limit: Optional[int] = None,
) -> str:
    """Build a query fetching records for the sampled author ids."""

    normalized_author_ids = [str(author_id) for author_id in author_ids if str(author_id)]
    if not normalized_author_ids:
        return ""

    escaped_author_ids = ", ".join(
        f"'{_escape_author_id_value(author_id)}'" for author_id in normalized_author_ids
    )
    columns = ", ".join(quote_identifier(col) for col in QUERY_COLUMNS)
    where_clauses: List[str] = [
        f"{quote_identifier('author_id')} != ''",
        f"{quote_identifier('author_id')} IS NOT NULL",
        f"{quote_identifier('author_id')} IN ({escaped_author_ids})",
    ]

    where_clause = " WHERE " + " AND ".join(where_clauses)

    query = (
        f"SELECT {columns}"
        f" FROM {quote_identifier(database)}.{quote_identifier(table)}"
        f"{where_clause}"
        f" ORDER BY {quote_identifier('author_id')}, {quote_identifier('doi')}, {quote_identifier('rank')}"
    )

    normalized_limit = _normalize_limit(query_limit)
    if normalized_limit is not None:
        query += f" LIMIT {normalized_limit}"

    return query


def build_author_id_sample_query(
    database: str,
    table: str,
    query_limit: Optional[int] = None,
) -> str:
    """Build a cheap query that samples author ids first."""

    normalized_limit = _normalize_limit(query_limit)

    where_clauses = [
        f"{quote_identifier('author_id')} != ''",
        f"{quote_identifier('author_id')} IS NOT NULL",
    ]

    query = (
        f"SELECT DISTINCT {quote_identifier('author_id')}"
        f" FROM {quote_identifier(database)}.{quote_identifier(table)}"
        f" WHERE {' AND '.join(where_clauses)}"
    )

    if normalized_limit is not None:
        query += f" LIMIT {normalized_limit}"

    return query


def create_clickhouse_client(
    host: str,
    port: int,
    username: str,
    password: str,
    database: str,
):
    import clickhouse_connect  # type: ignore

    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=username,
        password=password,
        database=database,
    )


def _normalize_clickhouse_row(
    row: Any,
    columns: Sequence[str],
) -> Dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)

    if isinstance(row, (tuple, list)):
        return {col: row[idx] if idx < len(row) else None for idx, col in enumerate(columns)}

    if hasattr(row, "_asdict"):
        return dict(row._asdict())

    raise TypeError(f"Unsupported row type: {type(row)!r}")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y"}:
            return True
        if normalized in {"0", "false", "f", "no", "n"}:
            return False

    return default


def _coerce_record(row: Mapping[str, Any]) -> Dict[str, Any]:
    author_id = str(row.get("author_id", "") or "")
    uid = str(row.get("uid", "") or "")
    rank = _to_int(row.get("rank"), 0)
    citation_count = _to_int(row.get("citation_count"), 0)
    fwci = _to_float(row.get("fwci"), 0.0)
    citation_percentile = _to_int(row.get("citation_percentile"), 0)
    is_retracted = _to_bool(row.get("is_retracted"), False)
    publication_date = "" if row.get("publication_date") is None else str(row.get("publication_date"))
    import_time = "" if row.get("import_time") is None else str(row.get("import_time"))

    return {
        "author_id": author_id,
        "author": str(row.get("author", "") or ""),
        "uid": uid,
        "doi": str(row.get("doi", "") or ""),
        "title": str(row.get("title", "") or ""),
        "rank": rank,
        "journal": str(row.get("journal", "") or ""),
        "citation_count": citation_count,
        "tag": str(row.get("tag", "") or ""),
        "state": str(row.get("state", "") or ""),
        "institution_id": str(row.get("institution_id", "") or ""),
        "institution_name": str(row.get("institution_name", "") or ""),
        "institution_country": str(row.get("institution_country", "") or ""),
        "institution_type": str(row.get("institution_type", "") or ""),
        "raw_affiliation": str(row.get("raw_affiliation", "") or ""),
        "fwci": fwci,
        "citation_percentile": citation_percentile,
        "primary_topic": str(row.get("primary_topic", "") or ""),
        "is_retracted": is_retracted,
        "publication_date": publication_date,
        "import_time": import_time,
    }


def _iter_stream_rows(stream: Any, columns: Sequence[str]) -> Iterator[Dict[str, Any]]:
    for item in stream:
        if isinstance(item, list):
            if item and isinstance(item[0], (tuple, list, Mapping)):
                for raw_row in item:
                    yield _normalize_clickhouse_row(raw_row, columns)
                continue

        if isinstance(item, (tuple, list)) and len(item) == len(columns):
            yield _normalize_clickhouse_row(item, columns)
            continue

        yield _normalize_clickhouse_row(item, columns)


def _query_rows(client: Any, query: str, columns: Sequence[str]) -> Iterator[Dict[str, Any]]:
    """Yield query rows without materializing the full result set."""

    if hasattr(client, "query_rows_stream"):
        context = client.query_rows_stream(query)
    elif hasattr(client, "query_row_block_stream"):
        context = client.query_row_block_stream(query)
    else:
        raise TypeError("ClickHouse client must expose query_rows_stream or query_row_block_stream")

    if hasattr(context, "__enter__"):
        manager = context
    else:
        manager = nullcontext(context)

    with manager as stream:
        yield from _iter_stream_rows(stream, columns)


def _extract_author_id_rows(
    client: Any,
    database: str,
    table: str,
    limit_authors: int,
) -> Iterator[str]:
    query = build_author_id_sample_query(
        database=database,
        table=table,
        query_limit=limit_authors,
    )

    for row in _query_rows(client, query, ("author_id",)):
        author_id = str(row.get("author_id", "") or "")
        if author_id:
            yield author_id


def _row_key(row: Mapping[str, Any]) -> str:
    return str(row.get("author_id", "") or "")


def _should_stop_limit_authors(limit_authors: Optional[int], emitted_authors: int) -> bool:
    if limit_authors is None:
        return False
    return emitted_authors >= limit_authors


def _chunk_author_ids(author_ids: Sequence[str], batch_size: int) -> Iterator[Sequence[str]]:
    normalized_batch_size = _normalize_author_batch_size(batch_size)
    for start in range(0, len(author_ids), normalized_batch_size):
        yield author_ids[start : start + normalized_batch_size]


def _write_text_author_group(
    output: TextIO,
    author_id: str,
    author: str,
    records: Sequence[Dict[str, Any]],
) -> None:
    """Write one author block in human-readable text."""

    output.write(f"Author ID: {author_id}\n")
    output.write(f"Author: {author}\n")
    output.write(f"Record count: {len(records)}\n")
    output.write("Records:\n")
    for record_index, record in enumerate(records, start=1):
        output.write(f"Record {record_index}\n")
        for field_name in REQUIRED_RECORD_FIELDS:
            output.write(f"  {field_name}: {record.get(field_name, '')}\n")
        output.write("\n")


def _write_jsonl_author_group(
    output: TextIO,
    author_id: str,
    author: str,
    records: Sequence[Dict[str, Any]],
) -> None:
    rec = {
        "author_id": author_id,
        "author": author,
        "record_count": len(records),
        "records": records,
    }
    output.write(json.dumps(rec, ensure_ascii=True) + "\n")


def export_rows(
    client,
    output: TextIO,
    database: str,
    table: str,
    author_id: Optional[str] = None,
    limit_authors: Optional[int] = None,
    query_limit: Optional[int] = None,
    output_format: str = "text",
    author_batch_size: int = DEFAULT_AUTHOR_BATCH_SIZE,
) -> int:
    """Run query and stream output.

    Returns the number of output records written.
    """

    written = 0
    emitted_authors = 0

    def flush_group(group: Sequence[Dict[str, Any]]) -> None:
        nonlocal emitted_authors, written
        if not group:
            return

        first = group[0]
        author_id = str(first.get("author_id", "") or "")
        author = str(first.get("author", "") or "")
        records = [_coerce_record(row) for row in group]
        if output_format == "jsonl":
            _write_jsonl_author_group(output, author_id=author_id, author=author, records=records)
        else:
            _write_text_author_group(output, author_id=author_id, author=author, records=records)
        written += 1
        emitted_authors += 1

    def write_grouped_rows(rows: Iterator[Dict[str, Any]]) -> None:
        current_key: Optional[str] = None
        current_group: List[Dict[str, Any]] = []
        for row in rows:
            key = _row_key(row)
            if current_key is None:
                current_key = key

            if key != current_key:
                flush_group(current_group)
                current_group = []
                current_key = key

            current_group.append(row)

        if current_group:
            flush_group(current_group)

    if limit_authors is not None and limit_authors <= 0:
        return 0

    if author_id is None and limit_authors is not None:
        sampled_author_ids = list(
            _extract_author_id_rows(
                client=client,
                database=database,
                table=table,
                limit_authors=limit_authors,
            )
        )
        if not sampled_author_ids:
            return 0

        for author_id_batch in _chunk_author_ids(sampled_author_ids, author_batch_size):
            query = build_author_id_in_query(
                database=database,
                table=table,
                author_ids=author_id_batch,
                query_limit=query_limit,
            )
            if not query:
                continue
            write_grouped_rows(_query_rows(client, query, QUERY_COLUMNS))
            if _should_stop_limit_authors(limit_authors, emitted_authors):
                break

        return written

    query = build_query(
        database=database,
        table=table,
        author_id=author_id,
        query_limit=query_limit,
    )
    if not query:
        return 0
    write_grouped_rows(_query_rows(client, query, QUERY_COLUMNS))

    return written


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export OpenAlex author records")
    parser.add_argument(
        "--format",
        choices=("text", "jsonl"),
        default="text",
        help="Output format (text or jsonl)",
    )
    parser.add_argument("--author-id", dest="author_id", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--limit-authors", type=int, default=None)
    parser.add_argument("--author-batch-size", type=int, default=DEFAULT_AUTHOR_BATCH_SIZE)
    parser.add_argument("--query-limit", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    client = create_clickhouse_client(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        database=args.database,
    )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as output:
            return export_rows(
                client=client,
                output=output,
                database=args.database,
                table=args.table,
                author_id=args.author_id,
                limit_authors=args.limit_authors,
                query_limit=args.query_limit,
                output_format=args.format,
                author_batch_size=args.author_batch_size,
            )

    return export_rows(
        client=client,
        output=sys.stdout,
        database=args.database,
        table=args.table,
        author_id=args.author_id,
        limit_authors=args.limit_authors,
        query_limit=args.query_limit,
        output_format=args.format,
        author_batch_size=args.author_batch_size,
    )


def cli(argv: Optional[Sequence[str]] = None) -> int:
    main(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
