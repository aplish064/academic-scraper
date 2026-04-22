# arXiv Fetcher Design Specification

**Date:** 2026-04-22
**Author:** Claude Code
**Status:** Draft
**Project:** Academic Scraper

## Overview

Design and implementation of a robust arXiv paper fetcher that retrieves all arXiv papers from 2026-04-22 back to 1990, storing data in ClickHouse with automatic progress tracking and retry capabilities.

## Requirements

### Functional Requirements

1. **Data Acquisition**
   - Fetch all arXiv papers from 2026-04-22 to 1990
   - Process papers day-by-day in reverse chronological order
   - Retrieve all papers for each date (no artificial limits)

2. **Data Storage**
   - Store data in ClickHouse `academic_db.arxiv` table
   - One row per author (expand multi-author papers)
   - Use temporary table deduplication for batch inserts

3. **Progress Management**
   - Track completed dates in JSON progress file
   - Only mark dates as completed if fully successful
   - Support resumption from last checkpoint

4. **Rate Limiting**
   - Respect arXiv API rate limits (1 request/second)
   - Pause 60 seconds on HTTP 429 (rate limit) errors
   - Automatic retry with exponential backoff for server errors

### Non-Functional Requirements

1. **Reliability**
   - Single date failure should not affect other dates
   - Database insert failure should not mark date as completed
   - Support graceful shutdown and restart

2. **Performance**
   - Process 100-500 papers per day (CS fields)
   - Memory efficient (< 500MB)
   - Estimated 4-11 hours for full 13,500 day range

3. **Maintainability**
   - Clear logging of all operations
   - Progress monitoring with statistics
   - Error recovery with detailed logging

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ArxivFetcher Main                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Date         │  │ Progress     │  │ ClickHouse   │      │
│  │ Generator    │→ │ Manager      │→ │ Client       │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         ↓                   ↓                   ↓            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Page         │  │ Error        │  │ Batch        │      │
│  │ Fetcher      │  │ Handler      │  │ Inserter     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Generate Date List (2026-04-22 → 1990-01-01)
   ↓
2. Load Progress File
   ↓
3. Filter Completed Dates
   ↓
4. For Each Pending Date:
   a. Fetch pages (3000 papers/page) until complete
   b. Parse XML responses (feedparser)
   c. Extract and validate paper data
   d. Transform to author-level rows
   e. Batch insert to ClickHouse (10,000 rows/batch)
   f. Update progress (only if fully successful)
   ↓
5. Generate Final Statistics
```

## Components

### 1. ArxivFetcher (Main Class)

**Responsibilities:**
- Coordinate date processing
- Manage progress tracking
- Handle error recovery
- Generate statistics

**Key Methods:**
- `__init__(start_date, end_year, ch_client)`
- `run()` - Main execution loop
- `fetch_papers_by_date(date_str)` - Process single date
- `load_progress()` / `save_progress()` - Progress management

### 2. HTTP Client with Retry Logic

**Responsibilities:**
- Make HTTP requests to arXiv API
- Handle rate limiting (429 errors)
- Implement retry logic with exponential backoff
- Timeout handling

**Configuration:**
```python
REQUEST_INTERVAL = 1.0  # seconds
REQUEST_TIMEOUT = 30    # seconds
MAX_RETRIES = 3
RATE_LIMIT_WAIT = 60    # seconds
```

### 3. XML Parser (feedparser)

**Responsibilities:**
- Parse arXiv Atom XML responses
- Extract paper metadata
- Handle author and affiliation data
- Validate required fields

**Fields Extracted:**
- `id` - Full arXiv URL
- `title` - Paper title
- `published` - Publication date
- `updated` - Last update date
- `authors[]` - Author list with affiliations
- `categories[]` - Category list
- `primary_category` - Primary category
- `links[]` - HTML and PDF URLs
- `comment` - Author comments (optional)
- `journal_ref` - Journal reference (optional)

### 4. Data Transformer

**Responsibilities:**
- Convert paper objects to database rows
- Expand multi-author papers (one row per author)
- Add rank and tag information
- Handle missing affiliations

**Transformation Rules:**
- Rank 1 → tag = "第一作者"
- Rank = total_authors → tag = "最后作者"
- Other ranks → tag = "其他"

### 5. ClickHouse Batch Inserter

**Responsibilities:**
- Create temporary table for deduplication
- Insert batch data (10,000 rows)
- Merge to target table with DISTINCT
- Drop temporary table

**Error Handling:**
- Log errors but continue processing
- Return False on failure (parent won't update progress)

## Database Schema

### Table: `academic_db.arxiv`

```sql
CREATE TABLE academic_db.arxiv (
    -- Paper Identification
    arxiv_id String,              -- arXiv ID (2012.12104v1)
    uid String,                   -- Full URL

    -- Paper Information
    title String,
    published Date,
    updated DateTime,

    -- Category Information
    categories Array(String),
    primary_category String,

    -- Journal Information (Optional)
    journal_ref String,
    comment String,

    -- Links
    url String,                   -- HTML URL
    pdf_url String,              -- PDF URL

    -- Author Information (one row per author)
    author String,
    rank UInt8,
    tag String,                   -- 第一作者/最后作者/其他
    affiliation String,

    -- Metadata
    import_date Date

) ENGINE = MergeTree()
ORDER BY (arxiv_id, rank);
```

## API Integration

### arXiv API Query Format

**Base URL:** `http://export.arxiv.org/api/query`

