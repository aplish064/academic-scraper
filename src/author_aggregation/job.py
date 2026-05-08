import argparse
from datetime import datetime, timedelta
from typing import Dict, Iterable, List

from . import source_mappers
from .entities import build_author_entities
from .matching import build_author_identity_edges, build_paper_identity_edges
from .repository import AuthorAggregationRepository, SOURCE_CONFIG, create_clickhouse_client


DEFAULT_SOURCES = ["openalex", "semantic", "arxiv", "dblp"]
# Use 1970-01-02 to avoid timezone conversion underflow on DateTime(UInt32).
INITIAL_WATERMARK = datetime(1970, 1, 2, 0, 0, 0)

SOURCE_MAPPERS = {
    "openalex": source_mappers.map_openalex_row,
    "semantic": source_mappers.map_semantic_row,
    "arxiv": source_mappers.map_arxiv_row,
    "dblp": source_mappers.map_dblp_row,
}


def build_pipeline_run_id(now: datetime) -> str:
    return f"author_aggregation_{now.strftime('%Y%m%d_%H%M%S')}"


def normalize_datetime(value: datetime) -> datetime:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build conservative author aggregation tables")
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help="Create authors_db schema and seed field dictionary",
    )
    parser.add_argument(
        "--init-source-indexes",
        action="store_true",
        help="Add and materialize source-table skip indexes for aggregation watermarks",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction and matching without writing derived rows",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum source rows per source for smoke tests",
    )
    parser.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCES),
        help="Comma-separated source list",
    )
    parser.add_argument(
        "--overlap-days",
        type=int,
        default=2,
        help="Overlap days for date-granularity source watermarks",
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=24,
        help="Import-time window size per run; use 0 to disable windowing",
    )
    parser.add_argument(
        "--source-window-hours",
        default="",
        help="Comma-separated per-source window overrides, for example arxiv=168,semantic=0.25",
    )
    return parser.parse_args(argv)


class AuthorAggregationJob:
    def __init__(self, repository: AuthorAggregationRepository, pipeline_run_id: str):
        self.repository = repository
        self.pipeline_run_id = pipeline_run_id

    def init_schema(self) -> None:
        self.repository.create_schema()
        self.repository.seed_field_dictionary()

    def normalize_source_rows(self, source: str, rows: Iterable[dict], observed_at: datetime):
        mapper = SOURCE_MAPPERS[source]
        return [mapper(row, self.pipeline_run_id, observed_at) for row in rows]

    def resolve_source_watermark(self, source: str, ingest_state, fallback_watermark: datetime) -> datetime:
        _, current_watermark_field = SOURCE_CONFIG[source]
        if ingest_state and ingest_state.watermark_field == current_watermark_field:
            source_watermark = ingest_state.last_watermark
        else:
            source_watermark = fallback_watermark

        source_watermark = normalize_datetime(source_watermark)
        min_watermark = normalize_datetime(self.repository.get_min_watermark(source))
        if min_watermark and (source_watermark is None or source_watermark < min_watermark):
            source_watermark = min_watermark
        source_watermark = source_watermark or fallback_watermark
        next_watermark = normalize_datetime(self.repository.get_next_watermark(source, source_watermark))
        if next_watermark and next_watermark > source_watermark:
            return next_watermark
        return source_watermark

    def run(
        self,
        sources: List[str],
        timestamp: datetime,
        last_watermark: datetime = None,
        limit: int = None,
        overlap_days: int = 2,
        window_hours: float = 24,
        source_window_hours: Dict[str, float] = None,
        dry_run: bool = False,
        default_watermark: datetime = INITIAL_WATERMARK,
    ):
        effective_default_watermark = last_watermark or default_watermark
        observations = []
        observations_by_source = {}
        source_errors = {}
        successful_watermarks = {}
        source_start_watermarks = {}

        for source in sources:
            ingest_state = self.repository.get_ingest_state(source)
            source_watermark = self.resolve_source_watermark(
                source=source,
                ingest_state=ingest_state,
                fallback_watermark=effective_default_watermark,
            )
            effective_window_hours = (
                source_window_hours.get(source, window_hours) if source_window_hours else window_hours
            )
            window_end = None
            if effective_window_hours and effective_window_hours > 0:
                window_end = source_watermark + timedelta(hours=effective_window_hours)
            self.repository.upsert_ingest_state(
                source=source,
                last_watermark=source_watermark,
                last_run_id=self.pipeline_run_id,
                last_status="running",
                last_error="",
                updated_at=timestamp,
            )
            source_start_watermarks[source] = source_watermark

            try:
                source_rows = self.repository.fetch_source_rows(
                    source=source,
                    last_watermark=source_watermark,
                    limit=limit,
                    overlap_days=overlap_days,
                    window_end=window_end,
                )
                normalized_rows = self.normalize_source_rows(source=source, rows=source_rows, observed_at=timestamp)
                observations.extend(normalized_rows)
                observations_by_source[source] = len(normalized_rows)

                if window_end is None:
                    max_import_time = max(
                        (
                            normalize_datetime(row.source_import_time)
                            for row in normalized_rows
                            if row.source_import_time
                        ),
                        default=source_watermark,
                    )
                    next_watermark = max(source_watermark, max_import_time)
                else:
                    next_watermark = window_end
                successful_watermarks[source] = next_watermark
            except Exception as exc:
                observations_by_source[source] = 0
                source_errors[source] = str(exc)
                self.repository.upsert_ingest_state(
                    source=source,
                    last_watermark=source_watermark,
                    last_run_id=self.pipeline_run_id,
                    last_status="failed",
                    last_error=str(exc),
                    updated_at=timestamp,
                )

        try:
            metrics = self.run_from_observations(observations, timestamp=timestamp, dry_run=dry_run)
        except Exception as exc:
            for source in successful_watermarks:
                self.repository.upsert_ingest_state(
                    source=source,
                    last_watermark=source_start_watermarks[source],
                    last_run_id=self.pipeline_run_id,
                    last_status="failed",
                    last_error=str(exc),
                    updated_at=timestamp,
                )
            raise

        for source, next_watermark in successful_watermarks.items():
            self.repository.upsert_ingest_state(
                source=source,
                last_watermark=next_watermark,
                last_run_id=self.pipeline_run_id,
                last_status="success",
                last_error="",
                updated_at=timestamp,
            )
        metrics["observations_by_source"] = observations_by_source
        metrics["source_errors"] = source_errors
        return metrics

    def run_from_observations(self, observations, timestamp: datetime, dry_run: bool = False):
        paper_edges = build_paper_identity_edges(observations, timestamp, self.pipeline_run_id)
        author_edges = build_author_identity_edges(observations, paper_edges, timestamp, self.pipeline_run_id)
        entities = build_author_entities(observations, author_edges, timestamp, self.pipeline_run_id)

        if not dry_run:
            self.repository.insert_observations(observations)
            self.repository.insert_paper_edges(paper_edges)
            self.repository.insert_author_edges(author_edges)
            self.repository.insert_author_entities(entities)

        return {
            "observations": len(observations),
            "paper_edges": len(paper_edges),
            "author_edges": len(author_edges),
            "entities": len(entities),
            "dry_run": dry_run,
        }


