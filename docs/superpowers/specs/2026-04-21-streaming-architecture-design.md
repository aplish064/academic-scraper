# Streaming Architecture Design for DBLP Fetcher

**Date:** 2026-04-21  
**Status:** Approved  
**Author:** Claude + User

## Overview

Redesign the DBLP Fetcher from a batch processing system to a true streaming architecture that processes papers incrementally with constant memory usage, preventing the out-of-memory errors that occur when loading 5+ million papers into memory.

## Problem Statement

**Current Issues:**
- XML parser loads all 5M+ papers into memory before processing (5-10GB memory spike)
- Long-running process (532 days estimated at 0.3 authors/sec)
- Frequent out-of-memory crashes
- Checkpoint system fragile and requires manual resets
- No backpressure mechanism when queue grows too large

**Goals:**
- Constant memory usage (< 2GB)
- Linear processing time (estimated 4-12 hours total)
- Automatic checkpoint recovery
- Resilient to failures and interruptions

## Architecture

### Component Diagram

```
┌─────────────────┐
│   XML File      │
│  (5M papers)    │
└────────┬────────┘
         │
         v
┌─────────────────────────────────────────┐
│  XML Parser (Producer)                  │
│  - ThreadPoolExecutor: 8 threads        │
│  - iterparse for streaming              │
│  - Yields papers one-by-one             │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│  Thread-Safe Queue (max 10,000)         │
│  - Backpressure monitoring              │
│  - ~100MB memory cap                    │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│  Author Processors (Consumers)          │
│  - ThreadPoolExecutor: 100 threads      │
│  - Aggregate papers by author           │
│  - Query DBLP API concurrently          │
│  - Write to ClickHouse immediately      │
└─────────────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│  ClickHouse Database                    │
│  - Batch writes (100 authors/batch)     │
└─────────────────────────────────────────┘
```

### Components

#### 1. XMLParser (Producer)

**Purpose:** Stream-parse XML and push papers to queue  

**Interface:**
```python
def parse_xml_streaming(
    xml_path: str,
    paper_queue: queue.Queue,
    checkpoint_manager: CheckpointManager,
    num_shards: int = 1,
    shard_index: int = 0
) -> int
```

**Implementation:**
- Uses `lxml.etree.iterparse` for streaming parsing
- Spawns 8 parallel threads for different file sections
- Clears parsed elements immediately after processing
- Saves checkpoint every 10,000 papers
- Implements backpressure: sleeps if queue > 9,000

**Returns:** Number of papers parsed

#### 2. ThreadSafeAuthorCache

**Purpose:** Aggregate papers by author with thread-safe operations  

**Interface:**
```python
class ThreadSafeAuthorCache:
    def __init__(self)
    def add_paper(self, paper: dict) -> None
    def get_authors_to_query(self, batch_size: int) -> Set[str]
    def get_papers_for_author(self, author_name: str) -> Set[str]
    def mark_processed(self, author_name: str) -> None
    def is_processed(self, author_name: str) -> bool
    def get_stats(self) -> dict
```

**Implementation:**
- Uses `threading.Lock` for all operations
- Two dicts: `author_to_papers` (author → set of paper IDs)
- Tracks processed authors to avoid duplicate queries
- Batch retrieval for efficient API calls

**Invariants:**
- All modifications are atomic
- No data races on concurrent reads/writes

#### 3. ThreadSafeCheckpointManager

**Purpose:** Manage checkpoint saves with atomic writes and thread safety  

**Interface:**
```python
class ThreadSafeCheckpointManager:
    def save_checkpoint(self, data: dict) -> None
    def load_checkpoint(self) -> dict
    def mark_chunk_complete(self, chunk_id: int) -> None
    def is_chunk_complete(self, chunk_id: int) -> bool
    def update_progress(self, component: str, progress: dict) -> None
```

**Implementation:**
- Uses `threading.RLock` for reentrant locking
- Atomic file writes: write to temp, then rename
- Three tracking sections:
  - `parsed_chunks`: which XML chunks are done
  - `author_progress`: how many authors queried
  - `db_stats`: database write statistics
