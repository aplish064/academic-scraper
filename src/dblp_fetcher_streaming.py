#!/usr/bin/env python3
"""
DBLP Streaming Fetcher - Main orchestrator for streaming DBLP data processing

Integrates all streaming components:
- XMLStreamingParser: Parses DBLP XML with constant memory
- ThreadSafeAuthorCache: Aggregates papers by author
- QueueMonitor: Tracks queue metrics
- StreamingAuthorMatcher: Queries DBLP API and writes to database
- ThreadSafeCheckpointManager: Handles checkpoint persistence
"""

import sys
import queue
import threading
import time
import pandas as pd
from typing import Dict, Any, Optional
from pathlib import Path

from streaming import (
    ThreadSafeAuthorCache,
    ThreadSafeCheckpointManager,
    QueueMonitor,
    StreamingAuthorMatcher,
    XMLStreamingParser
)


# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.absolute()

# Default file paths
XML_PATH = str(PROJECT_ROOT / "data" / "dblp.xml")
CHECKPOINT_PATH = str(PROJECT_ROOT / "log" / "checkpoint_streaming.json")
CSRANKINGS_PATH = str(PROJECT_ROOT / "data" / "csrankings.csv")

# Concurrency settings
QUEUE_SIZE = 10000
AUTHOR_API_CONCURRENT = 1  # Not used for hybrid strategy (XML + CSrankings only)

# Proxy settings - NOT NEEDED for hybrid strategy
# We only use XML data + CSrankings, no network requests to DBLP
DBLP_PROXY = None


# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================

