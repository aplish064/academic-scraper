"""Tests for ThreadSafeAuthorCache."""

import pytest
import threading
from src.streaming.author_cache import ThreadSafeAuthorCache


class TestThreadSafeAuthorCache:
    """Test suite for ThreadSafeAuthorCache."""

    def test_add_single_paper(self):
        """Adding a paper stores it in cache."""
        cache = ThreadSafeAuthorCache()
        paper = {
            'paper_id': 'paper1',
            'authors': ['Alice', 'Bob']
        }

        cache.add_paper(paper)

        assert cache.get_papers_for_author('Alice') == {'paper1'}
        assert cache.get_papers_for_author('Bob') == {'paper1'}

    def test_add_multiple_papers_same_author(self):
        """Multiple papers by same author are aggregated."""
        cache = ThreadSafeAuthorCache()

        cache.add_paper({'paper_id': 'paper1', 'authors': ['Alice']})
        cache.add_paper({'paper_id': 'paper2', 'authors': ['Alice', 'Bob']})
        cache.add_paper({'paper_id': 'paper3', 'authors': ['Alice']})

        assert cache.get_papers_for_author('Alice') == {'paper1', 'paper2', 'paper3'}
        assert cache.get_papers_for_author('Bob') == {'paper2'}

    def test_mark_processed_prevents_requery(self):
        """Processed authors are not returned for query."""
        cache = ThreadSafeAuthorCache()

        cache.add_paper({'paper_id': 'paper1', 'authors': ['Alice', 'Bob']})
        cache.mark_processed('Alice')

        authors_to_query = cache.get_authors_to_query(batch_size=10)

        assert 'Alice' not in authors_to_query
        assert 'Bob' in authors_to_query
        assert len(authors_to_query) == 1

    def test_thread_safety_concurrent_adds(self):
        """Multiple threads can add papers concurrently without data races."""
        cache = ThreadSafeAuthorCache()
        num_threads = 10
        papers_per_thread = 100

        def add_papers(thread_id):
            for i in range(papers_per_thread):
                paper_id = f'paper_thread{thread_id}_id{i}'
                authors = [f'Author{thread_id}']
                cache.add_paper({'paper_id': paper_id, 'authors': authors})

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=add_papers, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Verify all papers were added
        stats = cache.get_stats()
        assert stats['total_authors'] == num_threads
        assert stats['total_papers'] == num_threads * papers_per_thread

        # Verify each thread's author has correct number of papers
        for i in range(num_threads):
            papers = cache.get_papers_for_author(f'Author{i}')
            assert len(papers) == papers_per_thread

    def test_get_authors_to_query_respects_batch_size(self):
        """get_authors_to_query returns at most batch_size authors."""
        cache = ThreadSafeAuthorCache()

        # Add 5 authors
        for i in range(5):
            cache.add_paper({'paper_id': f'paper{i}', 'authors': [f'Author{i}']})

        # Request batch of 3
        authors = cache.get_authors_to_query(batch_size=3)
        assert len(authors) == 3

        # Request batch of 10 (more than available)
        authors = cache.get_authors_to_query(batch_size=10)
        assert len(authors) == 5

    def test_is_processed_tracks_state(self):
        """is_processed returns True only after mark_processed."""
        cache = ThreadSafeAuthorCache()

        cache.add_paper({'paper_id': 'paper1', 'authors': ['Alice']})

        assert not cache.is_processed('Alice')
        assert not cache.is_processed('Bob')  # Unknown author

        cache.mark_processed('Alice')

        assert cache.is_processed('Alice')
        assert not cache.is_processed('Bob')
