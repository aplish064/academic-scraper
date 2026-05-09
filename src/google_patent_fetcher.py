#!/usr/bin/env python3
"""Pure helpers for mapping Google Patents BigQuery publication rows."""

import argparse
import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, Iterator, List

try:
    from src import cn_patent_fetcher
except ImportError:  # pragma: no cover - supports direct script execution from src/
    import cn_patent_fetcher  # type: ignore

SOURCE_NAME = "google_patents"
PUBLICATIONS_TABLE = "patents-public-data.patents.publications"
DEFAULT_WINDOW_START_DATE = "1985-01-01"

PUBLICATION_COLUMNS = [
    "publication_number",
    "application_number",
    "country_code",
    "family_id",
    "title_localized",
    "abstract_localized",
    "publication_date",
    "filing_date",
    "grant_date",
    "inventor",
    "assignee",
    "ipc",
    "cpc",
]


def parse_args(argv: Any = None) -> argparse.Namespace:
    """Parse Google Patents bulk fetcher CLI arguments."""
    parser = argparse.ArgumentParser(description="Fetch Google Patents publication rows from BigQuery.")
    parser.add_argument("--country", default="CN")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--page-size", type=int, default=10000)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--estimate-only", action="store_true", default=False)
    parser.add_argument("--create-staging", action="store_true", default=False)
    parser.add_argument("--source-table", default=None)
    parser.add_argument("--staging-dataset", default="google_patents_staging")
    parser.add_argument("--staging-table", default="cn_publications")
    parser.add_argument("--max-bytes-billed", type=int, default=None)
    parser.add_argument("--windowed", action="store_true", default=False)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--windowed-staging", action="store_true", default=False)
    parser.add_argument("--keep-window-staging", action="store_true", default=False)
    parser.add_argument("--temp-staging-prefix", default="cn_publications_window")
    parser.add_argument("--no-resume-windowed", dest="resume_windowed", action="store_false")
    parser.set_defaults(resume_windowed=True)
    parser.add_argument("--credentials", default="data/patent-494208-e330c3351d40.json")
    parser.add_argument("--log-file", default="log/google_patent_fetcher.log")
    parser.add_argument("--progress-file", default="log/google_patent_fetch_progress.json")
    return parser.parse_args(argv)


def create_bigquery_client(credentials_path: str) -> Any:
    """Create an authenticated BigQuery client from a service account file."""
    bigquery_module = require_bigquery()

    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "google-auth is required for Google BigQuery service account credentials. "
            "Install it in the project environment or run with the existing venv."
        ) from exc

    credentials = service_account.Credentials.from_service_account_file(credentials_path)
    return bigquery_module.Client(credentials=credentials, project=credentials.project_id)


def estimate_query_bytes(
    client: Any,
    sql: str,
    country: str,
    start_date: Any = None,
    end_date: Any = None,
) -> int:
    """Run a BigQuery dry-run job and return estimated bytes processed."""
    bigquery_module = require_bigquery()
    job_config = bigquery_module.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
        query_parameters=_query_parameters(bigquery_module, country, start_date, end_date),
    )
    job = client.query(sql, job_config=job_config)
    return int(getattr(job, "total_bytes_processed", 0) or 0)


