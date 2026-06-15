"""Command-line interface for the Academic CV Builder."""

from __future__ import annotations

import argparse

from src.cv_builder.config import get_config
from src.cv_builder.crossref_client import CrossrefClient
from src.cv_builder.openalex_client import OpenAlexClient
from src.cv_builder.orcid_client import OrcidClient
from src.cv_builder.orcid_resolver import OrcidResolver
from src.cv_builder.repository import CvRepository
from src.cv_builder.runner import CvBuildRunner
from src.cv_builder.semantic_scholar_client import SemanticScholarClient
from src.cv_builder.semantic_scholar_resolver import SemanticScholarResolver


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_repository():
    config = get_config()
    return config, CvRepository(config)


def build_runner(repository, config):
    orcid_client = OrcidClient(config)
    semantic_client = SemanticScholarClient(config)
    return CvBuildRunner(
        repository=repository,
        openalex_client=OpenAlexClient(config),
        orcid_client=orcid_client,
        crossref_client=CrossrefClient(config),
        orcid_resolver=OrcidResolver(orcid_client),
        semantic_resolver=SemanticScholarResolver(semantic_client),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build academic CV tables from OpenAlex seeds.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-schema")

    init_queue = subparsers.add_parser("init-queue")
    init_queue.add_argument("--limit", type=positive_int, default=1000)

    process_author = subparsers.add_parser("process-author")
    process_author.add_argument("openalex_author_id")
    process_author.add_argument("--work-limit", type=positive_int, default=200)

    process_next = subparsers.add_parser("process-next")
    process_next.add_argument("--work-limit", type=positive_int, default=200)
    process_next.add_argument("--count", type=positive_int, default=1)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config, repository = build_repository()

    if args.command == "init-schema":
        repository.init_schema()
        print(f"initialized {config.cv_database}")
        return 0

    if args.command == "init-queue":
        repository.init_schema()
        queued_count = repository.enqueue_authors_from_openalex(args.limit)
        print(f"queued {queued_count} authors")
        return 0

    runner = build_runner(repository, config)

    if args.command == "process-author":
        person_id = runner.process_author(
            args.openalex_author_id,
            work_limit=args.work_limit,
            already_processing=False,
        )
        print(f"processed {args.openalex_author_id} -> {person_id}")
        return 0

    if args.command == "process-next":
        processed_count = 0
        for _ in range(args.count):
            author_id = repository.next_pending_author()
            if not author_id:
                if processed_count == 0:
                    print("no pending authors")
                break

            person_id = runner.process_author(
                author_id,
                work_limit=args.work_limit,
                already_processing=True,
            )
            processed_count += 1
            print(f"processed {author_id} -> {person_id}")

        if processed_count:
            print(f"processed_count {processed_count}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
