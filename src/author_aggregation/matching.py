import json
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from typing import Dict, Iterable, List, Tuple

from .models import AuthorIdentityEdge, AuthorObservation, PaperIdentityEdge
from .normalization import stable_u64


TITLE_YEAR_MIN_LENGTH = 30


def canonical_pair(
    left: AuthorObservation, right: AuthorObservation
) -> Tuple[AuthorObservation, AuthorObservation]:
    left_key = (left.source, left.source_paper_id)
    right_key = (right.source, right.source_paper_id)
    return (left, right) if left_key <= right_key else (right, left)


def unique_papers(observations: Iterable[AuthorObservation]) -> Dict[Tuple[str, str], AuthorObservation]:
    papers = {}
    for observation in observations:
        key = (observation.source, observation.source_paper_id)
        papers.setdefault(key, observation)
    return papers


def build_paper_identity_edges(
    observations: Iterable[AuthorObservation],
    created_at: datetime,
    pipeline_run_id: str,
) -> List[PaperIdentityEdge]:
    papers = list(unique_papers(observations).values())
    grouped = defaultdict(list)

    for paper in papers:
        if paper.doi:
            grouped[("doi_exact", paper.doi)].append(paper)
        if paper.arxiv_id:
            grouped[("arxiv_id_exact", paper.arxiv_id)].append(paper)
        if (
            not paper.doi
            and not paper.arxiv_id
            and len(paper.normalized_title) >= TITLE_YEAR_MIN_LENGTH
            and paper.publication_year
        ):
            grouped[("title_year_exact", f"{paper.normalized_title}\x1f{paper.publication_year}")].append(paper)

    edges = {}
    priority = {"doi_exact": 1, "arxiv_id_exact": 2, "title_year_exact": 3}
    confidence = {"doi_exact": 1.0, "arxiv_id_exact": 1.0, "title_year_exact": 0.95}

    for (match_type, match_value), group in grouped.items():
        by_source = defaultdict(list)
        for paper in group:
            by_source[paper.source].append(paper)
        if len(by_source) < 2:
            continue

        for left_source, right_source in combinations(sorted(by_source), 2):
            for raw_left in by_source[left_source]:
                for raw_right in by_source[right_source]:
                    left, right = canonical_pair(raw_left, raw_right)
                    pair_key = (left.source, left.source_paper_id, right.source, right.source_paper_id)
                    existing = edges.get(pair_key)
                    if existing and priority[existing.match_type] <= priority[match_type]:
                        continue
                    evidence = json.dumps({"match_value": match_value}, ensure_ascii=False, sort_keys=True)
                    edge_id = stable_u64(
                        "paper",
                        left.source,
                        left.source_paper_id,
                        right.source,
                        right.source_paper_id,
                        match_type,
                    )
                    edges[pair_key] = PaperIdentityEdge(
                        edge_id=edge_id,
                        left_source=left.source,
                        left_source_paper_id=left.source_paper_id,
                        right_source=right.source,
                        right_source_paper_id=right.source_paper_id,
                        match_type=match_type,
                        confidence=confidence[match_type],
                        evidence=evidence,
                        created_at=created_at,
                        pipeline_run_id=pipeline_run_id,
                    )

    return list(edges.values())


def build_author_identity_edges(
    observations: Iterable[AuthorObservation],
    paper_edges: Iterable[PaperIdentityEdge],
    created_at: datetime,
    pipeline_run_id: str,
) -> List[AuthorIdentityEdge]:
    by_paper = defaultdict(list)
    for observation in observations:
        by_paper[(observation.source, observation.source_paper_id)].append(observation)

    edges = []
    seen = set()
    for paper_edge in paper_edges:
        left_authors = by_paper[(paper_edge.left_source, paper_edge.left_source_paper_id)]
        right_authors = by_paper[(paper_edge.right_source, paper_edge.right_source_paper_id)]
        for left in left_authors:
            for right in right_authors:
                if left.author_rank != right.author_rank:
                    continue
                if left.normalized_author_name == "" or left.normalized_author_name != right.normalized_author_name:
                    continue
                pair = tuple(sorted([left.observation_id, right.observation_id]))
                if pair in seen:
                    continue
                seen.add(pair)
                evidence = json.dumps(
                    {
                        "paper_edge_id": paper_edge.edge_id,
                        "author_rank": left.author_rank,
                        "normalized_author_name": left.normalized_author_name,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                edge_id = stable_u64("author", pair[0], pair[1], paper_edge.edge_id)
                edges.append(
                    AuthorIdentityEdge(
                        edge_id=edge_id,
                        left_observation_id=pair[0],
                        right_observation_id=pair[1],
                        left_source=left.source,
                        right_source=right.source,
                        match_type="paper_edge_rank_name_exact",
                        paper_edge_id=paper_edge.edge_id,
                        confidence=1.0,
                        evidence=evidence,
                        created_at=created_at,
                        pipeline_run_id=pipeline_run_id,
                    )
                )
    return edges
