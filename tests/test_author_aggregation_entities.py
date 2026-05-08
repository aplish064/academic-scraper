import unittest
from datetime import date, datetime

from src.author_aggregation.entities import build_author_entities
from src.author_aggregation.models import AuthorIdentityEdge, AuthorObservation


NOW = datetime(2026, 5, 7, 12, 0, 0)
RUN_ID = "run-test"


def obs(observation_id, source, paper_id, name, year, source_author_id=""):
    return AuthorObservation(
        observation_id=observation_id,
        source=source,
        source_row_key=f"{source}:{paper_id}:1:{name}",
        source_paper_id=paper_id,
        source_author_id=source_author_id,
        author_name=name,
        normalized_author_name=name.lower(),
        author_rank=1,
        author_role="first",
        doi="",
        arxiv_id="",
        dblp_key=paper_id if source == "dblp" else "",
        semantic_id=paper_id if source == "semantic" else "",
        openalex_id=paper_id if source == "openalex" else "",
        title="Paper",
        normalized_title="paper",
        publication_date=date(year, 1, 1),
        publication_year=year,
        venue="Journal",
        institution_id="",
        institution_name="Example University" if source == "openalex" else "",
        institution_country="US" if source == "openalex" else "",
        raw_affiliation="",
        citation_count=0,
        fwci=0,
        primary_topic="",
        ccf_class="",
        source_import_time=NOW,
        observed_at=NOW,
        pipeline_run_id=RUN_ID,
    )


def edge(left_id, right_id):
    return AuthorIdentityEdge(
        edge_id=left_id + right_id,
        left_observation_id=left_id,
        right_observation_id=right_id,
        left_source="openalex",
        right_source="semantic",
        match_type="paper_edge_rank_name_exact",
        paper_edge_id=1,
        confidence=1.0,
        evidence="{}",
        created_at=NOW,
        pipeline_run_id=RUN_ID,
    )


class EntityTests(unittest.TestCase):
    def test_unmatched_observation_gets_single_entity(self):
        entities = build_author_entities([obs(1, "arxiv", "A1", "Alice", 2020)], [], NOW, RUN_ID)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].observation_count, 1)
        self.assertEqual(entities[0].canonical_name, "Alice")

    def test_connected_observations_share_entity(self):
        observations = [
            obs(1, "openalex", "W1", "Alice", 2020, "A1"),
            obs(2, "semantic", "S1", "Alice", 2021, "S1"),
            obs(3, "dblp", "D1", "Bob", 2022, "pid/1"),
        ]
        entities = build_author_entities(observations, [edge(1, 2)], NOW, RUN_ID)
        sizes = sorted(entity.observation_count for entity in entities)
        self.assertEqual(sizes, [1, 2])
        alice = [entity for entity in entities if entity.observation_count == 2][0]
        self.assertEqual(alice.source_count, 2)
        self.assertEqual(alice.first_publication_year, 2020)
        self.assertEqual(alice.last_publication_year, 2021)
        self.assertIn("openalex:A1", alice.source_author_ids)


if __name__ == "__main__":
    unittest.main()
