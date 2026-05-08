from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, Iterable, List

from .models import AuthorEntity, AuthorIdentityEdge, AuthorObservation
from .normalization import stable_u64


class UnionFind:
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left, right):
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def most_common_non_empty(values: Iterable[str]) -> str:
    counter = Counter(value for value in values if value)
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def build_author_entities(
    observations: Iterable[AuthorObservation],
    author_edges: Iterable[AuthorIdentityEdge],
    timestamp: datetime,
    pipeline_run_id: str,
) -> List[AuthorEntity]:
    observation_list = list(observations)
    if not observation_list:
        return []

    by_id: Dict[int, AuthorObservation] = {obs.observation_id: obs for obs in observation_list}
    union_find = UnionFind(by_id.keys())

    for edge in author_edges:
        if edge.left_observation_id in by_id and edge.right_observation_id in by_id:
            union_find.union(edge.left_observation_id, edge.right_observation_id)

    groups = defaultdict(list)
    for observation in observation_list:
        groups[union_find.find(observation.observation_id)].append(observation)

    entities: List[AuthorEntity] = []
    for group in groups.values():
        canonical = sorted(group, key=lambda obs: (-len(obs.author_name), obs.author_name))[0]
        years = [obs.publication_year for obs in group if obs.publication_year]
        source_author_ids = sorted(
            {f"{obs.source}:{obs.source_author_id}" for obs in group if obs.source_author_id}
        )
        source_papers = {(obs.source, obs.source_paper_id) for obs in group}
        sources = sorted({obs.source for obs in group})
        entity_id = stable_u64("entity", min(obs.observation_id for obs in group))
        entities.append(
            AuthorEntity(
                author_entity_id=entity_id,
                canonical_name=canonical.author_name,
                normalized_canonical_name=canonical.normalized_author_name,
                source_count=len(sources),
                observation_count=len(group),
                paper_count=len(source_papers),
                source_author_ids=source_author_ids,
                sources=sources,
                first_publication_year=min(years) if years else 0,
                last_publication_year=max(years) if years else 0,
                primary_institution_name=most_common_non_empty(obs.institution_name for obs in group),
                primary_country=most_common_non_empty(obs.institution_country for obs in group),
                created_at=timestamp,
                updated_at=timestamp,
                pipeline_run_id=pipeline_run_id,
            )
        )
    return entities