- Auto-saves every 60 seconds during active processing

**File Format:**
```json
{
  "parsed_chunks": [1, 2, 3],
  "author_progress": {
    "total_queued": 1670839,
    "queried": 45000,
    "processed": 120345
  },
  "db_stats": {
    "authors_written": 120345,
    "papers_written": 450000
  },
  "last_updated": "2026-04-21T10:30:00Z"
}
```

#### 4. StreamingAuthorMatcher

**Purpose:** Query authors and write to database in streaming fashion  

**Interface:**
```python
def streaming_match_and_write_authors(
    author_cache: ThreadSafeAuthorCache,
    checkpoint_manager: ThreadSafeCheckpointManager,
    csrankings_data: pd.DataFrame,
    db_client,
    batch_size: int = 100,
    max_concurrent: int = 100
) -> dict
```

**Implementation:**
- Pulls authors from cache in batches
- Queries DBLP API with ThreadPoolExecutor (100 concurrent)
- Writes to ClickHouse immediately for each author:
  - If found: all fields populated
  - If not found: writes with NULL/empty fields
- Batch writes: accumulates 100 authors, then single INSERT
- Saves checkpoint after each batch
- Returns statistics (queried, found, failed, written)

**Database Schema:**
```sql
CREATE TABLE authors (
  name String,
  dblp_url String,
  orcid String,
  affiliation String,
  homepage String,
  scholar_id String,
  papers Array(String),
  updated_at DateTime
)
```

#### 5. QueueMonitor

**Purpose:** Monitor queue size and detect backpressure issues  

**Interface:**
```python
class QueueMonitor:
    def __init__(self, paper_queue: queue.Queue, warning_threshold: int = 9000)
    def start(self) -> None
    def stop(self) -> None
    def get_stats(self) -> dict
```

**Implementation:**
- Background thread checks queue size every 5 seconds
- Logs warnings if queue > 9,000 (90% full)
- Tracks metrics: avg size, peak size, time at warning
- If queue stays full for > 60 seconds, alerts consumer might be too slow

### Data Flow

**Normal Flow:**
```
1. XML Parser reads 100 papers from XML
2. Parser pushes to queue (blocks if queue > 10,000)
3. Consumer pulls from queue
4. Consumer extracts authors, adds to cache
5. Consumer queries author (100 concurrent API calls)
6. Consumer writes author to ClickHouse (100 authors/batch)
7. Consumer saves checkpoint
8. Repeat
```

**Backpressure Flow:**
```
1. Queue size → 9,000 (90% full)
2. QueueMonitor logs warning
3. XML Parser sleeps for 1 second before next push
4. Consumers drain queue
5. Queue size → 5,000
6. Parser resumes normal speed
```

**Checkpoint Recovery Flow:**
```
1. CheckpointManager loads checkpoint file
2. XML Parser: skip chunks in `parsed_chunks`
3. Author Cache: skip authors in `processed_authors`
4. Resume from last saved position
```

### Concurrency Safety

**Thread Safety Guarantees:**

1. **Queue Operations:**
   - `queue.Queue` is thread-safe by design
   - Producers/consumers can safely call `put()`/`get()`

2. **Author Cache:**
   - All public methods use `with self._lock`
   - No direct access to internal dicts
   - Returns copies of data to avoid external modification

3. **Checkpoint Manager:**
   - Uses `RLock` for reentrant locking
   - File writes are atomic (temp + rename)
   - No partial checkpoint files possible

4. **Database Writes:**
   - Each writer thread gets unique batch
   - No overlapping author IDs between batches
   - ClickHouse handles concurrent INSERTs

**Potential Race Conditions:**

| Scenario | Risk | Mitigation |
|----------|------|------------|
| Two consumers pull same author batch | Duplicate queries | Cache returns and removes atomically |
| Checkpoint save during crash | Partial checkpoint | Atomic temp + rename |
| Queue overflow | OOM | Backpressure at 90% capacity |
| Database connection timeout | Lost data | Re-query and retry on next run |

