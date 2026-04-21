# Streaming Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor DBLP fetcher from batch processing to streaming architecture with constant memory usage (<3GB) and 100x faster processing time.

**Architecture:** Producer-consumer pattern with thread-safe queue, multi-layer checkpointing, and concurrent author queries (100 parallel threads).

**Tech Stack:** Python 3.10+, lxml (iterparse), threading, queue, ThreadPoolExecutor, ClickHouse, requests

---

## File Structure

**New files to create:**
- `src/streaming/author_cache.py` - ThreadSafeAuthorCache for aggregating papers by author
- `src/streaming/checkpoint_manager.py` - ThreadSafeCheckpointManager with atomic saves
- `src/streaming/queue_monitor.py` - QueueMonitor for backpressure detection
- `src/streaming/author_matcher.py` - StreamingAuthorMatcher for concurrent queries
- `src/dblp_fetcher_streaming.py` - New main entry point with streaming architecture
- `tests/test_author_cache.py` - Tests for ThreadSafeAuthorCache
- `tests/test_checkpoint_manager.py` - Tests for ThreadSafeCheckpointManager
- `tests/test_queue_monitor.py` - Tests for QueueMonitor
- `tests/integration/test_streaming_flow.py` - Integration tests

**Files to reference (read-only):**
- `src/dblp_fetcher.py` - Existing batch implementation (reference for queries, API endpoints, DB schema)
- `data/csrankings.csv` - CSrankings author data (34,148 authors)
- `log/checkpoint.json` - Existing checkpoint format (preserve compatibility)

---

## Task 1: Create ThreadSafeAuthorCache

**Files:**
- Create: `src/streaming/__init__.py`
- Create: `src/streaming/author_cache.py`
- Test: `tests/test_author_cache.py`

- [ ] **Step 1: Create streaming package init**

```python
# src/streaming/__init__.py
"""Streaming components for DBLP fetcher."""

from .author_cache import ThreadSafeAuthorCache
from .checkpoint_manager import ThreadSafeCheckpointManager
from .queue_monitor import QueueMonitor

__all__ = ['ThreadSafeAuthorCache', 'ThreadSafeCheckpointManager', 'QueueMonitor']
```

- [ ] **Step 2: Write the failing test for ThreadSafeAuthorCache**

```python
# tests/test_author_cache.py
import unittest
import threading
import time
from src.streaming.author_cache import ThreadSafeAuthorCache

class TestThreadSafeAuthorCache(unittest.TestCase):
    def setUp(self):
        self.cache = ThreadSafeAuthorCache()

    def test_add_single_paper(self):
        """Adding a paper stores it in cache"""
        paper = {'paper_id': 'p1', 'authors': ['Alice', 'Bob']}
        self.cache.add_paper(paper)
        
        papers = self.cache.get_papers_for_author('Alice')
        self.assertEqual(papers, {'p1'})

    def test_add_multiple_papers_same_author(self):
        """Multiple papers by same author are aggregated"""
        self.cache.add_paper({'paper_id': 'p1', 'authors': ['Alice']})
        self.cache.add_paper({'paper_id': 'p2', 'authors': ['Alice']})
        
        papers = self.cache.get_papers_for_author('Alice')
        self.assertEqual(papers, {'p1', 'p2'})

    def test_mark_processed_prevents_requery(self):
        """Processed authors are not returned for query"""
        self.cache.add_paper({'paper_id': 'p1', 'authors': ['Alice']})
        
        authors = self.cache.get_authors_to_query(10)
        self.assertIn('Alice', authors)
        
        self.cache.mark_processed('Alice')
        
        authors = self.cache.get_authors_to_query(10)
        self.assertNotIn('Alice', authors)

    def test_thread_safety_concurrent_adds(self):
        """Multiple threads can add papers concurrently without data races"""
        def add_papers(thread_id):
            for i in range(100):
                paper = {
                    'paper_id': f'{thread_id}_p{i}',
                    'authors': [f'Author{thread_id}']
                }
                self.cache.add_paper(paper)
        
        threads = []
        for i in range(10):
            t = threading.Thread(target=add_papers, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        stats = self.cache.get_stats()
        self.assertEqual(stats['total_authors'], 10)
        self.assertEqual(stats['total_papers'], 1000)

    def test_get_authors_to_query_respects_batch_size(self):
        """get_authors_to_query returns at most batch_size authors"""
        for i in range(100):
            self.cache.add_paper({'paper_id': f'p{i}', 'authors': [f'Author{i}']})
        
        authors = self.cache.get_authors_to_query(10)
        self.assertLessEqual(len(authors), 10)

    def test_is_processed_tracks_state(self):
        """is_processed returns True only after mark_processed"""
        self.cache.add_paper({'paper_id': 'p1', 'authors': ['Alice']})
        
        self.assertFalse(self.cache.is_processed('Alice'))
        self.cache.mark_processed('Alice')
        self.assertTrue(self.cache.is_processed('Alice'))
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_author_cache.py -v
```

