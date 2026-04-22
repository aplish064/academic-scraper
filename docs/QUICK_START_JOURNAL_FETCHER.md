# Semantic Scholar Journal Fetcher - Quick Start Guide

## Overview

The Semantic Scholar Journal Fetcher is a Python tool that automatically fetches all papers from a list of academic journals stored in a CSV file. It uses the Semantic Scholar API to validate journals and retrieve their papers, then stores the data in ClickHouse database.

**Key Features:**
- Batch processing of multiple journals
- Automatic journal validation (venue → query strategy)
- Progress tracking with resume capability
- Duplicate detection and removal
- Real-time progress display
- Comprehensive error handling

## Prerequisites

1. **Python 3.8+** with required dependencies:
   ```bash
   pip install requests clickhouse-connect pandas tqdm
   ```

2. **ClickHouse Database** running locally:
   - Host: localhost:8123
   - Database: academic_db
   - Table: semantic

3. **Semantic Scholar API Key** (configured in script)

## Quick Start

### 1. Prepare Your Journal List

Create a CSV file with a `Journal` column containing the journal names:

```csv
Journal
Nature
Science
PNAS
Physical Review Letters
```

Save it as `data/your_journals.csv` (UTF-8 encoding).

### 2. Configure the Script

Edit `src/semantic_fetcher.py` to set the CSV path:

```python
# CSV 配置
CSV_PATH = SCRIPT_DIR / "data/your_journals.csv"
CSV_ENCODING = "utf-8-sig"  # or "utf-8", "gbk"
```

Optional configuration:
```python
# Request rate (seconds between requests)
REQUEST_INTERVAL = 1.1

# Max pages per journal (None = unlimited)
MAX_PAGES_PER_JOURNAL = None

# Papers per API request
PAPERS_PER_REQUEST = 100
```

### 3. Run the Fetcher

```bash
# Using virtual environment (recommended)
venv/bin/python src/semantic_fetcher.py

# Or activate venv first
source venv/bin/activate
python src/semantic_fetcher.py
```

### 4. Monitor Progress

The script displays real-time progress:

```
============================================================
Semantic Scholar 期刊表论文获取器
============================================================
CSV 文件: /path/to/your_journals.csv
查询策略: venue → query
时间范围: 所有年份
请求间隔: 1.1秒
============================================================

📊 加载期刊列表...
   总计: 150 个期刊

🔍 验证期刊有效性...
   进度: ████████████████ 100% 150/150 [00:15<00:00]
   有效: 145 个 | 无效: 5 个

📥 获取论文...
   进度: ████████████░░░░ 80% 120/150 [02:30<00:45]
   已完成:115 进行中:1
```

## Progress Monitoring

### Progress File

Location: `log/journal_progress.json`

```json
{
  "csv_file": "your_journals.csv",
  "csv_loaded_at": "2026-04-22 15:32:59",
  "total_journals": 150,
  "journals": {
    "Nature": {
      "query_type": "query",
      "status": "completed",
      "total_pages": 50,
      "current_page": 50,
      "papers_fetched": 5000,
      "last_updated": "2026-04-22 15:45:30"
    },
    "Science": {
      "query_type": "venue",
      "status": "in_progress",
      "current_page": 25,
      "papers_fetched": 2500,
      "last_updated": "2026-04-22 15:46:10"
    }
  },
  "last_update": "2026-04-22 15:46:10"
}
```

### Journal Statuses

- **pending**: Not yet processed
- **valid**: Validated, ready to fetch
- **in_progress**: Currently fetching
- **completed**: Successfully finished
- **failed**: Validation failed

### Resume Capability

If the script is interrupted (Ctrl+C, error, etc.), simply re-run it. The script will:
- Skip completed journals
- Resume in-progress journals from the last page
- Continue with pending journals

## Troubleshooting

### Issue: CSV File Not Found

**Error:** `CSV文件不存在: /path/to/file.csv`

**Solution:**
- Check the CSV_PATH in the script
- Use absolute path: `Path("/full/path/to/file.csv")`
- Verify file exists and is readable

### Issue: Encoding Errors

**Error:** `UnicodeDecodeError` or CSV encoding issues

**Solution:**
- Try different encodings: `"utf-8"`, `"gbk"`, `"latin-1"`
- Use `"utf-8-sig"` for files with BOM
- Save CSV as UTF-8 without BOM

### Issue: No Valid Journals

**Error:** `没有有效的期刊，程序退出`

**Solution:**
- Check journal names in CSV (must match Semantic Scholar exactly)
- Verify internet connection
- Check API key is valid
- Try manual validation at https://api.semanticscholar.org/graph/v1/paper/search?venue=Nature

### Issue: ClickHouse Connection Failed

**Error:** `ClickHouse连接失败`

**Solution:**
```bash
# Check ClickHouse is running
clickhouse-client --query "SELECT 1"

# Check database exists
clickhouse-client --query "SHOW DATABASES"

# Check table exists
clickhouse-client --query "SHOW TABLES FROM academic_db"
```

### Issue: Rate Limiting

**Warning:** `速率限制，暂停60秒`

**Solution:**
- The script automatically handles rate limits
- Consider increasing REQUEST_INTERVAL
- Free tier: ~100 requests per 5 minutes

### Issue: Memory Issues

**Error:** System becomes slow or crashes

**Solution:**
- Reduce MAX_CONCURRENT_REQUESTS (if using concurrent version)
- Set MAX_PAGES_PER_JOURNAL to limit data
- Process CSV in smaller batches

