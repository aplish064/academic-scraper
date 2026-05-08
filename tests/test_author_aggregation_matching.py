import unittest
from datetime import date, datetime

from src.author_aggregation.matching import build_author_identity_edges, build_paper_identity_edges
from src.author_aggregation.models import AuthorObservation


NOW = datetime(2026, 5, 7, 12, 0, 0)
RUN_ID = "run-test"


def obs(
    source,
    paper_id,
    observation_id,
    rank,
    name,
    doi="",
    arxiv_id="",
    title="A Conservative Matching Paper",
    year=2026,
):
    return AuthorObservation(
        observation_id=observation_id,
        source=source,
        source_row_key=f"{source}:{paper_id}:{rank}:{name}",
        source_paper_id=paper_id,
        source_author_id=f"{source}-author-{rank}",
        author_name=name,
        normalized_author_name=name.lower(),
        author_rank=rank,
        author_role="first" if rank == 1 else "other",
        doi=doi,
        arxiv_id=arxiv_id,
        dblp_key=paper_id if source == "dblp" else "",
        semantic_id=paper_id if source == "semantic" else "",
        openalex_id=paper_id if source == "openalex" else "",
        title=title,
        normalized_title=title.lower(),
        publication_date=date(year, 1, 1),
        publication_year=year,
        venue="Journal",
        institution_id="",
        institution_name="",
        institution_country="",
        raw_affiliation="",
        citation_count=0,
        fwci=0.0,
        primary_topic="",
        ccf_class="",
        source_import_time=NOW,
        observed_at=NOW,
        pipeline_run_id=RUN_ID,
    )


class MatchingTests(unittest.TestCase):
    def test_paper_edge_uses_doi_exact(self):
        observations = [
            obs("openalex", "W1", 1, 1, "alice", doi="10.1/test"),
            obs("semantic", "S1", 2, 1, "alice", doi="10.1/test"),
        ]
        edges = build_paper_identity_edges(observations, NOW, RUN_ID)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].match_type, "doi_exact")
        self.assertEqual(edges[0].confidence, 1.0)

    def test_paper_edge_uses_arxiv_id_exact(self):
        observations = [
            obs("arxiv", "2401.1", 1, 1, "alice", arxiv_id="2401.1", doi=""),
            obs("semantic", "S1", 2, 1, "alice", arxiv_id="2401.1", doi=""),
        ]
        edges = build_paper_identity_edges(observations, NOW, RUN_ID)
        self.assertEqual(edges[0].match_type, "arxiv_id_exact")

    def test_title_year_edge_requires_long_title(self):
        short = [
            obs("openalex", "W1", 1, 1, "alice", title="Short title", doi=""),
            obs("dblp", "D1", 2, 1, "alice", title="Short title", doi=""),
        ]
        self.assertEqual(build_paper_identity_edges(short, NOW, RUN_ID), [])

    def test_paper_edge_skips_single_source_groups(self):
        observations = [
            obs("semantic", f"S{index}", index, 1, "alice", doi="10.1/shared")
            for index in range(1, 100)
        ]
        self.assertEqual(build_paper_identity_edges(observations, NOW, RUN_ID), [])

    def test_author_edge_requires_same_rank_and_name(self):
        left = obs("openalex", "W1", 1, 1, "alice", doi="10.1/test")
        right = obs("semantic", "S1", 2, 1, "alice", doi="10.1/test")
        paper_edges = build_paper_identity_edges([left, right], NOW, RUN_ID)
        author_edges = build_author_identity_edges([left, right], paper_edges, NOW, RUN_ID)
        self.assertEqual(len(author_edges), 1)
        self.assertEqual(author_edges[0].match_type, "paper_edge_rank_name_exact")

    def test_author_edge_rejects_rank_mismatch(self):
        left = obs("openalex", "W1", 1, 1, "alice", doi="10.1/test")
        right = obs("semantic", "S1", 2, 2, "alice", doi="10.1/test")
        paper_edges = build_paper_identity_edges([left, right], NOW, RUN_ID)
        author_edges = build_author_identity_edges([left, right], paper_edges, NOW, RUN_ID)
        self.assertEqual(author_edges, [])

    def test_author_edge_rejects_name_mismatch(self):
        left = obs("openalex", "W1", 1, 1, "alice", doi="10.1/test")
        right = obs("semantic", "S1", 2, 1, "bob", doi="10.1/test")
        paper_edges = build_paper_identity_edges([left, right], NOW, RUN_ID)
        author_edges = build_author_identity_edges([left, right], paper_edges, NOW, RUN_ID)
        self.assertEqual(author_edges, [])


if __name__ == "__main__":
    unittest.main()