class DBLPStreamingFetcher:
    """Main orchestrator for streaming DBLP data processing.

    Implements producer-consumer pattern:
    - Producer: XMLStreamingParser parses XML and puts papers into queue
    - Consumer: Background thread pulls papers and aggregates by author
    - Processing: After XML parsing, authors are queried against DBLP API

    This design enables:
    - Constant memory usage regardless of XML size
    - Concurrent XML parsing and author aggregation
    - Checkpoint-based resume capability
    - Progress monitoring via QueueMonitor
    """

    def __init__(
        self,
        xml_path: str,
        checkpoint_path: str,
        csrankings_path: str,
        db_client=None,
        queue_size: int = QUEUE_SIZE,
        max_concurrent: int = AUTHOR_API_CONCURRENT
    ):
        """Initialize the streaming fetcher.

        Args:
            xml_path: Path to DBLP XML file
            checkpoint_path: Path to checkpoint JSON file
            csrankings_path: Path to CSrankings CSV file
            db_client: Database client (optional, will create if None)
            queue_size: Maximum queue size for backpressure
            max_concurrent: Maximum concurrent API requests
        """
        self.xml_path = xml_path
        self.checkpoint_path = checkpoint_path
        self.csrankings_path = csrankings_path
        self.queue_size = queue_size
        self.max_concurrent = max_concurrent

        # Initialize queue for producer-consumer
        self.paper_queue = queue.Queue(maxsize=queue_size)

        # Initialize checkpoint manager
        self.checkpoint_manager = ThreadSafeCheckpointManager(checkpoint_path)

        # Initialize author cache
        self.author_cache = ThreadSafeAuthorCache()

        # Restore processed authors from checkpoint
        checkpoint = self.checkpoint_manager.load_checkpoint()
        if 'processed_authors' in checkpoint:
            self.author_cache.restore_processed_authors(set(checkpoint['processed_authors']))
            print(f"Restored {len(checkpoint['processed_authors'])} processed authors from checkpoint")

        # Initialize queue monitor
        self.queue_monitor = QueueMonitor(self.paper_queue, monitor_interval=5.0)

        # Load CSrankings data
        self.csrankings_df = self._load_csrankings()

        # Create or use provided database client
        if db_client is None:
            import clickhouse_connect
            self.db_client = clickhouse_connect.get_client(
                host='localhost',
                port=8123,
                database='academic_db'
            )
            print("✅ Connected to ClickHouse database academic_db")
        else:
            self.db_client = db_client

        # Initialize components (will be created in run())
        self.xml_parser = None
        self.author_matcher = None

        # Flag to signal parsing is complete
        self._parsing_complete = False

        # Statistics
        self._papers_consumed = 0

    def _load_csrankings(self) -> pd.DataFrame:
        """Load CSrankings data from CSV.

        Returns:
            DataFrame with CSrankings data
        """
        try:
            return pd.read_csv(self.csrankings_path)
        except Exception as e:
            print(f"Warning: Failed to load CSrankings: {e}")
            return pd.DataFrame()

    def _consume_papers_from_queue(self) -> int:
        """Consumer thread: Pull papers from queue and add to cache.

        Runs in background thread while XML parser produces papers.
        Prints progress every 10 seconds.

        Returns:
            Number of papers consumed from queue
        """
        consumed = 0
        last_print_time = time.time()

        while True:
            try:
                # Get paper from queue with timeout to check parsing complete flag
                try:
                    paper = self.paper_queue.get(timeout=1.0)
                    consumed += 1

                    # Add to author cache
                    self.author_cache.add_paper(paper)

                    # Mark task done
                    self.paper_queue.task_done()

                except queue.Empty:
                    # Queue timeout - check if parsing is complete
                    if self._parsing_complete:
                        break
                    continue

                # Print progress every 10 seconds
                current_time = time.time()
                if current_time - last_print_time >= 10:
                    cache_stats = self.author_cache.get_stats()
                    print(f"   Consumed: {consumed:,} papers | "
                          f"Authors: {cache_stats['total_authors']:,} | "
                          f"Queue: {self.paper_queue.qsize():,}")
                    last_print_time = current_time

            except Exception as e:
                print(f"Error in consumer thread: {e}")
                continue

        return consumed

    def run(self) -> Dict[str, int]:
        """Run the complete streaming pipeline with chunk-by-chunk processing.

        New streaming workflow:
        1. Parse XML and process each chunk immediately (no queue, no threads)
        2. For each chunk (10,000 papers):
           - Process papers
           - Write to database
           - Save checkpoint
           - Clear memory
        3. Continue until all papers processed

        Returns:
            Dictionary with statistics:
            - papers_parsed: Number of papers parsed from XML
            - rows_written: Number of author rows written to database
        """
        stats = {
            'papers_parsed': 0,
            'rows_written': 0
        }

        print("🚀 Starting DBLP Streaming Fetcher (Chunk-based)")
        print(f"   XML: {self.xml_path}")
        print(f"   Checkpoint: {self.checkpoint_path}")
        print(f"   CSrankings: {self.csrankings_path}")

        # Initialize author matcher upfront
        print(f"\n📝 Initializing author matcher...")
        self.author_matcher = StreamingAuthorMatcher(
            author_cache=self.author_cache,
            checkpoint_manager=self.checkpoint_manager,
            csrankings_data=self.csrankings_df,
            db_client=self.db_client,
            max_concurrent=self.max_concurrent,
            batch_size=10000  # Process 10k papers at a time
        )

        # Load checkpoint to get last processed chunk
        checkpoint = self.checkpoint_manager.load_checkpoint()
        start_chunk = checkpoint.get('last_processed_chunk', 0)

        if start_chunk > 0:
            print(f"📂 Resuming from chunk #{start_chunk}")

        # Stream XML and process chunk by chunk
        print(f"\n📖 Starting XML parsing and chunk processing...")
        start_time = time.time()

        chunk_papers = []
        chunk_count = 0
        paper_count = 0

        try:
            # Use iterparse for streaming with constant memory
            context = etree.iterparse(
                self.xml_path,
                events=('end',),
                recover=True
            )

            for event, element in context:
                try:
                    # Only process paper type elements
                    if element.tag not in XMLStreamingParser.PAPER_TAGS:
                        continue

                    # Extract paper data
                    paper_data = self._extract_paper_data(element)

                    # Only queue papers with both paper_id and authors
                    if paper_data['paper_id'] and paper_data.get('authors'):
                        # Add to author cache
                        self.author_cache.add_paper(paper_data)
                        chunk_papers.append(paper_data)
                        paper_count += 1

                        # Process chunk when threshold reached
                        if len(chunk_papers) >= 10000:
                            chunk_count += 1

                            # Skip if already processed
                            if chunk_count <= start_chunk:
                                print(f"⏭️  Skipping chunk #{chunk_count} (already processed)")
                                # Clear from cache
                                for paper in chunk_papers:
                                    self.author_cache.mark_processed(paper['paper_id'])
                                chunk_papers = []
                                element.clear()
                                continue

                            print(f"\n📦 Processing chunk #{chunk_count} ({len(chunk_papers):,} papers)...")

                            # Process this chunk
                            chunk_stats = self.author_matcher.process_paper_batch(chunk_papers)

                            # Update statistics
                            stats['papers_parsed'] += chunk_stats['queried']
                            stats['rows_written'] += chunk_stats['written']

                            print(f"   ✓ Queried: {chunk_stats['queried']:,}, Written: {chunk_stats['written']:,} rows")

                            # Save checkpoint
                            elapsed = time.time() - start_time
                            print(f"   💾 Saving checkpoint (chunk #{chunk_count})...")
                            self.checkpoint_manager.save_checkpoint({
                                'last_processed_chunk': chunk_count,
                                'total_papers_parsed': stats['papers_parsed'],
                                'total_rows_written': stats['rows_written'],
                                'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
                            })

                            # Clear papers from cache
                            for paper in chunk_papers:
                                self.author_cache.mark_processed(paper['paper_id'])
                            chunk_papers = []

                            # Progress every 10 chunks
                            if chunk_count % 10 == 0:
                                rate = stats['papers_parsed'] / elapsed if elapsed > 0 else 0
                                print(f"\n📊 Progress: {chunk_count} chunks | {stats['papers_parsed']:,} papers | {stats['rows_written']:,} rows | {rate:.0f} papers/sec")

                    # Clear element to free memory
                    element.clear()

                except Exception as e:
                    print(f"⚠️  Error processing element: {e}")
                    continue

        except Exception as e:
            print(f"❌ Fatal parsing error: {e}")
            raise

        # Process any remaining papers in last chunk
        if chunk_papers:
            chunk_count += 1
            print(f"\n📦 Processing final chunk #{chunk_count} ({len(chunk_papers):,} papers)...")
            chunk_stats = self.author_matcher.process_paper_batch(chunk_papers)
            stats['papers_parsed'] += chunk_stats['queried']
            stats['rows_written'] += chunk_stats['written']
            print(f"   ✓ Queried: {chunk_stats['queried']:,}, Written: {chunk_stats['written']:,} rows")

        total_time = time.time() - start_time

        # Final summary
        print(f"\n🎉 Processing complete!")
        print(f"   Total chunks: {chunk_count}")
        print(f"   Papers parsed: {stats['papers_parsed']:,}")
        print(f"   Author rows written: {stats['rows_written']:,}")
        print(f"   Total time: {total_time:.1f}s ({total_time/60:.1f} minutes)")

        return stats

    def _extract_paper_data(self, element: etree.Element) -> Dict[str, Any]:
        """Extract paper data from XML element."""
        from .xml_parser import XMLStreamingParser

        paper_id = element.get('key')

        # Extract authors
        authors = [
            author.text
            for author in element.findall('author')
            if author.text
        ]

        # Extract title and year
        title_elem = element.find('title')
        title = title_elem.text if title_elem is not None else None

        year_elem = element.find('year')
        year = year_elem.text if year_elem is not None else None

        # Extract venue (journal/conference name)
        venue_elem = element.find('venue')
        venue = venue_elem.text if venue_elem is not None else None

        # Extract DOI
        doi_elem = element.find('doi')
        doi = doi_elem.text if doi_elem is not None else None

        # Extract electronic edition (EE) URL
        ee_elem = element.find('ee')
        ee = ee_elem.text if ee_elem is not None else None

        # Extract volume
        volume_elem = element.find('volume')
        volume = volume_elem.text if volume_elem is not None else None

        # Extract number
        number_elem = element.find('number')
        number = number_elem.text if number_elem is not None else None

        # Extract pages
        pages_elem = element.find('pages')
        pages = pages_elem.text if pages_elem is not None else None

        # Extract publisher
        publisher_elem = element.find('publisher')
        publisher = publisher_elem.text if publisher_elem is not None else None

        return {
            'paper_id': paper_id,
            'authors': authors,
            'title': title,
            'year': year,
            'venue': venue,
            'doi': doi,
            'ee': ee,
            'volume': volume,
            'number': number,
            'pages': pages,
            'publisher': publisher
        }


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point for DBLP streaming fetcher."""
    fetcher = DBLPStreamingFetcher(
        xml_path=XML_PATH,
        checkpoint_path=CHECKPOINT_PATH,
        csrankings_path=CSRANKINGS_PATH,
        db_client=None,  # Will create default client
        queue_size=QUEUE_SIZE,
        max_concurrent=AUTHOR_API_CONCURRENT
    )

    stats = fetcher.run()
    print(f"\n✅ Final statistics: {stats}")


if __name__ == '__main__':
    main()