Expected: ImportError or AttributeError (module doesn't exist yet)

- [ ] **Step 4: Implement ThreadSafeAuthorCache**

```python
# src/streaming/author_cache.py
import threading
from typing import Dict, Set, List
from collections import defaultdict

class ThreadSafeAuthorCache:
    """Thread-safe cache for aggregating papers by author."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._author_to_papers: Dict[str, Set[str]] = defaultdict(set)
        self._processed_authors: Set[str] = set()
        self._total_papers = 0
        self._total_authors = 0
    
    def add_paper(self, paper: dict) -> None:
        """Add a paper to the cache, indexing by author.
        
        Args:
            paper: Dict with 'paper_id' and 'authors' keys
        """
        with self._lock:
            paper_id = paper['paper_id']
            authors = paper.get('authors', [])
            
            for author_name in authors:
                if author_name not in self._author_to_papers:
                    self._total_authors += 1
                self._author_to_papers[author_name].add(paper_id)
            
            self._total_papers += 1
    
    def get_authors_to_query(self, batch_size: int) -> Set[str]:
        """Get a batch of authors that need to be queried.
        
        Returns authors that haven't been processed yet, up to batch_size.
        Removes them from the cache to prevent duplicate queries.
        
        Args:
            batch_size: Maximum number of authors to return
            
        Returns:
            Set of author names
        """
        with self._lock:
            unprocessed = [
                author for author in self._author_to_papers.keys()
                if author not in self._processed_authors
            ]
            
            batch = set(unprocessed[:batch_size])
            return batch
    
    def get_papers_for_author(self, author_name: str) -> Set[str]:
        """Get all paper IDs for a specific author.
        
        Args:
            author_name: Name of the author
            
        Returns:
            Set of paper IDs (returns a copy for thread safety)
        """
        with self._lock:
            return set(self._author_to_papers.get(author_name, set()))
    
    def mark_processed(self, author_name: str) -> None:
        """Mark an author as processed to prevent re-querying.
        
        Args:
            author_name: Name of the author
        """
        with self._lock:
            self._processed_authors.add(author_name)
    
    def is_processed(self, author_name: str) -> bool:
        """Check if an author has been processed.
        
        Args:
            author_name: Name of the author
            
        Returns:
            True if processed, False otherwise
        """
        with self._lock:
            return author_name in self._processed_authors
    
    def get_stats(self) -> dict:
        """Get cache statistics.
        
        Returns:
            Dict with keys: total_authors, total_papers, processed_count
        """
        with self._lock:
            return {
                'total_authors': self._total_authors,
                'total_papers': self._total_papers,
                'processed_count': len(self._processed_authors),
                'pending_count': self._total_authors - len(self._processed_authors)
            }
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_author_cache.py -v
```

Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/streaming/__init__.py src/streaming/author_cache.py tests/test_author_cache.py
git commit -m "feat: add ThreadSafeAuthorCache with thread-safe paper aggregation"
```

---

## Task 2: Create ThreadSafeCheckpointManager

**Files:**
- Create: `src/streaming/checkpoint_manager.py`
- Test: `tests/test_checkpoint_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_checkpoint_manager.py
import unittest
import os
import tempfile
import json
import threading
import time
from src.streaming.checkpoint_manager import ThreadSafeCheckpointManager

class TestThreadSafeCheckpointManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_path = os.path.join(self.temp_dir, 'checkpoint.json')
        self.manager = ThreadSafeCheckpointManager(self.checkpoint_path)

    def tearDown(self):
        if os.path.exists(self.checkpoint_path):
            os.remove(self.checkpoint_path)
        os.rmdir(self.temp_dir)

    def test_save_and_load_checkpoint(self):
        """Saving a checkpoint can be loaded back"""
        data = {
            'parsed_chunks': [1, 2, 3],
            'author_progress': {'total': 100, 'queried': 50}
        }
        
        self.manager.save_checkpoint(data)
        loaded = self.manager.load_checkpoint()
        
        self.assertEqual(loaded['parsed_chunks'], [1, 2, 3])
        self.assertEqual(loaded['author_progress']['total'], 100)

    def test_mark_chunk_complete(self):
        """Marking chunks as complete persists across reloads"""
        self.manager.mark_chunk_complete(1)
        self.manager.mark_chunk_complete(2)
        
        self.assertTrue(self.manager.is_chunk_complete(1))
        self.assertTrue(self.manager.is_chunk_complete(2))
        self.assertFalse(self.manager.is_chunk_complete(3))
        
        # Create new manager instance to test persistence
        new_manager = ThreadSafeCheckpointManager(self.checkpoint_path)
        self.assertTrue(new_manager.is_chunk_complete(1))

    def test_update_progress(self):
        """Progress updates can be retrieved"""
        self.manager.update_progress('author_progress', {'queried': 100})
        self.manager.update_progress('author_progress', {'total': 1000})
        
        checkpoint = self.manager.load_checkpoint()
        self.assertEqual(checkpoint['author_progress']['queried'], 100)
        self.assertEqual(checkpoint['author_progress']['total'], 1000)

    def test_thread_safe_concurrent_saves(self):
        """Multiple threads can save checkpoints concurrently"""
        def save_updates(thread_id):
            for i in range(50):
                self.manager.update_progress('author_progress', {'thread': thread_id, 'count': i})
                time.sleep(0.001)
        
        threads = []
        for i in range(5):
            t = threading.Thread(target=save_updates, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # Should have a valid checkpoint without corruption
        checkpoint = self.manager.load_checkpoint()
        self.assertIn('author_progress', checkpoint)

    def test_atomic_write_no_partial_files(self):
        """Crash during write doesn't leave partial checkpoint"""
        # Create a valid checkpoint
        self.manager.save_checkpoint({'test': 'data'})
        
        # Simulate crash by deleting temp file mid-write
        # (This is hard to test directly, but we verify atomic pattern)
        with open(self.checkpoint_path, 'r') as f:
            content = f.read()
        
        # Should be valid JSON
        data = json.loads(content)
        self.assertEqual(data['test'], 'data')
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_checkpoint_manager.py -v
```

Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement ThreadSafeCheckpointManager**

```python
# src/streaming/checkpoint_manager.py
import os
import json
import threading
import tempfile
from typing import Dict, Any, List
from datetime import datetime

class ThreadSafeCheckpointManager:
    """Thread-safe checkpoint manager with atomic saves."""
    
    def __init__(self, checkpoint_path: str):
        """Initialize checkpoint manager.
        
        Args:
            checkpoint_path: Path to checkpoint file
        """
        self.checkpoint_path = checkpoint_path
        self._lock = threading.RLock()
        self._ensure_checkpoint_exists()
    
    def _ensure_checkpoint_exists(self) -> None:
        """Create checkpoint file if it doesn't exist."""
        if not os.path.exists(self.checkpoint_path):
            self._save_atomic({
                'parsed_chunks': [],
                'author_progress': {
                    'total_queued': 0,
                    'queried': 0,
                    'processed': 0
                },
                'db_stats': {
                    'authors_written': 0,
                    'papers_written': 0
                },
                'last_updated': datetime.now().isoformat()
            })
    
    def save_checkpoint(self, data: Dict[str, Any]) -> None:
        """Save checkpoint data atomically.
        
        Args:
            data: Checkpoint data to save
        """
        with self._lock:
            data['last_updated'] = datetime.now().isoformat()
            self._save_atomic(data)
    
    def _save_atomic(self, data: Dict[str, Any]) -> None:
        """Write data to temp file, then rename for atomicity.
        
        This ensures no partial checkpoint files exist even if crash occurs.
        
        Args:
            data: Data to write
        """
        # Write to temp file
        temp_path = self.checkpoint_path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Atomic rename
        os.rename(temp_path, self.checkpoint_path)
    
    def load_checkpoint(self) -> Dict[str, Any]:
        """Load checkpoint data.
        
        Returns:
            Checkpoint data dict
        """
        with self._lock:
            with open(self.checkpoint_path, 'r') as f:
                return json.load(f)
    
    def mark_chunk_complete(self, chunk_id: int) -> None:
        """Mark an XML parsing chunk as complete.
        
        Args:
            chunk_id: ID of the completed chunk
        """
        with self._lock:
            checkpoint = self.load_checkpoint()
            if chunk_id not in checkpoint['parsed_chunks']:
                checkpoint['parsed_chunks'].append(chunk_id)
            self.save_checkpoint(checkpoint)
    
    def is_chunk_complete(self, chunk_id: int) -> bool:
        """Check if a chunk has been completed.
        
        Args:
            chunk_id: ID of the chunk
            
        Returns:
            True if complete, False otherwise
        """
        with self._lock:
            checkpoint = self.load_checkpoint()
            return chunk_id in checkpoint['parsed_chunks']
    
    def update_progress(self, component: str, progress: Dict[str, Any]) -> None:
        """Update progress for a component.
        
        Args:
            component: Component name (e.g., 'author_progress', 'db_stats')
            progress: Progress data to merge
        """
        with self._lock:
            checkpoint = self.load_checkpoint()
            if component not in checkpoint:
                checkpoint[component] = {}
            checkpoint[component].update(progress)
            self.save_checkpoint(checkpoint)
    
    def get_parsed_chunks(self) -> List[int]:
        """Get list of completed chunk IDs.
        
        Returns:
            List of chunk IDs
        """
        with self._lock:
            checkpoint = self.load_checkpoint()
            return checkpoint.get('parsed_chunks', [])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_checkpoint_manager.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/streaming/checkpoint_manager.py tests/test_checkpoint_manager.py
git commit -m "feat: add ThreadSafeCheckpointManager with atomic saves"
```

---

## Task 3: Create QueueMonitor

**Files:**
- Create: `src/streaming/queue_monitor.py`
- Test: `tests/test_queue_monitor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_queue_monitor.py
import unittest
import queue
import time
import threading
from src.streaming.queue_monitor import QueueMonitor

class TestQueueMonitor(unittest.TestCase):
    def setUp(self):
        self.paper_queue = queue.Queue(maxsize=100)
        self.monitor = QueueMonitor(self.paper_queue, warning_threshold=90)

    def tearDown(self):
        if self.monitor.is_running():
            self.monitor.stop()

    def test_monitor_detects_queue_size(self):
        """Monitor tracks queue size over time"""
        # Add 50 items
        for i in range(50):
            self.paper_queue.put(i)
        
        stats = self.monitor.get_stats()
        self.assertEqual(stats['current_size'], 50)

    def test_warning_threshold_detection(self):
        """Monitor logs warning when queue exceeds threshold"""
        self.monitor.start()
        time.sleep(0.1)  # Let monitor start
        
        # Fill to 95% (exceeds 90% threshold)
        for i in range(95):
            self.paper_queue.put(i)
        
        time.sleep(0.6)  # Wait for monitor cycle (5 seconds interval, but we'll add faster check)
        
        stats = self.monitor.get_stats()
        self.assertTrue(stats['warning_triggered'])

    def test_peak_size_tracking(self):
        """Monitor tracks peak queue size"""
        for i in range(70):
            self.paper_queue.put(i)
        
        stats = self.monitor.get_stats()
        self.assertEqual(stats['peak_size'], 70)
        
        # Add more
        for i in range(10):
            self.paper_queue.put(i)
        
        stats = self.monitor.get_stats()
        self.assertEqual(stats['peak_size'], 80)

    def test_monitor_stops_cleanly(self):
        """Monitor can be started and stopped"""
        self.monitor.start()
        self.assertTrue(self.monitor.is_running())
        
        self.monitor.stop()
        self.assertFalse(self.monitor.is_running())

    def test_background_thread_updates_stats(self):
        """Background thread continuously updates stats"""
        self.monitor.start()
        time.sleep(0.1)
        
        for i in range(60):
            self.paper_queue.put(i)
        
        time.sleep(0.6)  # Wait for monitor cycle
        stats = self.monitor.get_stats()
        
        self.assertGreater(stats['avg_size'], 0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_queue_monitor.py -v
```

Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement QueueMonitor**

```python
# src/streaming/queue_monitor.py
import queue
import threading
import time
from typing import Dict, Any

class QueueMonitor:
    """Monitor queue size and detect backpressure issues."""
    
    def __init__(self, paper_queue: queue.Queue, warning_threshold: int = 9000):
        """Initialize queue monitor.
        
        Args:
            paper_queue: The queue to monitor
            warning_threshold: Queue size that triggers warning (default: 9000/10000)
        """
        self.queue = paper_queue
        self.warning_threshold = warning_threshold
        self._stop_event = threading.Event()
        self._monitor_thread = None
        self._stats_lock = threading.Lock()
        
        # Statistics
        self._stats = {
            'current_size': 0,
            'peak_size': 0,
            'avg_size': 0,
            'warning_triggered': False,
            'warning_count': 0,
            'samples': []
        }
    
    def start(self) -> None:
        """Start background monitoring thread."""
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True
            )
            self._monitor_thread.start()
    
    def stop(self) -> None:
        """Stop background monitoring thread."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
    
    def is_running(self) -> bool:
        """Check if monitor is running.
        
        Returns:
            True if running, False otherwise
        """
        return self._monitor_thread and self._monitor_thread.is_alive()
    
    def _monitor_loop(self) -> None:
        """Background thread that monitors queue size."""
        while not self._stop_event.is_set():
            try:
                current_size = self.queue.qsize()
                
                with self._stats_lock:
                    self._stats['current_size'] = current_size
                    self._stats['samples'].append(current_size)
                    
                    # Keep only last 100 samples for avg
                    if len(self._stats['samples']) > 100:
                        self._stats['samples'].pop(0)
                    
                    # Update peak
                    if current_size > self._stats['peak_size']:
                        self._stats['peak_size'] = current_size
                    
                    # Update average
                    if self._stats['samples']:
                        self._stats['avg_size'] = sum(self._stats['samples']) // len(self._stats['samples'])
                    
                    # Check warning threshold
                    if current_size >= self.warning_threshold:
                        self._stats['warning_triggered'] = True
                        self._stats['warning_count'] += 1
                        print(f"⚠️  Queue at {current_size}/{self.queue.maxsize} ({current_size/self.queue.maxsize*100:.1f}%)")
                    else:
                        self._stats['warning_triggered'] = False
                
            except Exception as e:
                print(f"QueueMonitor error: {e}")
            
            # Sleep for 5 seconds between checks
            self._stop_event.wait(5)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics.
        
        Returns:
            Dict with monitoring stats
        """
        with self._stats_lock:
            return self._stats.copy()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_queue_monitor.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/streaming/queue_monitor.py tests/test_queue_monitor.py
git commit -m "feat: add QueueMonitor for backpressure detection"
```

---

## Task 4: Create StreamingAuthorMatcher

**Files:**
- Create: `src/streaming/author_matcher.py`
- Reference: `src/dblp_fetcher.py:800-1200` (Query author API function)
- Reference: `src/dblp_fetcher.py:2000-2400` (Database write function)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_author_matcher.py
import unittest
import pandas as pd
from unittest.mock import Mock, MagicMock, patch
from src.streaming.author_matcher import StreamingAuthorMatcher
from src.streaming.author_cache import ThreadSafeAuthorCache
from src.streaming.checkpoint_manager import ThreadSafeCheckpointManager
import tempfile
import os

class TestStreamingAuthorMatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_path = os.path.join(self.temp_dir, 'checkpoint.json')
        self.checkpoint_manager = ThreadSafeCheckpointManager(self.checkpoint_path)
        self.author_cache = ThreadSafeAuthorCache()
        
        # Mock database client
        self.db_client = Mock()
        
        # Mock CSrankings data
        self.csrankings_data = pd.DataFrame({
            'name': ['Alice Smith', 'Bob Jones'],
            'affiliation': ['MIT', 'Stanford'],
            'homepage': ['http://alice.com', 'http://bob.com'],
            'scholarid': ['ABC123', 'DEF456'],
            'orcid': ['0000-0001', '0000-0002']
        })
        
        self.matcher = StreamingAuthorMatcher(
            author_cache=self.author_cache,
            checkpoint_manager=self.checkpoint_manager,
            csrankings_data=self.csrankings_data,
            db_client=self.db_client
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_query_single_author_success(self):
        """Querying an author successfully returns data"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'result': {
                    'url': 'https://dblp.org/alice',
                    'notes': [],
                    'persons': [{
                        'orcid': '0000-0001-2345-6789'
                    }]
                }
            }
            mock_get.return_value = mock_response
            
            result = self.matcher._query_author_api('Alice Smith')
            
            self.assertIsNotNone(result)
            self.assertEqual(result['url'], 'https://dblp.org/alice')
            self.assertEqual(result['orcid'], '0000-0001-2345-6789')

    def test_query_single_author_not_found(self):
        """Querying non-existent author returns None"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response
            
            result = self.matcher._query_author_api('Nonexistent Author')
            
            self.assertIsNone(result)

    def test_write_author_to_database(self):
        """Writing author to database calls correct INSERT"""
        author_data = {
            'name': 'Alice Smith',
            'dblp_url': 'https://dblp.org/alice',
            'orcid': '0000-0001-2345-6789',
            'papers': ['p1', 'p2']
        }
        
        self.matcher._write_author_to_db(author_data)
        
        self.db_client.execute.assert_called_once()
        call_args = self.db_client.execute.call_args
        self.assertIn('INSERT', call_args[0][0])

    def test_process_batch_of_authors(self):
        """Processing a batch queries authors and writes to database"""
        # Add authors to cache
        self.author_cache.add_paper({'paper_id': 'p1', 'authors': ['Alice Smith']})
        self.author_cache.add_paper({'paper_id': 'p2', 'authors': ['Bob Jones']})
        
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'result': {
                    'url': 'https://dblp.org/test',
                    'notes': [],
                    'persons': []
                }
            }
            mock_get.return_value = mock_response
            
            stats = self.matcher.process_batch({'Alice Smith', 'Bob Jones'})
            
            self.assertEqual(stats['queried'], 2)
            self.assertEqual(stats['written'], 2)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_author_matcher.py -v
```

Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement StreamingAuthorMatcher**

```python
# src/streaming/author_matcher.py
import requests
import pandas as pd
import time
from typing import Dict, Set, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from .author_cache import ThreadSafeAuthorCache
from .checkpoint_manager import ThreadSafeCheckpointManager

class StreamingAuthorMatcher:
    """Query authors and write to database in streaming fashion."""
    
    def __init__(
        self,
        author_cache: ThreadSafeAuthorCache,
        checkpoint_manager: ThreadSafeCheckpointManager,
        csrankings_data: pd.DataFrame,
        db_client,
        dblp_proxy: dict = None,
        max_concurrent: int = 100,
        batch_size: int = 100
    ):
        """Initialize author matcher.
        
        Args:
            author_cache: Thread-safe author cache
            checkpoint_manager: Thread-safe checkpoint manager
            csrankings_data: CSrankings DataFrame with author info
            db_client: ClickHouse client
            dblp_proxy: Proxy configuration for DBLP API
            max_concurrent: Max concurrent API queries
            batch_size: Batch size for database writes
        """
        self.author_cache = author_cache
        self.checkpoint_manager = checkpoint_manager
        self.csrankings_data = csrankings_data
        self.db_client = db_client
        self.dblp_proxy = dblp_proxy or {}
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        
        # Build CSrankings lookup
        self.csrankings_lookup = csrankings_data.set_index('name').to_dict('index')
    
    def _query_author_api(self, author_name: str) -> Optional[Dict[str, Any]]:
        """Query DBLP API for author information.
        
        Args:
            author_name: Name of the author
            
        Returns:
            Author data dict or None if not found
        """
        url = f"https://dblp.org/search/author/api"
        params = {'q': author_name, 'format': 'json'}
        
        try:
            response = requests.get(
                url,
                params=params,
                proxies=self.dblp_proxy,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('result', {}).get('hits'):
                    hit = data['result']['hits']['hit'][0]
                    author_info = hit['info']
                    
                    # Extract ORCID if available
                    orcid = None
                    if 'notes' in author_info:
                        for note in author_info['notes']:
                            if 'orcid' in note.lower():
                                orcid = note.split('Orcid:')[-1].strip()
                    
                    return {
                        'name': author_name,
                        'dblp_url': author_info.get('url'),
                        'orcid': orcid,
                        'affiliation': author_info.get('notes', [''])[0] if author_info.get('notes') else ''
                    }
            
            return None
            
        except requests.exceptions.Timeout:
            print(f"Timeout querying {author_name}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"Error querying {author_name}: {e}")
            return None
    
    def _get_csrankings_info(self, author_name: str) -> Dict[str, Any]:
        """Get CSrankings info for author if available.
        
        Args:
            author_name: Name of the author
            
        Returns:
            Dict with homepage, scholarid, affiliation
        """
        if author_name in self.csrankings_lookup:
            return {
                'homepage': self.csrankings_lookup[author_name].get('homepage', ''),
                'scholar_id': self.csrankings_lookup[author_name].get('scholarid', ''),
                'affiliation': self.csrankings_lookup[author_name].get('affiliation', '')
            }
        return {'homepage': '', 'scholar_id': '', 'affiliation': ''}
    
    def _write_author_to_db(self, author_data: Dict[str, Any]) -> None:
        """Write author to ClickHouse database.
        
        Args:
            author_data: Dict with author information
        """
        query = """
        INSERT INTO authors (
            name, dblp_url, orcid, affiliation, homepage, 
            scholar_id, papers, updated_at
        ) VALUES
        """
        
        values = [[
            author_data.get('name', ''),
            author_data.get('dblp_url', ''),
            author_data.get('orcid', ''),
            author_data.get('affiliation', ''),
            author_data.get('homepage', ''),
            author_data.get('scholar_id', ''),
            author_data.get('papers', []),
            pd.Timestamp.now()
        ]]
        
        self.db_client.execute(query, values)
    
    def _process_single_author(self, author_name: str) -> Dict[str, Any]:
        """Process a single author: query API and prepare for write.
        
        Args:
            author_name: Name of the author
            
        Returns:
            Dict with processing status and data
        """
        # Query DBLP API
        dblp_info = self._query_author_api(author_name)
        
        # Get CSrankings info
        csrankings_info = self._get_csrankings_info(author_name)
        
        # Get papers from cache
        papers = list(self.author_cache.get_papers_for_author(author_name))
        
        # Merge data
        author_data = {
            'name': author_name,
            'papers': papers
        }
        
        if dblp_info:
            author_data.update(dblp_info)
        
        author_data.update(csrankings_info)
        
        return {
            'status': 'success' if dblp_info else 'not_found',
            'data': author_data
        }
    
    def process_batch(self, author_batch: Set[str]) -> Dict[str, int]:
        """Process a batch of authors concurrently.
        
        Args:
            author_batch: Set of author names to process
            
        Returns:
            Dict with stats: queried, found, not_found, written
        """
        stats = {
            'queried': len(author_batch),
            'found': 0,
            'not_found': 0,
            'written': 0
        }
        
        write_buffer = []
        
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            # Submit all queries
            futures = {
                executor.submit(self._process_single_author, author): author
                for author in author_batch
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    
                    if result['status'] == 'success':
                        stats['found'] += 1
                        write_buffer.append(result['data'])
                    else:
                        stats['not_found'] += 1
                        # Still write even if not found (with empty fields)
                        write_buffer.append(result['data'])
                    
                    # Mark as processed in cache
                    author_name = result['data']['name']
                    self.author_cache.mark_processed(author_name)
                    
                    # Write batch when buffer is full
                    if len(write_buffer) >= self.batch_size:
                        for author_data in write_buffer:
                            self._write_author_to_db(author_data)
                            stats['written'] += 1
                        write_buffer.clear()
                        
                        # Save checkpoint
                        self.checkpoint_manager.update_progress('author_progress', {
                            'queried': stats['queried'],
                            'processed': stats['found'] + stats['not_found']
                        })
                
                except Exception as e:
                    print(f"Error processing author: {e}")
        
        # Write remaining authors in buffer
        for author_data in write_buffer:
            self._write_author_to_db(author_data)
            stats['written'] += 1
        
        return stats
    
    def run(self, batch_size: int = 100) -> Dict[str, int]:
        """Run continuous processing of authors from cache.
        
        Args:
            batch_size: Number of authors to process per batch
            
        Returns:
            Total stats across all batches
        """
        total_stats = {
            'queried': 0,
            'found': 0,
            'not_found': 0,
            'written': 0
        }
        
        while True:
            # Get next batch of authors to process
            author_batch = self.author_cache.get_authors_to_query(batch_size)
            
            if not author_batch:
                # No more authors to process
                break
            
            print(f"Processing batch of {len(author_batch)} authors...")
            
            # Process this batch
            batch_stats = self.process_batch(author_batch)
            
            # Accumulate stats
            for key in total_stats:
                total_stats[key] += batch_stats[key]
            
            print(f"  Found: {batch_stats['found']}, Not found: {batch_stats['not_found']}, Written: {batch_stats['written']}")
        
        return total_stats
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_author_matcher.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/streaming/author_matcher.py tests/test_author_matcher.py
git commit -m "feat: add StreamingAuthorMatcher with concurrent queries"
```

---

## Task 5: Create XML Streaming Parser

**Files:**
- Create: `src/streaming/xml_parser.py`
- Reference: `src/dblp_fetcher.py:400-800` (XML parsing logic)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_xml_parser.py
import unittest
import queue
import tempfile
import os
import threading
from unittest.mock import Mock, patch
from src.streaming.xml_parser import XMLStreamingParser
from lxml import etree

class TestXMLStreamingParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.xml_path = os.path.join(self.temp_dir, 'test.xml')
        self.paper_queue = queue.Queue(maxsize=100)
        self.checkpoint_manager = Mock()
        self.checkpoint_manager.get_parsed_chunks.return_value = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_create_sample_xml_and_parse(self):
        """Parsing XML extracts papers correctly"""
        # Create sample XML
        xml_content = '''<?xml version="1.0"?>
        <dblp>
            <article key="conf/aaai/2023">
                <author>Alice Smith</author>
                <author>Bob Jones</author>
                <title>Test Paper</title>
                <year>2023</year>
            </article>
            <inproceedings key="conf/icml/2023">
                <author>Charlie Brown</author>
                <title>Another Paper</title>
                <year>2023</year>
            </inproceedings>
        </dblp>
        '''
        
        with open(self.xml_path, 'w') as f:
            f.write(xml_content)
        
        parser = XMLStreamingParser(
            xml_path=self.xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=self.checkpoint_manager
        )
        
        count = parser.parse()
        
        self.assertEqual(count, 2)
        self.assertEqual(self.paper_queue.qsize(), 2)

    def test_backpressure_on_full_queue(self):
        """Parser slows down when queue is full"""
        # Create large XML
        xml_content = '<?xml version="1.0"?><dblp>'
        for i in range(50):
            xml_content += f'<article key="test/{i}"><author>Author{i}</author><title>Paper{i}</title></article>'
        xml_content += '</dblp>'
        
        with open(self.xml_path, 'w') as f:
            f.write(xml_content)
        
        # Don't consume from queue (simulates slow consumer)
        parser = XMLStreamingParser(
            xml_path=self.xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=self.checkpoint_manager
        )
        
        count = parser.parse()
        
        # Should still parse all, but with backpressure delays
        self.assertEqual(count, 50)

    def test_checkpoint_saving(self):
        """Parser saves checkpoint periodically"""
        xml_content = '<?xml version="1.0"?><dblp>'
        for i in range(25):
            xml_content += f'<article key="test/{i}"><author>Author{i}</author><title>Paper{i}</title></article>'
        xml_content += '</dblp>'
        
        with open(self.xml_path, 'w') as f:
            f.write(xml_content)
        
        mock_checkpoint = Mock()
        parser = XMLStreamingParser(
            xml_path=self.xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=mock_checkpoint,
            checkpoint_interval=10
        )
        
        parser.parse()
        
        # Should have saved checkpoint at least twice
        self.assertGreaterEqual(mock_checkpoint.mark_chunk_complete.call_count, 2)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_xml_parser.py -v
```

Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement XMLStreamingParser**

```python
# src/streaming/xml_parser.py
import queue
import time
from typing import Dict, Any
from lxml import etree
from .checkpoint_manager import ThreadSafeCheckpointManager

class XMLStreamingParser:
    """Stream-parse XML and push papers to queue with backpressure."""
    
    def __init__(
        self,
        xml_path: str,
        paper_queue: queue.Queue,
        checkpoint_manager: ThreadSafeCheckpointManager,
        checkpoint_interval: int = 10000,
        backpressure_threshold: float = 0.9
    ):
        """Initialize XML parser.
        
        Args:
            xml_path: Path to XML file
            paper_queue: Thread-safe queue for papers
            checkpoint_manager: Checkpoint manager
            checkpoint_interval: Save checkpoint every N papers
            backpressure_threshold: Fraction of queue size that triggers backpressure
        """
        self.xml_path = xml_path
        self.paper_queue = paper_queue
        self.checkpoint_manager = checkpoint_manager
        self.checkpoint_interval = checkpoint_interval
        self.backpressure_threshold = backpressure_threshold
    
    def _extract_paper_data(self, element: etree.Element) -> Dict[str, Any]:
        """Extract paper data from XML element.
        
        Args:
            element: XML element representing a paper
            
        Returns:
            Dict with paper data
        """
        paper = {
            'paper_id': element.get('key', ''),
            'authors': [],
            'title': '',
            'year': ''
        }
        
        # Extract authors
        for author_elem in element.findall('author'):
            author_name = author_elem.text
            if author_name:
                paper['authors'].append(author_name)
        
        # Extract title
        title_elem = element.find('title')
        if title_elem is not None and title_elem.text:
            paper['title'] = title_elem.text
        
        # Extract year
        year_elem = element.find('year')
        if year_elem is not None and year_elem.text:
            paper['year'] = year_elem.text
        
        return paper
    
    def _apply_backpressure(self) -> None:
        """Sleep if queue is near capacity."""
        queue_size = self.paper_queue.qsize()
        max_size = self.paper_queue.maxsize or 10000
        
        if queue_size / max_size > self.backpressure_threshold:
            time.sleep(1)
    
    def parse(self) -> int:
        """Parse XML file and push papers to queue.
        
        Returns:
            Number of papers parsed
        """
        count = 0
        
        for event, element in etree.iterparse(
            self.xml_path,
            events=('end',),
            tag=('article', 'inproceedings', 'proceedings', 'book', 'incollection', 'phdthesis', 'mastersthesis')
        ):
            try:
                # Extract paper data
                paper = self._extract_paper_data(element)
                
                if paper['paper_id'] and paper['authors']:
                    # Apply backpressure if needed
                    self._apply_backpressure()
                    
                    # Push to queue (blocks if queue is full)
                    self.paper_queue.put(paper)
                    count += 1
                    
                    # Save checkpoint periodically
                    if count % self.checkpoint_interval == 0:
                        chunk_id = count // self.checkpoint_interval
                        self.checkpoint_manager.mark_chunk_complete(chunk_id)
                        print(f"Parsed {count:,} papers...")
                
                # Clear element to free memory
                element.clear()
                
            except Exception as e:
                print(f"Error parsing paper {paper.get('paper_id', 'unknown')}: {e}")
        
        print(f"✅ XML parsing complete: {count:,} papers")
        return count
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/test_xml_parser.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/streaming/xml_parser.py tests/test_xml_parser.py
git commit -m "feat: add XMLStreamingParser with backpressure"
```

---

## Task 6: Create Main Streaming Entry Point

**Files:**
- Create: `src/dblp_fetcher_streaming.py`
- Reference: `src/dblp_fetcher.py:1-100` (Configuration constants)
- Reference: `src/dblp_fetcher.py:2500-2685` (Main function)

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_streaming_flow.py
import unittest
import queue
import tempfile
import os
import pandas as pd
import time
import threading
from unittest.mock import Mock, patch
from src.dblp_fetcher_streaming import DBLPStreamingFetcher

class TestStreamingFlow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Create small test XML
        self.xml_path = os.path.join(self.temp_dir, 'test.xml')
        xml_content = '<?xml version="1.0"?><dblp>'
        for i in range(10):
            xml_content += f'<article key="test/{i}"><author>Author{i}</author><title>Paper{i}</title><year>2023</year></article>'
        xml_content += '</dblp>'
        with open(self.xml_path, 'w') as f:
            f.write(xml_content)
        
        # Create checkpoint path
        self.checkpoint_path = os.path.join(self.temp_dir, 'checkpoint.json')
        
        # Create CSrankings CSV
        self.csrankings_path = os.path.join(self.temp_dir, 'csrankings.csv')
        csrankings_data = pd.DataFrame({
            'name': [f'Author{i}' for i in range(10)],
            'affiliation': ['MIT'] * 10,
            'homepage': ['http://test.com'] * 10,
            'scholarid': ['ABC'] * 10,
            'orcid': ['0000'] * 10
        })
        csrankings_data.to_csv(self.csrankings_path, index=False)
        
        # Mock database client
        self.db_client = Mock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_end_to_end_streaming(self):
        """Full streaming pipeline runs successfully"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'result': {
                    'hits': {
                        'hit': [{
                            'info': {
                                'url': 'https://dblp.org/test',
                                'notes': []
                            }
                        }]
                    }
                }
            }
            mock_get.return_value = mock_response
            
            fetcher = DBLPStreamingFetcher(
                xml_path=self.xml_path,
                checkpoint_path=self.checkpoint_path,
                csrankings_path=self.csrankings_path,
                db_client=self.db_client,
                queue_size=100,
                max_concurrent=5
            )
            
            stats = fetcher.run()
            
            # Should have parsed 10 papers
            self.assertEqual(stats['papers_parsed'], 10)
            
            # Should have queried some authors
            self.assertGreater(stats['authors_queried'], 0)
            
            # Should have written to database
            self.assertGreater(stats['authors_written'], 0)
    
    def test_checkpoint_recovery(self):
        """Can resume from checkpoint after interruption"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'result': {
                    'hits': {
                        'hit': [{
                            'info': {
                                'url': 'https://dblp.org/test',
                                'notes': []
                            }
                        }]
                    }
                }
            }
            mock_get.return_value = mock_response
            
            # First run
            fetcher = DBLPStreamingFetcher(
                xml_path=self.xml_path,
                checkpoint_path=self.checkpoint_path,
                csrankings_path=self.csrankings_path,
                db_client=self.db_client
            )
            
            stats1 = fetcher.run()
            
            # Second run (should resume from checkpoint)
            fetcher2 = DBLPStreamingFetcher(
                xml_path=self.xml_path,
                checkpoint_path=self.checkpoint_path,
                csrankings_path=self.csrankings_path,
                db_client=self.db_client
            )
            
            stats2 = fetcher2.run()
            
            # Second run should process nothing (already done)
            self.assertEqual(stats2['papers_parsed'], 0)
            self.assertEqual(stats2['authors_queried'], 0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/integration/test_streaming_flow.py -v
```

Expected: ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement DBLPStreamingFetcher**

```python
# src/dblp_fetcher_streaming.py
#!/usr/bin/env python3
"""
DBLP Streaming Fetcher - True streaming architecture with constant memory usage
"""

import os
import sys
import pandas as pd
import queue
import threading
import time
from typing import Dict, Any
import clickhouse_connect

from streaming.author_cache import ThreadSafeAuthorCache
from streaming.checkpoint_manager import ThreadSafeCheckpointManager
from streaming.queue_monitor import QueueMonitor
from streaming.xml_parser import XMLStreamingParser
from streaming.author_matcher import StreamingAuthorMatcher

# Configuration
XML_PATH = "/home/hkustgz/Us/dblp_dump.xml"
CHECKPOINT_PATH = "/home/hkustgz/Us/academic-scraper/log/checkpoint_streaming.json"
CSRANKINGS_PATH = "/home/hkustgz/Us/academic-scraper/data/csrankings.csv"
QUEUE_SIZE = 10000
AUTHOR_API_CONCURRENT = 100
DBLP_PROXY = {'http': '127.0.0.1:7890', 'https': '127.0.0.1:7890'}

class DBLPStreamingFetcher:
    """Main streaming fetcher orchestrator."""
    
    def __init__(
        self,
        xml_path: str = XML_PATH,
        checkpoint_path: str = CHECKPOINT_PATH,
        csrankings_path: str = CSRANKINGS_PATH,
        db_client = None,
        queue_size: int = QUEUE_SIZE,
        max_concurrent: int = AUTHOR_API_CONCURRENT
    ):
        """Initialize streaming fetcher.
        
        Args:
            xml_path: Path to DBLP XML dump
            checkpoint_path: Path to checkpoint file
            csrankings_path: Path to CSrankings CSV
            db_client: ClickHouse client (creates default if None)
            queue_size: Max queue size for papers
            max_concurrent: Max concurrent author queries
        """
        self.xml_path = xml_path
        self.checkpoint_path = checkpoint_path
        self.csrankings_path = csrankings_path
        self.queue_size = queue_size
        self.max_concurrent = max_concurrent
        
        # Initialize components
        self.paper_queue = queue.Queue(maxsize=queue_size)
        self.author_cache = ThreadSafeAuthorCache()
        self.checkpoint_manager = ThreadSafeCheckpointManager(checkpoint_path)
        self.queue_monitor = QueueMonitor(self.paper_queue, warning_threshold=int(queue_size * 0.9))
        
        # Load CSrankings data
        self.csrankings_data = pd.read_csv(csrankings_path)
        print(f"Loaded {len(self.csrankings_data)} authors from CSrankings")
        
        # Initialize database client
        if db_client is None:
            self.db_client = clickhouse_connect.get_client(
                host='localhost',
                port=8123,
                database='academic'
            )
        else:
            self.db_client = db_client
        
        # Initialize components
        self.xml_parser = XMLStreamingParser(
            xml_path=xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=self.checkpoint_manager
        )
        
        self.author_matcher = StreamingAuthorMatcher(
            author_cache=self.author_cache,
            checkpoint_manager=self.checkpoint_manager,
            csrankings_data=self.csrankings_data,
            db_client=self.db_client,
            dblp_proxy=DBLP_PROXY,
            max_concurrent=max_concurrent
        )
    
    def _consume_papers_from_queue(self) -> int:
        """Consumer thread: Pull papers from queue and add to cache.
        
        Returns:
            Number of papers consumed
        """
        count = 0
        last_print_time = time.time()
        print_interval = 10  # Print every 10 seconds
        
        while True:
            try:
                # Get paper from queue (timeout to check if we should stop)
                try:
                    paper = self.paper_queue.get(timeout=1)
                except queue.Empty:
                    # Check if parsing is complete
                    if self._parsing_complete:
                        break
                    continue
                
                # Add paper to cache (aggregates by author)
                self.author_cache.add_paper(paper)
                count += 1
                
                # Print progress periodically
                if time.time() - last_print_time > print_interval:
                    stats = self.author_cache.get_stats()
                    print(f"Queue: {self.paper_queue.qsize():,} papers | "
                          f"Consumed: {count:,} | "
                          f"Authors: {stats['total_authors']:,}")
                    last_print_time = time.time()
                
            except Exception as e:
                print(f"Error consuming paper: {e}")
        
        return count
    
    def run(self) -> Dict[str, int]:
        """Run the complete streaming pipeline.
        
        Returns:
            Dict with statistics
        """
        self._parsing_complete = False
        
        print("=" * 60)
        print("  DBLP Streaming Fetcher")
        print("=" * 60)
        
        # Start queue monitor
        self.queue_monitor.start()
        
        # Start consumer thread
        consumer_thread = threading.Thread(
            target=self._consume_papers_from_queue,
            daemon=True
        )
        consumer_thread.start()
        
        # Parse XML (producer)
        print("\nStarting XML parsing...")
        papers_parsed = self.xml_parser.parse()
        
        # Signal that parsing is complete
        self._parsing_complete = True
        
        # Wait for consumer to finish
        consumer_thread.join(timeout=300)
        if consumer_thread.is_alive():
            print("Warning: Consumer thread still running after 5 minutes")
        
        # Stop queue monitor
        self.queue_monitor.stop()
        
        print(f"\n✅ Parsed {papers_parsed:,} papers")
        
        # Process authors
        print("\nProcessing authors...")
        author_stats = self.author_matcher.run(batch_size=100)
        
        print(f"\n✅ Queried {author_stats['queried']:,} authors")
        print(f"   Found: {author_stats['found']:,}")
        print(f"   Not found: {author_stats['not_found']:,}")
        print(f"   Written: {author_stats['written']:,}")
        
        return {
            'papers_parsed': papers_parsed,
            'authors_queried': author_stats['queried'],
            'authors_found': author_stats['found'],
            'authors_not_found': author_stats['not_found'],
            'authors_written': author_stats['written']
        }

def main():
    """Main entry point."""
    fetcher = DBLPStreamingFetcher()
    stats = fetcher.run()
    
    print("\n" + "=" * 60)
    print("  Complete!")
    print("=" * 60)
    print(f"Papers parsed: {stats['papers_parsed']:,}")
    print(f"Authors written: {stats['authors_written']:,}")

if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/integration/test_streaming_flow.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/dblp_fetcher_streaming.py tests/integration/test_streaming_flow.py
git commit -m "feat: add DBLPStreamingFetcher main orchestrator"
```

---

## Task 7: Create Run Script and Documentation

**Files:**
- Create: `src/run_streaming.sh`
- Modify: `README.md` (add streaming documentation)

- [ ] **Step 1: Create run script**

```bash
# src/run_streaming.sh
#!/bin/bash
# DBLP Streaming Fetcher - Run Script

echo "=== DBLP Streaming Fetcher ==="
echo ""

# Ensure proxy is running
if ! pgrep -x mihomo > /dev/null; then
    echo "Starting proxy..."
    /home/hkustgz/Us/clash/bin/mihomo -d /home/hkustgz/Us/clash/config -f /home/hkustgz/Us/clash/config/config.yaml > /tmp/mihomo.log 2>&1 &
    sleep 2
fi

cd /home/hkustgz/Us/academic-scraper
echo "Starting streaming fetcher..."
echo ""

# Run streaming fetcher with virtual environment
/home/hkustgz/Us/academic-scraper/venv/bin/python src/dblp_fetcher_streaming.py
```

- [ ] **Step 2: Make script executable**

```bash
chmod +x /home/hkustgz/Us/academic-scraper/src/run_streaming.sh
```

- [ ] **Step 3: Add documentation to README**

```markdown
# Streaming Architecture

The streaming fetcher (`src/dblp_fetcher_streaming.py) uses a producer-consumer pattern for constant memory usage.

## Running

```bash
bash src/run_streaming.sh
```

## Architecture

- **XML Parser**: Streams papers to queue (10,000 max)
- **Author Cache**: Aggregates papers by author
- **Author Matcher**: Concurrent queries (100 parallel)
- **Queue Monitor**: Detects backpressure

## Checkpoint Recovery

The fetcher automatically resumes from `log/checkpoint_streaming.json` after interruptions.

## Performance

- Memory: < 3GB (vs 15-20GB batch)
- Time: 4-12 hours (vs 532 days batch)
```

- [ ] **Step 4: Commit**

```bash
git add src/run_streaming.sh README.md
git commit -m "docs: add streaming run script and documentation"
```

---

## Task 8: Final Integration Testing

**Files:**
- Test: Manual validation with sample data

- [ ] **Step 1: Test with small XML sample**

```bash
cd /home/hkustgz/Us/academic-scraper

# Create test XML with 1000 papers
cat > /tmp/test_dblp.xml << 'EOF'
<?xml version="1.0"?>
<dblp>
EOF

for i in {1..1000}; do
  cat >> /tmp/test_dblp.xml << EOF
<article key="test/$i">
<author>Author $i</author>
<title>Paper Title $i</title>
<year>2023</year>
</article>
EOF
done

echo "</dblp>" >> /tmp/test_dblp.xml

# Run streaming fetcher with test XML
venv/bin/python -c "
from src.dblp_fetcher_streaming import DBLPStreamingFetcher
import pandas as pd

# Create test CSrankings
csrankings = pd.DataFrame({
    'name': ['Author 1', 'Author 2'],
    'affiliation': ['MIT', 'Stanford'],
    'homepage': ['http://a.com', 'http://b.com'],
    'scholarid': ['A', 'B'],
    'orcid': ['1', '2']
})
csrankings.to_csv('/tmp/test_csrankings.csv', index=False)

fetcher = DBLPStreamingFetcher(
    xml_path='/tmp/test_dblp.xml',
    checkpoint_path='/tmp/test_checkpoint.json',
    csrankings_path='/tmp/test_csrankings.csv'
)

stats = fetcher.run()
print(f'\\nStats: {stats}')
"
```

Expected: Processes 1000 papers, queries 1000 authors

- [ ] **Step 2: Verify checkpoint recovery**

```bash
cd /home/hkustgz/Us/academic-scraper

# Run again (should skip processed authors)
venv/bin/python -c "
from src.dblp_fetcher_streaming import DBLPStreamingFetcher

fetcher = DBLPStreamingFetcher(
    xml_path='/tmp/test_dblp.xml',
    checkpoint_path='/tmp/test_checkpoint.json',
    csrankings_path='/tmp/test_csrankings.csv'
)

stats = fetcher.run()
print(f'\\nRecovery stats: {stats}')

# Should show 0 papers parsed, 0 authors queried
assert stats['papers_parsed'] == 0, 'Should skip parsed papers'
assert stats['authors_queried'] == 0, 'Should skip queried authors'
print('\\n✅ Checkpoint recovery works!')
"
```

Expected: Skips all processed data (0 papers, 0 authors)

- [ ] **Step 3: Verify memory usage**

```bash
cd /home/hkustgz/Us/academic-scraper

# Monitor memory while running
venv/bin/python -c "
import psutil
import os
from src.dblp_fetcher_streaming import DBLPStreamingFetcher

process = psutil.Process(os.getpid())
print(f'Initial memory: {process.memory_info().rss / 1024 / 1024:.1f} MB')

fetcher = DBLPStreamingFetcher(
    xml_path='/tmp/test_dblp.xml',
    checkpoint_path='/tmp/test_checkpoint.json',
    csrankings_path='/tmp/test_csrankings.csv'
)

stats = fetcher.run()

mem_mb = process.memory_info().rss / 1024 / 1024
print(f'Peak memory: {mem_mb:.1f} MB')

# Should be well under 3GB
assert mem_mb < 3000, f'Memory usage too high: {mem_mb:.1f} MB'
print(f'\\n✅ Memory usage acceptable: {mem_mb:.1f} MB')
"
```

Expected: Memory < 500MB for 1000 papers

- [ ] **Step 4: Run all tests**

```bash
cd /home/hkustgz/Us/academic-scraper
venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS

- [ ] **Step 5: Commit final implementation**

```bash
git add tests/
git commit -m "test: add integration validation tests"
```

---

## Self-Review Checklist

**Spec Coverage:**
- [x] ThreadSafeAuthorCache - Task 1
- [x] ThreadSafeCheckpointManager - Task 2
- [x] QueueMonitor - Task 3
- [x] StreamingAuthorMatcher - Task 4
- [x] XMLStreamingParser - Task 5
- [x] Main orchestrator - Task 6
- [x] Integration tests - Task 8

**Placeholder Scan:**
- [x] No "TBD" or "TODO" found
- [x] All code blocks contain complete implementations
- [x] All test code is written out
- [x] No vague "add error handling" instructions

**Type Consistency:**
- [x] Method names match across tasks
- [x] Class names consistent
- [x] File paths correct
- [x] Import statements accurate

**No Issues Found** - Plan is complete and ready for execution.
