"""Streaming author matcher for concurrent DBLP API queries and database writes."""

import requests
from typing import Dict, Set, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import pandas as pd
from .author_cache import ThreadSafeAuthorCache
from .checkpoint_manager import ThreadSafeCheckpointManager


class StreamingAuthorMatcher:
    """Concurrent author matcher that queries DBLP API and writes to database.

    This component:
    - Queries DBLP author API concurrently (100 parallel requests)
    - Enriches author data with CSrankings information
    - Writes authors to database in batches
    - Manages checkpointing for crash recovery
    """

    DBLP_API_URL = "https://dblp.org/search/author/api"

    def __init__(
        self,
        author_cache: ThreadSafeAuthorCache,
        checkpoint_manager: ThreadSafeCheckpointManager,
        csrankings_data: pd.DataFrame,
        db_client,
        dblp_proxy: Optional[str] = None,
        max_concurrent: int = 100,
        batch_size: int = 100
    ):
        """Initialize the streaming author matcher.

        Args:
            author_cache: Thread-safe cache for paper-author mappings
            checkpoint_manager: Thread-safe checkpoint manager
            csrankings_data: DataFrame with CSrankings author information
            db_client: ClickHouse client for database writes
            dblp_proxy: Optional proxy for DBLP API requests
            max_concurrent: Maximum number of concurrent API requests
            batch_size: Batch size for database writes
        """
        self.author_cache = author_cache
        self.checkpoint_manager = checkpoint_manager
        self.db_client = db_client
        self.dblp_proxy = dblp_proxy
        self.max_concurrent = max_concurrent
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

    def _query_author_api(self, author_name: str) -> Optional[Dict[str, Any]]:
        """Query DBLP author API for a single author with retry logic.

        Args:
            author_name: Name of the author to query

        Returns:
            Dictionary with 'url' and 'orcid' keys, or None if not found
        """
        # Retry logic for SSL and proxy errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                params = {
                    'q': author_name,
                    'format': 'json'
                }

                proxies = {'http': self.dblp_proxy, 'https': self.dblp_proxy} if self.dblp_proxy else None

                response = requests.get(
                    self.DBLP_API_URL,
                    params=params,
                    proxies=proxies,
                    timeout=30
                )

                if response.status_code == 404:
                    return None

            response.raise_for_status()
            data = response.json()

            # Extract author information from response
            result = data.get('result', {})
            hits = result.get('hits', {})
            hit_list = hits.get('hit', [])

            if not hit_list:
                return None

            # Get first hit
            first_hit = hit_list[0]
            info = first_hit.get('info', {})

            # Extract URL
            url = info.get('url', '')

            # Extract ORCID from notes or persons
            orcid = ''

            # Try to get ORCID from notes
            notes = info.get('notes', {})
            note_list = notes.get('note', [])
            if isinstance(note_list, list):
                for note in note_list:
                    note_text = note.get('@text', '') if isinstance(note, dict) else str(note)
                    if 'Orcid:' in note_text:
                        # Extract ORCID from "Orcid: 0000-0001-2345-6789" format
                        orcid = note_text.split('Orcid:')[-1].strip()
                        break

            # Try to get ORCID from persons if not found in notes
            if not orcid:
                persons = info.get('persons', {})
                person_list = persons.get('person', [])
                if person_list and isinstance(person_list, list) and len(person_list) > 0:
                    first_person = person_list[0]
                    if isinstance(first_person, dict):
                        orcid = first_person.get('orcid', '')

            return {
                'url': url,
                'orcid': orcid
            }

            except requests.exceptions.SSLError as e:
                if attempt < max_retries - 1:
                    # Retry after delay for SSL errors
                    import time
                    time.sleep(2 ** attempt)  # Exponential backoff: 2s, 4s
                    continue
                else:
                    print(f"SSL Error querying author {author_name}: {e}")
                    return None
            except requests.exceptions.ProxyError as e:
                if attempt < max_retries - 1:
                    # Retry after delay for proxy errors
                    import time
                    time.sleep(2 ** attempt)
                    continue
                else:
                    print(f"Proxy Error querying author {author_name}: {e}")
                    return None
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                else:
                    print(f"Timeout querying author: {author_name}")
                    return None
            except requests.exceptions.RequestException as e:
                # Don't retry on other request exceptions (429, 500, etc)
                print(f"Error querying author {author_name}: {e}")
                return None

        # All retries exhausted
        return None
            return None

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

    def _write_author_to_db(self, author_data: Dict[str, Any]) -> None:
        """Write a single author to the database.

        Args:
            author_data: Dictionary containing author information
        """
        query = """
            INSERT INTO authors (
                name, dblp_url, orcid, affiliation,
                homepage, scholar_id, papers, updated_at
            ) VALUES
        """

        values = (
            author_data.get('name', ''),
            author_data.get('dblp_url', ''),
            author_data.get('orcid', ''),
            author_data.get('affiliation', ''),
            author_data.get('homepage', ''),
            author_data.get('scholar_id', ''),
            author_data.get('papers', []),
            author_data.get('updated_at', '')
        )

        self.db_client.execute(query, [values])

    def _write_authors_batch(self, authors: List[Dict[str, Any]]) -> None:
        """Write multiple authors to database in a single batch.

        Args:
            authors: List of author data dictionaries
        """
        if not authors:
            return

        query = """
            INSERT INTO authors (
                name, dblp_url, orcid, affiliation,
                homepage, scholar_id, papers, updated_at
            ) VALUES
        """

        values_list = []
        for author_data in authors:
            values = (
                author_data.get('name', ''),
                author_data.get('dblp_url', ''),
                author_data.get('orcid', ''),
                author_data.get('affiliation', ''),
                author_data.get('homepage', ''),
                author_data.get('scholar_id', ''),
                author_data.get('papers', []),
                author_data.get('updated_at', '')
            )
            values_list.append(values)

        self.db_client.insert(query, values_list)

    def _process_single_author(self, author_name: str) -> Dict[str, Any]:
        """Process a single author: query API, get CSrankings info, merge data.

        Args:
            author_name: Name of the author to process

        Returns:
            Dictionary with status and author data
        """
        # Query DBLP API
        dblp_info = self._query_author_api(author_name)

        # Get CSrankings information
        csrankings_info = self._get_csrankings_info(author_name)

        # Get papers from cache
        papers = list(self.author_cache.get_papers_for_author(author_name))

        # Merge data
        author_data = {
            'name': author_name,
            'dblp_url': dblp_info['url'] if dblp_info else '',
            'orcid': dblp_info['orcid'] if dblp_info else '',
            'affiliation': csrankings_info.get('affiliation', ''),
            'homepage': csrankings_info.get('homepage', ''),
            'scholar_id': csrankings_info.get('scholarid', ''),
            'papers': papers,
            'updated_at': datetime.now().isoformat()
        }

        # If not found in DBLP but has CSrankings ORCID, use that
        if not author_data['orcid'] and csrankings_info.get('orcid'):
            author_data['orcid'] = csrankings_info.get('orcid', '')

        return {
            'status': 'success',
            'data': author_data
        }

    def process_batch(self, author_batch: Set[str]) -> Dict[str, int]:
        """Process a batch of authors concurrently.

        Args:
            author_batch: Set of author names to process

        Returns:
            Dictionary with statistics (queried, written, failed)
        """
        stats = {
            'queried': 0,
            'written': 0,
            'failed': 0
        }

        if not author_batch:
            return stats

        # Process authors concurrently
        authors_to_write = []

        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            # Submit all queries
            future_to_author = {
                executor.submit(self._process_single_author, author): author
                for author in author_batch
            }

            # Collect results as they complete
            for future in as_completed(future_to_author):
                author_name = future_to_author[future]
                try:
                    result = future.result()
                    stats['queried'] += 1

                    if result['status'] == 'success':
                        authors_to_write.append(result['data'])

                        # Write in batches
                        if len(authors_to_write) >= self.batch_size:
                            self._write_authors_batch(authors_to_write)
                            stats['written'] += len(authors_to_write)
                            authors_to_write.clear()

                        # Mark as processed in cache
                        self.author_cache.mark_processed(author_name)

                except Exception as e:
                    print(f"Error processing author {author_name}: {e}")
                    stats['failed'] += 1

        # Write remaining authors
        if authors_to_write:
            self._write_authors_batch(authors_to_write)
            stats['written'] += len(authors_to_write)

        # Save checkpoint
        self.checkpoint_manager.update_progress(
            'author_matcher',
            {
                'total_processed': stats['queried'],
                'total_written': stats['written']
            }
        )

        # Save processed authors to checkpoint for recovery
        processed_authors_list = list(self.author_cache.get_processed_authors())
        self.checkpoint_manager.save_checkpoint({
            'parsed_chunks': self.checkpoint_manager.get_parsed_chunks(),
            'author_progress': {
                'total_queued': 0,  # Can be calculated from cache
                'queried': stats['queried'],
                'processed': stats['written']
            },
            'processed_authors': processed_authors_list,
            'db_stats': {
                'authors_written': stats['written'],
                'papers_written': 0  # Would need to track this
            },
            'last_updated': datetime.now().isoformat()
        })

        return stats

    def run(self, batch_size: int = 100) -> Dict[str, int]:
        """Continuous loop processing authors from cache until no more remain.

        Args:
            batch_size: Number of authors to process per batch

        Returns:
            Final statistics dictionary
        """
        total_stats = {
            'queried': 0,
            'written': 0,
            'failed': 0
        }

        while True:
            # Get next batch of unprocessed authors
            authors_to_process = self.author_cache.get_authors_to_query(batch_size)

            if not authors_to_process:
                # No more authors to process
                break

            # Process the batch
            batch_stats = self.process_batch(authors_to_process)

            # Accumulate statistics
            total_stats['queried'] += batch_stats['queried']
            total_stats['written'] += batch_stats['written']
            total_stats['failed'] += batch_stats['failed']

            print(f"Processed batch: {batch_stats['queried']} authors, "
                  f"{batch_stats['written']} written, {batch_stats['failed']} failed")

        return total_stats
