"""Streaming paper matcher for fast database writes using XML + CSrankings data.

Hybrid strategy:
- Uses XML data (title, authors, year, dblp_key) - no network requests needed
- Enriches with CSrankings data (ORCID, affiliation, homepage)
- Fast batch processing without external API calls
"""

from typing import Dict, Set, Any, Optional, List
from datetime import datetime
import pandas as pd
from .author_cache import ThreadSafeAuthorCache
from .checkpoint_manager import ThreadSafeCheckpointManager


class StreamingAuthorMatcher:
    """Fast author matcher using XML data + CSrankings enrichment.

    This component:
    - Processes papers from XML (no network requests)
    - Enriches author data with CSrankings information
    - Writes paper-author relationships to database in batches
    - Very fast: can process millions of papers
    """

    def __init__(
        self,
        author_cache: ThreadSafeAuthorCache,
        checkpoint_manager: ThreadSafeCheckpointManager,
        csrankings_data: pd.DataFrame,
        db_client,
        max_concurrent: int = 1,  # Not used for network, kept for compatibility
        batch_size: int = 1000  # Larger batch size for faster processing
    ):
        """Initialize the streaming author matcher.

        Args:
            author_cache: Thread-safe cache for paper-author mappings
            checkpoint_manager: Thread-safe checkpoint manager
            csrankings_data: DataFrame with CSrankings author information
            db_client: ClickHouse client for database writes
            max_concurrent: Not used (kept for API compatibility)
            batch_size: Batch size for database writes
        """
        self.author_cache = author_cache
        self.checkpoint_manager = checkpoint_manager
        self.db_client = db_client
        self.batch_size = batch_size

        # Build CSrankings lookup dictionary for fast access
        self._csrankings_lookup: Dict[str, Dict[str, Any]] = {}
        if csrankings_data is not None and not csrankings_data.empty:
            for _, row in csrankings_data.iterrows():
                name = row['name']
                self._csrankings_lookup[name] = {
                    'affiliation': row.get('affiliation', ''),
                    'homepage': row.get('homepage', ''),
                    'scholarid': row.get('scholarid', ''),
                    'orcid': row.get('orcid', '')
                }

        # Track processed papers
        self._processed_papers: Set[str] = set()

    def _get_csrankings_info(self, author_name: str) -> Dict[str, Any]:
        """Lookup author in CSrankings data.

        Args:
            author_name: Name of the author

        Returns:
            Dictionary with CSrankings info (homepage, scholar_id, affiliation, orcid)
        """
        return self._csrankings_lookup.get(author_name, {
            'affiliation': '',
            'homepage': '',
            'scholarid': '',
            'orcid': ''
        })

    def _process_single_paper(self, paper_data: Dict[str, Any]) -> List[tuple]:
        """Process a single paper: extract authors, merge with CSrankings data.

        Args:
            paper_data: Dictionary with paper_id (dblp_key), authors[], title, year

        Returns:
            List of tuples (database rows) for insertion
        """
        dblp_key = paper_data['paper_id']
        xml_authors = paper_data.get('authors', [])

        # Create rows for each author
        rows = []

        for idx, author_name in enumerate(xml_authors):
            # Get CSrankings info
            csrankings_info = self._get_csrankings_info(author_name)

            # Helper function to convert None to empty string
            def safe_str(value):
                return value if value is not None else ''

            # Helper function to ensure integer is safe for UInt8
            def safe_uint8(value, default=0):
                if value is None:
                    return default
                try:
                    ivalue = int(value)
                    # Clamp to 0-255 range
                    if ivalue < 0:
                        return 0
                    if ivalue > 255:
                        return 255
                    return ivalue
                except (ValueError, TypeError):
                    return default

            # Helper function to ensure integer is safe for UInt32
            def safe_uint32(value, default=0):
                if value is None:
                    return default
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return default

            # Build the row - must match table column order exactly
            # dblp_key, mdate, type, title, year, venue, venue_type, ccf_class,
            # author_pid, author_name, author_orcid, author_rank, author_role,
            # author_total_papers, author_profile_url, volume, number, pages,
            # publisher, doi, ee, dblp_url, institution, institution_confidence

            # Generate dblp_url from paper_id
            dblp_url = f"https://dblp.org/rec/{dblp_key}.html" if dblp_key else ''

            # Generate author_pid from paper_id and author rank (unique identifier)
            author_pid = f"{dblp_key}::{idx + 1}" if dblp_key else ''

            row = (
                safe_str(dblp_key),  # dblp_key
                '',  # mdate
                '',  # type
                safe_str(paper_data.get('title')),  # title
                safe_str(paper_data.get('year')),  # year
                safe_str(paper_data.get('venue')),  # venue (from XML)
                '',  # venue_type
                '',  # ccf_class
                author_pid,  # author_pid (generated from paper_id + rank)
                safe_str(author_name),  # author_name
                safe_str(csrankings_info.get('orcid')),  # author_orcid
                safe_uint8(idx + 1, 1),  # author_rank (ensure 1-255)
                '',  # author_role
                safe_uint32(0),  # author_total_papers
                safe_str(csrankings_info.get('homepage')),  # author_profile_url
                safe_str(paper_data.get('volume')),  # volume (from XML)
                safe_str(paper_data.get('number')),  # number (from XML)
                safe_str(paper_data.get('pages')),  # pages (from XML)
                safe_str(paper_data.get('publisher')),  # publisher (from XML)
                safe_str(paper_data.get('doi')),  # doi (from XML)
                safe_str(paper_data.get('ee')),  # ee (from XML)
                dblp_url,  # dblp_url
                safe_str(csrankings_info.get('affiliation')),  # institution
                1.0 if csrankings_info.get('affiliation') else 0.0  # institution_confidence
            )
            rows.append(row)

        return rows

    def _write_rows_batch(self, rows: List[tuple]) -> None:
        """Write multiple rows to database in a single batch.

        Args:
            rows: List of tuples with values in table column order
        """
        if not rows:
            return

        # ClickHouse insert with column names
        column_names = [
            'dblp_key', 'mdate', 'type', 'title', 'year', 'venue', 'venue_type', 'ccf_class',
            'author_pid', 'author_name', 'author_orcid', 'author_rank', 'author_role',
            'author_total_papers', 'author_profile_url', 'volume', 'number', 'pages',
            'publisher', 'doi', 'ee', 'dblp_url', 'institution', 'institution_confidence'
        ]

        self.db_client.insert('dblp', rows, column_names=column_names)

    def process_paper_batch(self, papers: List[Dict[str, Any]]) -> Dict[str, int]:
        """Process a batch of papers (very fast, no network calls).

        Args:
            papers: List of paper data dictionaries

        Returns:
            Dictionary with statistics (queried, written, failed)
        """
        stats = {
            'queried': 0,
            'written': 0,
            'failed': 0
        }

        if not papers:
            return stats

        # Process all papers (no threading needed, just CPU work)
        all_rows = []

        for paper in papers:
            dblp_key = paper.get('paper_id', 'unknown')
            try:
                rows = self._process_single_paper(paper)
                stats['queried'] += 1
                all_rows.extend(rows)

                # Mark paper as processed
                self._processed_papers.add(dblp_key)

            except Exception as e:
                print(f"Error processing paper {dblp_key}: {e}")
                stats['failed'] += 1

        # Write all rows in one batch
        if all_rows:
            self._write_rows_batch(all_rows)
            stats['written'] += len(all_rows)

        return stats

    def run(self, batch_size: int = 1000) -> Dict[str, int]:
        """Continuous loop processing papers from cache until no more remain.

        Very fast processing - no network calls.

        Args:
            batch_size: Number of papers to process per batch

        Returns:
            Final statistics dictionary
        """
        total_stats = {
            'total_queried': 0,
            'written_rows': 0,
            'failed_papers': 0
        }

        processed_count = 0
        batch_num = 0

        while True:
            # Get papers from cache
            papers_to_process = []

            # Collect unique paper IDs - directly access processed papers
            # to find unprocessed ones
            all_paper_ids = set()

            # Get all authors (including partially processed ones)
            with self.author_cache._lock:
                all_paper_ids = set(self.author_cache._paper_objects.keys()) - self._processed_papers

            if not all_paper_ids:
                # No more unprocessed papers
                break

            # Take next batch
            paper_ids = list(all_paper_ids)[:batch_size]

            if not paper_ids:
                break

            # Get complete paper objects
            papers_to_process = self.author_cache.get_paper_objects(set(paper_ids))

            # Process the batch
            batch_stats = self.process_paper_batch(papers_to_process)

            # Mark papers as processed
            for paper_id in paper_ids:
                self._processed_papers.add(paper_id)

            # Accumulate statistics
            total_stats['total_queried'] += batch_stats['queried']
            total_stats['written_rows'] += batch_stats['written']
            total_stats['failed_papers'] += batch_stats['failed']

            processed_count += batch_stats['queried']
            batch_num += 1

            # Print progress every 10 batches
            if batch_num % 10 == 0:
                progress_pct = (total_stats['total_queried'] / 8350000) * 100
                print(f"Progress: {progress_pct:.2f}% | Batch {batch_num} | "
                      f"Papers: {batch_stats['queried']}, Rows: {batch_stats['written']}")

            # Save checkpoint every 10000 papers
            if processed_count >= 10000:
                processed_authors_list = list(self.author_cache.get_processed_authors())
                self.checkpoint_manager.save_checkpoint({
                    'parsed_chunks': self.checkpoint_manager.get_parsed_chunks(),
                    'paper_progress': {
                        'total_queried': total_stats['total_queried'],
                        'written_rows': total_stats['written_rows']
                    },
                    'processed_authors': processed_authors_list,
                    'processed_papers': list(self._processed_papers),
                    'last_updated': datetime.now().isoformat()
                })
                processed_count = 0

        # Final checkpoint
        processed_authors_list = list(self.author_cache.get_processed_authors())
        self.checkpoint_manager.save_checkpoint({
            'parsed_chunks': self.checkpoint_manager.get_parsed_chunks(),
            'paper_progress': {
                'total_queried': total_stats['total_queried'],
                'written_rows': total_stats['written_rows']
            },
            'processed_authors': processed_authors_list,
            'processed_papers': list(self._processed_papers),
            'last_updated': datetime.now().isoformat()
        })

        return total_stats