**Query Parameters:**
```
search_query=lastUpdatedDate:[20260422+TO+20260422]
start=0
max_results=3000
```

**Date-Based Query Strategy:**
```python
# Use lastUpdatedDate field with date range (YYYYMMDD format)
# For single day query, use same start and end date
search_query=lastUpdatedDate:[20260422+TO+20260422]

# For category + date combination
search_query=cat:cs.AI+and+lastUpdatedDate:[20260422+TO+20260422]
```

**Note:** arXiv API uses `lastUpdatedDate` field with format `YYYYMMDD` (no hyphens). The `+` character must be URL-encoded as `%2B` in actual requests.

**Pagination Strategy:**
```python
def fetch_all_papers_for_date(date_str):
    all_papers = []
    start = 0
    per_page = 3000

    while True:
        papers = fetch_page(date_str, start, per_page)

        if len(papers) == 0:
            break  # No more papers

        all_papers.extend(papers)

        if len(papers) < per_page:
            break  # Last page

        start += per_page
        time.sleep(REQUEST_INTERVAL)

    return all_papers
```

## Error Handling

### Error Categories and Responses

| Error Type | HTTP Code | Action |
|------------|-----------|--------|
| Rate Limit | 429 | Wait 60 seconds, retry |
| Server Error | 5xx | Exponential backoff (2^n * 2s), max 3 retries |
| Timeout | N/A | Wait 5 seconds, retry |
| Parse Error | N/A | Log warning, skip paper |
| DB Insert Error | N/A | Log error, don't update progress |

### Progress Update Strategy

**Only update progress on complete success:**

```python
def fetch_papers_by_date(date_str):
    try:
        # 1. Fetch all papers
        papers = fetch_all_papers(date_str)
        if not papers:
            return False  # Don't update progress

        # 2. Transform to rows
        rows = transform_papers_to_rows(papers)
        if not rows:
            return False  # Don't update progress

        # 3. Insert to database
        success = batch_insert(rows)
        if not success:
            return False  # Don't update progress

        # 4. All successful - update progress
        update_progress(date_str, status='completed')
        return True

    except Exception as e:
        log_error(f"Date {date_str} failed: {e}")
        return False  # Don't update progress
```

## Configuration

### Command-Line Arguments

```bash
python src/arxiv_fetcher.py [OPTIONS]

Options:
  --start-date DATE     Start date (default: 2026-04-22)
  --end-year YEAR       End year (default: 1990)
  --interval SECONDS    Request interval (default: 1.0)
  --per-page NUM        Papers per page (default: 3000)
  --dry-run             Test mode, no database writes
```

### Configuration File (Optional)

Create `config/arxiv_config.json`:
```json
{
  "start_date": "2026-04-22",
  "end_year": 1990,
  "request_interval": 1.0,
  "per_page": 3000,
  "batch_threshold": 10000
}
```

## Performance Considerations

### Memory Management

1. **Batch Processing**
   - Write to ClickHouse every 10,000 rows
   - Clear paper lists immediately after writing
   - Use `del` and `gc.collect()` explicitly

2. **XML Parsing**
   - Use feedparser (efficient, well-tested)
   - Parse page-by-page, not all at once

3. **Connection Reuse**
   - Single ClickHouse connection for all dates
   - HTTP connection pooling (requests Session)

### Performance Estimates

- **Papers per day:** 100-500 (CS fields)
- **Authors per paper:** 3-5 average
- **Rows per day:** 500-2,500
- **Processing time per day:** 1-3 seconds
- **Total days:** ~13,500 (2026-04-22 → 1990)
- **Estimated total time:** 4-11 hours

## Testing

### Unit Tests

1. **API Client Tests**
   - Test retry logic
   - Test rate limit handling
   - Test timeout handling

2. **Parser Tests**
   - Test XML parsing with various field combinations
   - Test author extraction
   - Test affiliation handling

3. **Transformer Tests**
   - Test paper-to-row conversion
   - Test rank and tag assignment
   - Test missing field handling

### Integration Tests