### Error Handling

**XML Parsing Errors:**
- Log error with paper ID and line number
- Skip problematic paper, continue parsing
- Save checkpoint to avoid reprocessing

**API Query Errors:**
- Rate limit (429): Exponential backoff (1s, 2s, 4s, 8s)
- Timeout (30s): Retry once, then mark as failed
- 404/500: Mark as failed, continue
- Network error: Retry 3 times with backoff
- All errors logged with author name and timestamp

**Database Write Errors:**
- Connection lost: Reconnect and retry batch
- Constraint violation: Log warning, skip duplicate
- Timeout: Retry once, then fail
- Checkpoint saved after successful write only

**Recovery Strategy:**
- Checkpoint after every successful batch
- On restart, skip processed authors
- Failed queries retried on next run
- No data loss from crashes

### Checkpoint Recovery

**Three-Layer Checkpointing:**

1. **XML Parsing Layer:**
   - Tracks which file chunks are processed
   - Skips completed chunks on restart
   - Checkpoint every 10,000 papers

2. **Author Query Layer:**
   - Tracks which authors are queried
   - Skips processed authors on restart
   - Checkpoint every 100 authors

3. **Database Write Layer:**
   - Tracks how many rows written
   - Enables progress reporting
   - Checkpoint after each batch

**Recovery Process:**
```python
# On startup
checkpoint = checkpoint_manager.load_checkpoint()
parsed_chunks = checkpoint.get('parsed_chunks', [])
queried_authors = checkpoint.get('queried_authors', set())

# XML parser skips completed chunks
parser.parse_xml_streaming(skip_chunks=parsed_chunks)

# Author matcher skips queried authors
matcher.stream_authors(skip_authors=queried_authors)
```

**Reset Mechanism:**
```python
# Manual reset if checkpoint corrupted
python reset_checkpoint.py --component authors --keep-cache
```

## Performance Estimates

**Memory Usage:**
- Queue: 10,000 papers × 10KB = 100MB
- Author cache: 1.6M authors × 1KB = 1.6GB
- Threads: 108 threads × 10MB = 1GB
- **Total: < 3GB** (vs. 15-20GB before)

**Processing Speed:**
- XML parsing: 40,000-50,000 papers/sec
- Author queries: 30-100 authors/sec (with 100 concurrent)
- Database writes: 10,000 authors/sec (batch inserts)
- **Total time: 4-12 hours** (vs. 532 days before)

**Bottlenecks:**
- DBLP API rate limits (mitigated by concurrent queries)
- Proxy connection latency (40s per call)
- Network bandwidth for API calls

## Implementation Checklist

- [ ] Implement ThreadSafeAuthorCache
- [ ] Implement ThreadSafeCheckpointManager
- [ ] Refactor XMLParser with backpressure
- [ ] Implement StreamingAuthorMatcher
- [ ] Implement QueueMonitor
- [ ] Update main() to use new architecture
- [ ] Add integration tests
- [ ] Performance testing with sample data
- [ ] Update documentation

## Migration Path

**Phase 1: Parallel Implementation**
- Keep existing `dblp_fetcher.py` as `dblp_fetcher_batch.py`
- Implement new streaming version as `dblp_fetcher_streaming.py`
- Test both with small dataset

**Phase 2: Validation**
- Run both on 100K papers sample
- Compare output: same authors, same counts
- Verify memory usage < 3GB
- Verify checkpoint recovery works

**Phase 3: Cutover**
- Replace `dblp_fetcher.py` with streaming version
- Update run scripts
- Update documentation

**Phase 4: Full Run**
- Run on full 5M paper dataset
- Monitor memory, queue size, API rate
- Iterate on bottlenecks

## Success Criteria

1. **Memory:** Peak usage < 3GB (vs. 15-20GB)
2. **Time:** Complete in < 24 hours (vs. 532 days)
3. **Reliability:** Can resume from checkpoint after crash
4. **Correctness:** Same author data as batch version
5. **Monitoring:** Real-time progress indicators