def run(argv: Any = None) -> int:
    """Run the Google Patents bulk fetcher CLI."""
    args = parse_args(argv)
    try:
        return _run(args)
    except Exception as exc:
        write_progress(
            args.progress_file,
            status="failed",
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        raise


def _run(args: argparse.Namespace) -> int:
    """Run the Google Patents bulk fetcher with parsed CLI arguments."""
    client = create_bigquery_client(args.credentials)
    if args.create_staging:
        target_table = build_staging_table_id(client, args)
        staging_sql = build_create_staging_query(
            target_table,
            country=args.country,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        write_progress(
            args.progress_file,
            phase="create_staging",
            status="estimating",
            country=args.country,
            target_table=target_table,
        )
        estimated_bytes = estimate_query_bytes(client, staging_sql, args.country, args.start_date, args.end_date)
        _emit(f"staging_estimated_bytes={estimated_bytes}", args.log_file)
        write_progress(
            args.progress_file,
            phase="create_staging",
            status="estimated",
            country=args.country,
            target_table=target_table,
            estimated_bytes=estimated_bytes,
        )
        if args.estimate_only:
            return 0

        staging_table = create_staging_table(
            client,
            dataset_id=args.staging_dataset,
            table_id=args.staging_table,
            country=args.country,
            start_date=args.start_date,
            end_date=args.end_date,
            max_bytes_billed=args.max_bytes_billed,
            progress_file=args.progress_file,
        )
        _emit(f"staging_table={staging_table}", args.log_file)
        write_progress(
            args.progress_file,
            phase="create_staging",
            status="completed",
            country=args.country,
            staging_table=staging_table,
            estimated_bytes=estimated_bytes,
        )
        return 0

    if args.windowed:
        return run_windowed_import(client, args)

    source_table = build_source_table_id(args)
    sql = build_publications_query(
        country=args.country,
        start_date=args.start_date,
        end_date=args.end_date,
        limit=args.limit,
        source_table=source_table,
    )

    write_progress(
        args.progress_file,
        phase="import_clickhouse",
        status="estimating",
        country=args.country,
        source_table=source_table,
    )
    estimated_bytes = estimate_query_bytes(client, sql, args.country, args.start_date, args.end_date)
    _emit(f"estimated_bytes={estimated_bytes}", args.log_file)
    write_progress(
        args.progress_file,
        phase="import_clickhouse",
        status="estimated",
        country=args.country,
        source_table=source_table,
        estimated_bytes=estimated_bytes,
    )

    if args.estimate_only:
        return 0

    if args.dry_run:
        records = 0
        rows = stream_query_rows(
            client,
            sql,
            country=args.country,
            start_date=args.start_date,
            end_date=args.end_date,
            page_size=args.page_size,
            max_bytes_billed=args.max_bytes_billed,
        )
        for batch in iter_batches(rows, args.batch_size):
            for row in batch:
                map_bigquery_row(row)
                records += 1
        _emit(f"dry_run_records={records}", args.log_file)
        write_progress(
            args.progress_file,
            phase="dry_run",
            status="completed",
            country=args.country,
            source_table=source_table,
            records=records,
            estimated_bytes=estimated_bytes,
        )
        return 0

    ch_client = cn_patent_fetcher.create_clickhouse_client()
    cn_patent_fetcher.ensure_database(ch_client)
    inserted_patents = 0
    write_progress(
        args.progress_file,
        phase="import_clickhouse",
        status="running",
        country=args.country,
        source_table=source_table,
        inserted_patents=inserted_patents,
        estimated_bytes=estimated_bytes,
    )
    rows = stream_query_rows(
        client,
        sql,
        country=args.country,
        start_date=args.start_date,
        end_date=args.end_date,
        page_size=args.page_size,
        max_bytes_billed=args.max_bytes_billed,
    )
    for batch in iter_batches(rows, args.batch_size):
        inserted_patents += process_bigquery_batch(ch_client, batch, args.batch_size)
        _emit(f"inserted_patents={inserted_patents}", args.log_file)
        write_progress(
            args.progress_file,
            phase="import_clickhouse",
            status="running",
            country=args.country,
            source_table=source_table,
            inserted_patents=inserted_patents,
            last_batch_size=len(batch),
            estimated_bytes=estimated_bytes,
        )
    write_progress(
        args.progress_file,
        phase="import_clickhouse",
        status="completed",
        country=args.country,
        source_table=source_table,
        inserted_patents=inserted_patents,
        estimated_bytes=estimated_bytes,
    )
    return 0


def run_windowed_import(client: Any, args: argparse.Namespace) -> int:
    """Import Google Patents directly from the source table in date windows."""
    source_table = build_source_table_id(args)
    start_date, end_date = resolve_window_bounds(args)
    windows = list(iter_date_windows(start_date, end_date, args.window_days))
    progress = load_progress_file(args.progress_file)
    completed_windows = progress.get("completed_windows", {})
    if not isinstance(completed_windows, dict) or not args.resume_windowed:
        completed_windows = {}

    inserted_patents_total = sum(
        int(value.get("inserted_patents", 0) or 0)
        for value in completed_windows.values()
        if isinstance(value, dict)
    )
    estimated_bytes_total = 0

    write_progress(
        args.progress_file,
        phase="windowed_import",
        status="running",
        country=args.country,
        source_table=source_table,
        start_date=start_date,
        end_date=end_date,
        window_days=args.window_days,
        total_windows=len(windows),
        completed_windows=completed_windows,
        inserted_patents_total=inserted_patents_total,
        estimated_bytes_total=estimated_bytes_total,
    )

    ch_client = None
    if not args.estimate_only and not args.dry_run:
        ch_client = cn_patent_fetcher.create_clickhouse_client()
        cn_patent_fetcher.ensure_database(ch_client)

    for window_start, window_end in windows:
        key = window_progress_key(window_start, window_end)
        if key in completed_windows:
            _emit(f"window_skipped={key}", args.log_file)
            continue

        sql = build_publications_query(
            country=args.country,
            start_date=window_start,
            end_date=window_end,
            limit=args.limit,
            source_table=source_table,
        )
        write_progress(
            args.progress_file,
            phase="windowed_import",
            status="estimating",
            country=args.country,
            source_table=source_table,
            current_window=key,
            completed_windows=completed_windows,
            inserted_patents_total=inserted_patents_total,
            estimated_bytes_total=estimated_bytes_total,
        )
        estimated_bytes = estimate_query_bytes(client, sql, args.country, window_start, window_end)
        estimated_bytes_total += estimated_bytes
        _emit(f"window_estimated_bytes={key}:{estimated_bytes}", args.log_file)

        if args.estimate_only:
            continue

        temp_staging_table = ""
        temp_staging_deleted = False
        query_source_table = source_table
        query_start_date = window_start
        query_end_date = window_end
        if args.windowed_staging:
            temp_staging_table = create_staging_table(
                client,
                dataset_id=args.staging_dataset,
                table_id=build_temp_staging_table_name(args, window_start, window_end),
                country=args.country,
                start_date=window_start,
                end_date=window_end,
                max_bytes_billed=args.max_bytes_billed,
                progress_file=args.progress_file,
            )
            query_source_table = temp_staging_table
            query_start_date = None
            query_end_date = None
            write_progress(
                args.progress_file,
                phase="windowed_import",
                status="temp_staging_ready",
                country=args.country,
                source_table=source_table,
                current_window=key,
                temp_staging_table=temp_staging_table,
                completed_windows=completed_windows,
                inserted_patents_total=inserted_patents_total,
                estimated_bytes_total=estimated_bytes_total,
            )

        query_sql = build_publications_query(
            country=args.country,
            start_date=query_start_date,
            end_date=query_end_date,
            limit=args.limit,
            source_table=query_source_table,
        )
        inserted_patents = 0
        try:
            rows = stream_query_rows(
                client,
                query_sql,
                country=args.country,
                start_date=query_start_date,
                end_date=query_end_date,
                page_size=args.page_size,
                max_bytes_billed=args.max_bytes_billed,
            )
            for batch in iter_batches(rows, args.batch_size):
                if args.dry_run:
                    for row in batch:
                        map_bigquery_row(row)
                    inserted_patents += len(batch)
                else:
                    inserted_patents += process_bigquery_batch(ch_client, batch, args.batch_size)
                write_progress(
                    args.progress_file,
                    phase="windowed_import",
                    status="running",
                    country=args.country,
                    source_table=source_table,
                    current_window=key,
                    temp_staging_table=temp_staging_table,
                    completed_windows=completed_windows,
                    inserted_patents_total=inserted_patents_total + inserted_patents,
                    last_batch_size=len(batch),
                    estimated_bytes_total=estimated_bytes_total,
                )
        finally:
            if temp_staging_table and not args.keep_window_staging:
                delete_bigquery_table(client, temp_staging_table)
                temp_staging_deleted = True

        inserted_patents_total += inserted_patents
        completed_windows[key] = {
            "start_date": window_start,
            "end_date": window_end,
            "inserted_patents": inserted_patents,
            "estimated_bytes": estimated_bytes,
            "temp_staging_table": temp_staging_table,
            "temp_staging_deleted": temp_staging_deleted,
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
        _emit(f"window_completed={key} inserted_patents={inserted_patents}", args.log_file)
        write_progress(
            args.progress_file,
            phase="windowed_import",
            status="running",
            country=args.country,
            source_table=source_table,
            current_window=key,
            completed_windows=completed_windows,
            inserted_patents_total=inserted_patents_total,
            estimated_bytes_total=estimated_bytes_total,
        )

    final_status = "estimated" if args.estimate_only else "completed"
    write_progress(
        args.progress_file,
        phase="windowed_import",
        status=final_status,
        country=args.country,
        source_table=source_table,
        start_date=start_date,
        end_date=end_date,
        total_windows=len(windows),
        completed_windows=completed_windows,
        inserted_patents_total=inserted_patents_total,
        estimated_bytes_total=estimated_bytes_total,
    )
    return 0


def process_bigquery_batch(ch_client: Any, rows: Iterable[Any], batch_size: int) -> int:
    """Map, parse, expand, and insert one bounded BigQuery batch into ClickHouse."""
    expanded_rows = {
        "patents": [],
        "applications": [],
        "inventors": [],
        "assignees": [],
        "abstracts": [],
        "ipc": [],
    }

    for row in rows:
        mapped = map_bigquery_row(row)
        parsed = cn_patent_fetcher.parse_cn_patent_record(mapped)
        expanded = cn_patent_fetcher.expand_patent_rows(parsed)
        for key in expanded_rows:
            expanded_rows[key].extend(expanded.get(key, []))

    table_specs = (
        (cn_patent_fetcher.CH_TABLE, expanded_rows["patents"], cn_patent_fetcher.PATENT_COLUMNS),
        (
            cn_patent_fetcher.CH_APPLICATIONS_TABLE,
            expanded_rows["applications"],
            cn_patent_fetcher.APPLICATION_COLUMNS,
        ),
        (cn_patent_fetcher.CH_INVENTORS_TABLE, expanded_rows["inventors"], cn_patent_fetcher.INVENTOR_COLUMNS),
        (cn_patent_fetcher.CH_ASSIGNEES_TABLE, expanded_rows["assignees"], cn_patent_fetcher.ASSIGNEE_COLUMNS),
        (cn_patent_fetcher.CH_ABSTRACTS_TABLE, expanded_rows["abstracts"], cn_patent_fetcher.ABSTRACT_COLUMNS),
        (cn_patent_fetcher.CH_IPC_TABLE, expanded_rows["ipc"], cn_patent_fetcher.IPC_COLUMNS),
    )

    for table_name, table_rows, columns in table_specs:
        if not table_rows:
            continue
        cn_patent_fetcher.insert_table(ch_client, table_name, table_rows, columns, batch_size=batch_size)

    return len(expanded_rows["patents"])


def build_source_table_id(args: argparse.Namespace) -> str:
    return _strip(getattr(args, "source_table", "")) or PUBLICATIONS_TABLE


def build_staging_table_id(client: Any, args: argparse.Namespace) -> str:
    project = _strip(getattr(client, "project", ""))
    dataset_id = _strip(args.staging_dataset)
    table_id = _strip(args.staging_table)
    if project:
        return f"{project}.{dataset_id}.{table_id}"
    return f"{dataset_id}.{table_id}"


def build_temp_staging_table_name(args: argparse.Namespace, start_date: Any, end_date: Any) -> str:
    prefix = _strip(getattr(args, "temp_staging_prefix", "")) or "cn_publications_window"
    start_key = parse_date_object(start_date).strftime("%Y%m%d")
    end_key = parse_date_object(end_date).strftime("%Y%m%d")
    return f"{prefix}_{start_key}_{end_key}"


def build_temp_staging_table_id(client: Any, args: argparse.Namespace, start_date: Any, end_date: Any) -> str:
    staging_args = argparse.Namespace(
        staging_dataset=args.staging_dataset,
        staging_table=build_temp_staging_table_name(args, start_date, end_date),
    )
    return build_staging_table_id(client, staging_args)


def delete_bigquery_table(client: Any, table_id: str) -> None:
    client.delete_table(table_id, not_found_ok=True)


def build_create_staging_query(
    target_table: str,
    country: Any,
    start_date: Any = None,
    end_date: Any = None,
) -> str:
    select_columns = ",\n    ".join(PUBLICATION_COLUMNS)
    query_lines = [
        f"CREATE OR REPLACE TABLE `{target_table}` AS",
        "SELECT",
        f"    {select_columns}",
        f"FROM `{PUBLICATIONS_TABLE}`",
        "WHERE country_code = @country",
    ]
    if start_date not in (None, ""):
        query_lines.append("  AND publication_date >= @start_date")
    if end_date not in (None, ""):
        query_lines.append("  AND publication_date <= @end_date")
    return "\n".join(query_lines)


def create_staging_table(
    client: Any,
    dataset_id: str,
    table_id: str,
    country: str,
    start_date: Any = None,
    end_date: Any = None,
    max_bytes_billed: Any = None,
    progress_file: str = "",
) -> str:
    bigquery_module = _optional_bigquery()
    dataset = client.dataset(dataset_id)
    client.create_dataset(dataset, exists_ok=True)
    args = argparse.Namespace(staging_dataset=dataset_id, staging_table=table_id)
    target_table = build_staging_table_id(client, args)
    sql = build_create_staging_query(target_table, country, start_date, end_date)
    job_config_kwargs = {
        "query_parameters": _query_parameters(bigquery_module, country, start_date, end_date),
    }
    if max_bytes_billed not in (None, ""):
        job_config_kwargs["maximum_bytes_billed"] = int(max_bytes_billed)

    job_config = bigquery_module.QueryJobConfig(**job_config_kwargs)
    job = client.query(sql, job_config=job_config)
    write_progress(
        progress_file,
        phase="create_staging",
        status="running",
        country=country,
        target_table=target_table,
        bigquery_job_id=_strip(getattr(job, "job_id", "")),
    )
    job.result()
    return target_table


def iter_batches(rows: Iterable[Any], batch_size: int) -> Iterator[List[Any]]:
    """Yield rows in bounded batches."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    batch: List[Any] = []
    for row in rows:
        batch.append(row)
        if len(batch) == batch_size:
            yield batch
            batch = []

    if batch:
        yield batch


def stream_query_rows(
    client: Any,
    sql: str,
    country: str,
    start_date: Any = None,
    end_date: Any = None,
    page_size: int = 1000,
    max_bytes_billed: Any = None,
) -> Any:
    """Run a parameterized Google Patents query and stream paged results."""
    bigquery_module = _optional_bigquery()
    job_config_kwargs = {
        "query_parameters": _query_parameters(bigquery_module, country, start_date, end_date),
    }
    if max_bytes_billed not in (None, ""):
        job_config_kwargs["maximum_bytes_billed"] = int(max_bytes_billed)
    job_config = bigquery_module.QueryJobConfig(**job_config_kwargs)
    job = client.query(sql, job_config=job_config)
    return job.result(page_size=page_size)


def main(argv: Any = None) -> int:
    return run(argv)


def parse_date_param(value: Any) -> int:
    """Parse YYYY-MM-DD or YYYYMMDD values into BigQuery INT64 dates."""
    text = _strip(value)
    if len(text) == 8 and text.isdigit():
        datetime.strptime(text, "%Y%m%d")
        return int(text)

    return int(datetime.strptime(text, "%Y-%m-%d").strftime("%Y%m%d"))


def parse_date_object(value: Any) -> date:
    """Parse YYYY-MM-DD or YYYYMMDD values into a date object."""
    text = _strip(value)
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.strptime(text, "%Y-%m-%d").date()


def resolve_window_bounds(args: argparse.Namespace) -> tuple:
    start = _strip(getattr(args, "start_date", "")) or DEFAULT_WINDOW_START_DATE
    end = _strip(getattr(args, "end_date", "")) or datetime.now().date().isoformat()
    return parse_date_object(start).isoformat(), parse_date_object(end).isoformat()


def iter_date_windows(start_date: Any, end_date: Any, window_days: int) -> Iterator[tuple]:
    """Yield inclusive ISO date windows."""
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    current = parse_date_object(start_date)
    final = parse_date_object(end_date)
    if current > final:
        raise ValueError("start_date must be on or before end_date")

    delta = timedelta(days=window_days - 1)
    while current <= final:
        window_end = min(current + delta, final)
        yield current.isoformat(), window_end.isoformat()
        current = window_end + timedelta(days=1)


def window_progress_key(start_date: Any, end_date: Any) -> str:
    return f"{parse_date_object(start_date).isoformat()}:{parse_date_object(end_date).isoformat()}"


def build_publications_query(
    country: Any,
    start_date: Any = None,
    end_date: Any = None,
    limit: Any = None,
    source_table: Any = None,
) -> str:
    """Build a parameterized SQL query for Google Patents publications."""
    select_columns = ",\n    ".join(PUBLICATION_COLUMNS)
    table_id = _strip(source_table) or PUBLICATIONS_TABLE
    query_lines = [
        "SELECT",
        f"    {select_columns}",
        f"FROM `{table_id}`",
        "WHERE country_code = @country",
    ]

    if start_date not in (None, ""):
        query_lines.append("  AND publication_date >= @start_date")
    if end_date not in (None, ""):
        query_lines.append("  AND publication_date <= @end_date")
    if limit not in (None, ""):
        query_lines.append(f"LIMIT {int(limit)}")

    return "\n".join(query_lines)


def yyyymmdd_to_iso(value: Any) -> str:
    """Convert BigQuery integer dates like 20240430 into ISO date strings."""
    if value in (None, "", 0):
        return ""

    text = str(value).strip()
    if not text or text == "0" or len(text) != 8 or not text.isdigit():
        return ""

    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def localized_text(value: Any) -> str:
    """Return Chinese localized text when available, else the first text value."""
    items = _as_list(value)
    fallback = ""

    for item in items:
        text = _strip(_field(item, "text"))
        if not text:
            continue
        if not fallback:
            fallback = text
        if _strip(_field(item, "language")).lower() == "zh":
            return text

    return fallback


def names_from_list(value: Any) -> List[str]:
    """Extract repeated string names from BigQuery values and common variants."""
    return _strings_from_list(value, ("name", "text", "value"))


def codes_from_list(value: Any) -> List[str]:
    """Extract classification codes from repeated records or strings."""
    return _strings_from_list(value, ("code", "text", "value"))


def map_bigquery_row(row: Any) -> Dict[str, Any]:
    """Map a Google Patents BigQuery row into parse_cn_patent_record input."""
    record = _row_to_dict(row)
    publication_number = _normalize_google_number(record.get("publication_number"))
    application_number = _normalize_google_number(record.get("application_number"))
    title = localized_text(record.get("title_localized"))
    abstract = localized_text(record.get("abstract_localized"))
    inventors = names_from_list(record.get("inventor"))
    assignees = names_from_list(record.get("assignee"))
    ipc_codes = codes_from_list(record.get("ipc"))
    cpc_codes = codes_from_list(record.get("cpc"))

    jsonable_record = _to_jsonable(record)

    return {
        "source": SOURCE_NAME,
        "publication_number": publication_number,
        "application_number": application_number,
        "title": title,
        "abstract": abstract,
        "专利名称": title,
        "摘要": abstract,
        "publication_date": yyyymmdd_to_iso(record.get("publication_date")),
        "application_date": yyyymmdd_to_iso(record.get("filing_date")),
        "grant_date": yyyymmdd_to_iso(record.get("grant_date")),
        "inventors": inventors,
        "assignees": assignees,
        "ipc_codes": ipc_codes,
        "cpc_codes": cpc_codes,
        "发明人": "; ".join(inventors),
        "申请人": "; ".join(assignees),
        "IPC": "; ".join(ipc_codes),
        "CPC": "; ".join(cpc_codes),
        "family_id": _strip(record.get("family_id")),
        "country": _strip(record.get("country_code")),
        "source_url": f"https://patents.google.com/patent/{publication_number}"
        if publication_number
        else "",
        "raw_json": json.dumps(jsonable_record, ensure_ascii=False, sort_keys=True, default=str),
    }


def _normalize_google_number(value: Any) -> str:
    return _strip(value).replace("-", "")


def _strings_from_list(value: Any, keys: Any) -> List[str]:
    results: List[str] = []
    for item in _flatten(value):
        text = _extract_text(item, keys)
        if text:
            results.append(text)
    return results


def _extract_text(value: Any, keys: Any) -> str:
    if isinstance(value, dict):
        for key in keys:
            text = _strip(value.get(key))
            if text:
                return text
        return ""

    if hasattr(value, "get"):
        for key in keys:
            try:
                text = _strip(value.get(key))
            except (AttributeError, TypeError):
                text = ""
            if text:
                return text

    return _strip(value)


def _flatten(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        flattened: List[Any] = []
        for item in value:
            flattened.extend(_flatten(item))
        return flattened
    return [value]


def _as_list(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _field(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    if hasattr(value, "get"):
        try:
            return value.get(key)
        except (AttributeError, TypeError):
            return ""
    return getattr(value, key, "")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "items"):
        return dict(row.items())
    return {column: getattr(row, column, "") for column in PUBLICATION_COLUMNS}


class _LocalScalarQueryParameter:
    def __init__(self, name: str, type_: str, value: Any):
        self.name = name
        self.type_ = type_
        self.value = value


class _LocalQueryJobConfig:
    def __init__(
        self,
        query_parameters: List[Any] = None,
        dry_run: bool = False,
        use_query_cache: bool = True,
        maximum_bytes_billed: Any = None,
    ):
        self.query_parameters = query_parameters or []
        self.dry_run = dry_run
        self.use_query_cache = use_query_cache
        self.maximum_bytes_billed = maximum_bytes_billed


class _LocalBigQuery:
    ScalarQueryParameter = _LocalScalarQueryParameter
    QueryJobConfig = _LocalQueryJobConfig


def _optional_bigquery() -> Any:
    try:
        return _load_bigquery()
    except RuntimeError:
        return _LocalBigQuery


def require_bigquery() -> Any:
    return _load_bigquery()


def _load_bigquery() -> Any:
    try:
        from google.cloud import bigquery as bigquery_module
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required for live Google Patents fetching. "
            "Install it in the project environment or run with the existing venv."
        ) from exc
    return bigquery_module


def _query_parameters(bigquery_module: Any, country: str, start_date: Any = None, end_date: Any = None) -> List[Any]:
    query_parameters = [
        bigquery_module.ScalarQueryParameter("country", "STRING", country),
    ]

    if start_date not in (None, ""):
        query_parameters.append(
            bigquery_module.ScalarQueryParameter("start_date", "INT64", parse_date_param(start_date))
        )
    if end_date not in (None, ""):
        query_parameters.append(
            bigquery_module.ScalarQueryParameter("end_date", "INT64", parse_date_param(end_date))
        )

    return query_parameters


def _emit(message: str, log_file: str = "") -> None:
    print(message)
    if not log_file:
        return

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def write_progress(progress_file: str = "", **fields: Any) -> None:
    """Merge progress fields into a JSON checkpoint file."""
    if not progress_file:
        return

    progress: Dict[str, Any] = {}
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            if isinstance(existing, dict):
                progress.update(existing)
        except (OSError, json.JSONDecodeError):
            progress = {}

    progress.update({key: _to_jsonable(value) for key, value in fields.items() if value is not None})
    progress["updated_at"] = datetime.now().isoformat(timespec="seconds")
    progress["pid"] = os.getpid()

    progress_dir = os.path.dirname(progress_file)
    if progress_dir:
        os.makedirs(progress_dir, exist_ok=True)
    tmp_path = f"{progress_file}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(progress, handle, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        handle.write("\n")
    os.replace(tmp_path, progress_file)


def load_progress_file(progress_file: str = "") -> Dict[str, Any]:
    if not progress_file or not os.path.exists(progress_file):
        return {}
    try:
        with open(progress_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if hasattr(value, "items"):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_to_jsonable(item) for item in sorted(value, key=lambda item: str(item))]
    return value


def _strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


if __name__ == "__main__":
    raise SystemExit(main())