## Data Storage

### ClickHouse Schema

Papers are stored in the `semantic` table with one row per author:

```sql
CREATE TABLE semantic (
    author_id String,
    author String,
    uid String,        -- Paper ID
    doi String,
    title String,
    rank UInt8,        -- Author position (1=first)
    journal String,
    citation_count UInt32,
    tag String,        -- 第一作者/最后作者/其他
    state String,
    institution_id String,
    institution_name String,
    institution_country String,
    institution_type String,
    raw_affiliation String,
    year UInt16,
    publication_date String,
    venue String,
    journal_name String,
    arxiv_id String,
    pubmed_id String,
    url String,
    abstract String,
    import_date Date,
    import_time DateTime
)
ENGINE = MergeTree()
ORDER BY (uid, rank)
```

### Query Examples

```sql
-- Count papers by journal
SELECT journal_name, COUNT(DISTINCT uid) as paper_count
FROM semantic
GROUP BY journal_name
ORDER BY paper_count DESC;

-- Find papers by first author
SELECT author, title, journal_name, year
FROM semantic
WHERE tag = '第一作者'
AND author LIKE '%Zhang%';

-- Recent papers from Nature
SELECT title, authors, year, citation_count
FROM semantic
WHERE journal_name = 'Nature'
AND year >= 2020
ORDER BY citation_count DESC;
```

## Comparison with Original Version

### Improvements in This Version

1. **Journal Validation**
   - **Before**: No validation, wasted requests on invalid journals
   - **After**: Pre-validates all journals using venue → query strategy

2. **Progress Tracking**
   - **Before**: No resume capability, interruptions meant restarting
   - **After**: Full progress persistence, resume from any point

3. **Error Handling**
   - **Before**: Basic error handling
   - **After**: Comprehensive retry logic, rate limit detection, graceful degradation

4. **Data Quality**
   - **Before**: Potential duplicates
   - **After**: Automatic deduplication using temporary tables

5. **User Experience**
   - **Before**: Limited feedback
   - **After**: Real-time progress bars, detailed logging, clear status indicators

6. **Filtering**
   - **Before**: No filtering
   - **After**: Filters out arXiv-only papers (consistent with original logic)

7. **Author Information**
   - **Before**: Basic author data
   - **After**: Author ranking with tags (第一作者/最后作者/其他)

### Performance Considerations

- **Request Interval**: 1.1 seconds balances speed and API limits
- **Batch Size**: 100 papers per request optimizes network/processing
- **Deduplication**: Temporary table strategy is efficient for large datasets
- **Memory**: Streams data to database, doesn't accumulate in memory

## Advanced Usage

### Processing Large Journal Lists

For CSV files with 1000+ journals:

1. **Split the CSV** into smaller batches:
   ```bash
   # Split into files of 100 journals each
   split -l 101 large_journals.csv batch_
   ```

2. **Run sequentially** to avoid overwhelming the API:
   ```bash
   for file in batch_*; do
       # Update CSV_PATH for each batch
       venv/bin/python src/semantic_fetcher.py
       sleep 300  # 5-minute break between batches
   done
   ```

### Custom Filtering

Edit `paper_to_rows()` to add custom filtering logic:

```python
def paper_to_rows(paper: dict) -> List[Dict[str, Any]]:
    # Add custom filters
    year = paper.get("year", 0)
    if year < 2020:  # Only recent papers
        return []

    # Continue with existing logic...
```

### Integration with Other Tools

```bash
# Export to CSV for analysis
clickhouse-client --query "SELECT * FROM semantic INTO OUTFILE 'papers.csv' FORMAT CSVWithNames"

# Import to visualization tools
clickhouse-client --query "SELECT journal_name, COUNT(*) FROM semantic GROUP BY journal_name" > journal_stats.csv
```

## Logs and Debugging

### Log Files

- **Main Log**: `log/journal_fetch.log` - All operations
- **Error Log**: `log/journal_errors.log` - Errors and warnings only

### Debug Mode

Edit the script to enable verbose logging:

```python
# Add at the top of main()
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Common Log Messages

```
[INFO] ClickHouse连接成功
[INFO] 加载CSV文件: /path/to/file.csv
[INFO] 发现 150 个唯一期刊
[INFO] 验证期刊: Nature
[INFO]   ✓ 期刊有效 (venue查询)
[INFO] 开始获取期刊: Nature (从第0页开始)
[INFO]   第0页: 获取100篇论文, 250行
[WARNING] 速率限制，暂停60秒
[ERROR] 请求失败: HTTP 429
```

## Best Practices

1. **Start Small**: Test with 5-10 journals first
2. **Monitor Progress**: Check journal_progress.json regularly
3. **Handle Errors**: Review error logs after each run
4. **Respect API Limits**: Don't decrease REQUEST_INTERVAL below 1.0
5. **Backup Data**: Export ClickHouse data before large runs
6. **Validate CSV**: Check for encoding issues before running
7. **Use Virtual Environment**: Isolates dependencies

## Support and Contributions

For issues or improvements:
1. Check log files for error details
2. Verify CSV format and encoding
3. Test with a small subset of journals
4. Review ClickHouse connection and table schema

## Summary

This tool provides a robust, production-ready solution for fetching academic papers from Semantic Scholar. With proper configuration and monitoring, it can reliably process thousands of journals and millions of papers while maintaining data quality and integrity.
