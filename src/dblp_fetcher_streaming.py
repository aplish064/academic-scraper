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
AUTHOR_API_CONCURRENT = 5  # Reduced to 5 to avoid SSL/proxy errors

# Proxy settings (if needed)
DBLP_PROXY = {'http': '127.0.0.1:7890', 'https': '127.0.0.1:7890'}


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
                database='academic'
            )
            print("✅ Connected to ClickHouse database")
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
        """Run the complete streaming pipeline.

        Orchestrates the entire workflow:
        1. Start queue monitor
        2. Start consumer thread
        3. Parse XML (producer)
        4. Wait for consumer to finish
        5. Stop queue monitor
        6. Process authors with DBLP API

        Returns:
            Dictionary with statistics:
            - papers_parsed: Number of papers parsed from XML
            - papers_consumed: Number of papers consumed from queue
            - authors_queried: Number of authors queried against API
            - authors_written: Number of authors written to database
        """
        stats = {
            'papers_parsed': 0,
            'papers_consumed': 0,
            'authors_queried': 0,
            'authors_written': 0
        }

        print("🚀 Starting DBLP Streaming Fetcher")
        print(f"   XML: {self.xml_path}")
        print(f"   Checkpoint: {self.checkpoint_path}")
        print(f"   Queue size: {self.queue_size:,}")
        print(f"   Max concurrent: {self.max_concurrent:,}")

        # Step 1: Start queue monitor
        print("\n📊 Starting queue monitor...")
        self.queue_monitor.start()

        # Step 2: Start consumer thread
        print("\n🔄 Starting consumer thread...")
        consumer_thread = threading.Thread(
            target=self._consume_papers_from_queue,
            daemon=True
        )
        consumer_thread.start()

        # Step 3: Parse XML (producer)
        print("\n📖 Parsing XML file...")
        self.xml_parser = XMLStreamingParser(
            xml_path=self.xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=self.checkpoint_manager,
            checkpoint_interval=10000,
            backpressure_threshold=0.9
        )

        start_time = time.time()
        papers_parsed = self.xml_parser.parse()
        stats['papers_parsed'] = papers_parsed

        # Signal parsing is complete
        self._parsing_complete = True

        parse_time = time.time() - start_time
        print(f"\n✅ XML parsing complete: {papers_parsed:,} papers in {parse_time:.1f}s")

        # Step 4: Wait for consumer to finish
        print("\n⏳ Waiting for consumer to finish...")
        consumer_thread.join(timeout=300)  # 5 minute timeout

        if consumer_thread.is_alive():
            print("⚠️  Consumer thread timeout (5 minutes)")
        else:
            print("✅ Consumer thread finished")

        stats['papers_consumed'] = self._papers_consumed = self._papers_consumed or papers_parsed

        # Step 5: Stop queue monitor
        print("\n🛑 Stopping queue monitor...")
        self.queue_monitor.stop()

        # Print cache statistics
        cache_stats = self.author_cache.get_stats()
        print(f"\n📦 Cache statistics:")
        print(f"   Total papers: {cache_stats['total_papers']:,}")
        print(f"   Total authors: {cache_stats['total_authors']:,}")
        print(f"   Pending processing: {cache_stats['pending_count']:,}")

        # Step 6: Process authors with DBLP API
        print(f"\n🔍 Processing authors with DBLP API...")
        self.author_matcher = StreamingAuthorMatcher(
            author_cache=self.author_cache,
            checkpoint_manager=self.checkpoint_manager,
            csrankings_data=self.csrankings_df,
            db_client=self.db_client,
            max_concurrent=self.max_concurrent,
            dblp_proxy=DBLP_PROXY.get('http')
        )

        matcher_stats = self.author_matcher.run(batch_size=100)
        stats['authors_queried'] = matcher_stats.get('total_queried', 0)
        stats['authors_written'] = matcher_stats.get('written_rows', 0)

        # Final summary
        print(f"\n🎉 Pipeline complete!")
        print(f"   Papers parsed: {stats['papers_parsed']:,}")
        print(f"   Papers consumed: {stats['papers_consumed']:,}")
        print(f"   Authors queried: {stats['authors_queried']:,}")
        print(f"   Authors written: {stats['authors_written']:,}")

        return stats


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