1. **End-to-End Test**
   - Fetch 2-3 days of data
   - Verify database inserts
   - Check progress file updates

2. **Error Recovery Test**
   - Simulate network failures
   - Simulate database failures
   - Verify retry logic

### Dry-Run Mode

```bash
python src/arxiv_fetcher.py --dry-run --start-date 2026-04-22 --end-year 2026
```

**Dry-run behavior:**
- Fetch and parse data
- Print statistics
- No database writes
- No progress file updates

## Monitoring and Logging

### Log Files

1. **Main Log:** `log/arxiv_fetch.log`
   - All operations and errors
   - Timestamps for each operation
   - Progress updates

2. **Error Log:** `log/arxiv_errors.log`
   - Only ERROR and WARNING level messages
   - Detailed error traces

3. **Progress File:** `log/arxiv_fetch_progress.json`
   ```json
   {
     "start_date": "2026-04-22",
     "end_year": 1990,
     "total_dates": 13500,
     "completed_dates": ["20260422", "20260421"],
     "last_updated": "2026-04-22 15:30:00"
   }
   ```

### Console Output

**Real-time Progress:**
```
📅 正在获取: 2026-04-22
  📄 第1页: 获取 3000 篇论文
  📄 第2页: 获取 1500 篇论文
  💾 已写入 12650 行
  ✅ 2026-04-22: 完成 4500 篇论文 → 12650 行

📊 进度: 1/13500 (0.0%)
   速度: 1.2 天/秒
   已用时: 0.8 分钟
   预计剩余: 187.5 分钟
```

## Dependencies

### Required Packages

```txt
requests>=2.31.0
feedparser>=6.0.10
clickhouse-connect>=0.6.0
python-dateutil>=2.8.2
tqdm>=4.65.0
```

### Installation

```bash
cd /home/hkustgz/Us/academic-scraper
source venv/bin/activate
pip install requests feedparser clickhouse-connect python-dateutil tqdm
```

## Deployment

### File Structure

```
academic-scraper/
├── src/
│   ├── arxiv_fetcher.py          # Main implementation
│   ├── openalex_fetcher.py       # Existing
│   ├── dblp_fetcher.py          # Existing
│   └── semantic_fetcher.py      # Existing
├── log/
│   ├── arxiv_fetch_progress.json  # Auto-created
│   ├── arxiv_fetch.log           # Auto-created
│   └── arxiv_errors.log          # Auto-created
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-04-22-arxiv-fetcher-design.md
└── venv/
```

### Running the Fetcher

```bash
# Activate virtual environment
cd /home/hkustgz/Us/academic-scraper
source venv/bin/activate

# Run with default settings
python src/arxiv_fetcher.py

# Run with custom settings
python src/arxiv_fetcher.py --start-date 2026-04-01 --end-year 2020

# Dry run (test mode)
python src/arxiv_fetcher.py --dry-run
```

### Stopping and Resuming

**Graceful Shutdown:**
```bash
# Press Ctrl+C to stop
# Progress is automatically saved
```

**Resuming:**
```bash
# Simply run again - it will skip completed dates
python src/arxiv_fetcher.py
```

## Success Criteria

1. ✅ Successfully fetch all papers from 2026-04-22 to 1990
2. ✅ All data correctly stored in ClickHouse
3. ✅ Progress file tracks completed dates accurately
4. ✅ No data loss from failures (retry mechanism works)
5. ✅ Performance within estimated bounds (4-11 hours total)
6. ✅ Memory usage stays below 500MB
7. ✅ Clear logging of all operations and errors

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| arXiv API changes | High | Use standard Atom feed parsing, version checking |
| Rate limit violations | Medium | Conservative 1s interval + 60s pause on 429 |
| Network failures | Medium | Automatic retry with exponential backoff |
| Database connection loss | Low | Connection error handling, retry logic |
| Memory overflow | Low | Batch processing, explicit cleanup |
| Data corruption | Medium | Temporary table deduplication, validation |

## Future Enhancements

1. **Async Version** - Port to asyncio for 3-5x speed improvement
2. **Incremental Updates** - Daily cron job for new papers only
3. **Citation Integration** - JOIN with Semantic Scholar for citations
4. **Full-Text Fetching** - Download PDFs for selected papers
5. **Duplicate Detection** - Cross-reference with OpenAlex/DBLP

## References

- [arXiv API Documentation](https://info.arxiv.org/help/api)
- [arXiv API User Manual](https://info.arxiv.org/help/api/user-manual.html)
- [ClickHouse Python Driver](https://github.com/ClickHouse/clickhouse-connect)
- [feedparser Documentation](https://feedparser.readthedocs.io/)

---

**Document Version:** 1.0
**Last Updated:** 2026-04-22
