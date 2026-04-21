"""Thread-safe cache for aggregating papers by author."""

from threading import Lock
from typing import Dict, Set


class ThreadSafeAuthorCache:
    """Thread-safe cache storing paper IDs grouped by author.

    This cache is used by the streaming DBLP fetcher to:
    - Aggregate papers by author as they're consumed from the XML parsing queue
    - Track which authors have been processed (queried against DBLP API)
    - Provide batches of unprocessed authors for concurrent querying
    """

    def __init__(self):
        """Initialize the cache with thread-safe data structures."""
        self._lock = Lock()
        self._author_to_papers: Dict[str, Set[str]] = {}
        self._processed_authors: Set[str] = set()
        self._total_papers = 0

    def add_paper(self, paper: dict) -> None:
        """Add a paper to the cache, updating author mappings.

        Args:
            paper: Dictionary containing 'paper_id' and 'authors' keys.
                   'authors' should be a list of author names.
        """
        paper_id = paper['paper_id']
        authors = paper['authors']

        with self._lock:
            self._total_papers += 1
            for author in authors:
                if author not in self._author_to_papers:
                    self._author_to_papers[author] = set()
                self._author_to_papers[author].add(paper_id)

    def get_authors_to_query(self, batch_size: int) -> Set[str]:
        """Get a batch of unprocessed authors to query.

        Args:
            batch_size: Maximum number of authors to return.

        Returns:
            Set of author names that haven't been processed yet, up to batch_size.
        """
        with self._lock:
            unprocessed = set(self._author_to_papers.keys()) - self._processed_authors
            # Convert to list to slice, then back to set
            unprocessed_list = list(unprocessed)[:batch_size]
            return set(unprocessed_list)

    def get_papers_for_author(self, author_name: str) -> Set[str]:
        """Get all paper IDs for a specific author.

        Args:
            author_name: Name of the author.

        Returns:
            Set of paper IDs (copy for thread safety).
        """
        with self._lock:
            if author_name in self._author_to_papers:
                # Return a copy to prevent external modification
                return set(self._author_to_papers[author_name])
            return set()

    def mark_processed(self, author_name: str) -> None:
        """Mark an author as processed (queried against DBLP).

        Args:
            author_name: Name of the author to mark as processed.
        """
        with self._lock:
            self._processed_authors.add(author_name)

    def is_processed(self, author_name: str) -> bool:
        """Check if an author has been processed.

        Args:
            author_name: Name of the author to check.

        Returns:
            True if the author has been marked as processed, False otherwise.
        """
        with self._lock:
            return author_name in self._processed_authors

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with keys:
            - total_authors: Total number of unique authors
            - total_papers: Total number of papers added
            - processed_count: Number of authors marked as processed
            - pending_count: Number of authors awaiting processing
        """
        with self._lock:
            return {
                'total_authors': len(self._author_to_papers),
                'total_papers': self._total_papers,
                'processed_count': len(self._processed_authors),
                'pending_count': len(self._author_to_papers) - len(self._processed_authors)
            }