def parse_sources(value: str) -> List[str]:
    requested = [part.strip().lower() for part in value.split(",") if part.strip()]
    unique_sources = []
    seen = set()
    for source in requested:
        if source not in seen:
            unique_sources.append(source)
            seen.add(source)

    unknown_sources = [source for source in unique_sources if source not in SOURCE_MAPPERS]
    if unknown_sources:
        raise ValueError(f"unknown sources: {', '.join(unknown_sources)}")
    return unique_sources or list(DEFAULT_SOURCES)


def parse_source_window_hours(value: str) -> Dict[str, float]:
    if not value.strip():
        return {}

    overrides = {}
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"invalid source window override: {item}")
        source, hours_text = [piece.strip().lower() for piece in item.split("=", 1)]
        if source not in SOURCE_MAPPERS:
            raise ValueError(f"unknown source in window override: {source}")
        try:
            hours = float(hours_text)
        except ValueError as exc:
            raise ValueError(f"invalid window hours for source {source}: {hours_text}") from exc
        if hours < 0:
            raise ValueError(f"window hours must be non-negative for source {source}")
        overrides[source] = hours
    return overrides


def main(argv=None) -> int:
    args = parse_args(argv)
    now = datetime.now()
    repo = AuthorAggregationRepository(create_clickhouse_client())
    job = AuthorAggregationJob(repository=repo, pipeline_run_id=build_pipeline_run_id(now))

    if args.init_schema:
        job.init_schema()
        print("authors_db schema initialized")
        return 0

    if args.init_source_indexes:
        repo.ensure_source_watermark_indexes(materialize=True)
        print("source watermark indexes initialized")
        return 0

    try:
        selected_sources = parse_sources(args.sources)
        source_window_hours = parse_source_window_hours(args.source_window_hours)
    except ValueError as exc:
        print(str(exc))
        return 2

    metrics = job.run(
        sources=selected_sources,
        timestamp=now,
        limit=args.limit,
        overlap_days=args.overlap_days,
        window_hours=args.window_hours,
        source_window_hours=source_window_hours,
        dry_run=args.dry_run,
    )
    print(f"run_id={job.pipeline_run_id} dry_run={metrics['dry_run']}")
    print(
        "observations={observations} paper_edges={paper_edges} "
        "author_edges={author_edges} entities={entities}".format(**metrics)
    )
    for source in selected_sources:
        count = metrics["observations_by_source"].get(source, 0)
        print(f"observations.{source}={count}")
    for source in selected_sources:
        if source in metrics["source_errors"]:
            print(f"error.{source}={metrics['source_errors'][source]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
