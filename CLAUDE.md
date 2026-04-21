# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Academic Scraper is a high-performance academic paper data collection system that fetches papers from OpenAlex API. The project uses async I/O with HTTP/2 to achieve 20-50x speed improvements over traditional synchronous approaches.

## Key Commands

### Running the Main Fetcher
```bash
python3 src/openalex_fetcher.py
```
The script automatically resumes from the last checkpoint using `log/openalex_fetch_progress.json`.

### Data Maintenance Tools
```bash
# Check for duplicate records in CSV files
python3 temp/check_duplicates.py

# Merge CSV files
python3 temp/merge_csv.py
```

### Dependencies
```bash
pip install httpx tqdm
```

### Environment Setup

**IMPORTANT - Always use virtual environment for testing and running:**

The project uses a Python virtual environment located at `/home/hkustgz/Us/academic-scraper/venv`. All dependencies are already installed there.

**When running or testing any Python code:**
```bash
# Use the virtual environment Python
/home/hkustgz/Us/academic-scraper/venv/bin/python <script>

# Or activate the virtual environment first
source /home/hkustgz/Us/academic-scraper/venv/bin/activate
python <script>
```

**Examples:**
```bash
# Running the dashboard API server
cd /home/hkustgz/Us/academic-scraper/dashboard
../venv/bin/python api_server.py

# Running database queries
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "import clickhouse_connect; ..."

# Installing packages (if needed)
/home/hkustgz/Us/academic-scraper/venv/bin/pip install <package>
```

**Never use system Python3 directly** - it may not have all required packages installed, causing import errors.

## Architecture

### Core Components

**openalex_fetcher.py** - Main async fetcher
- Uses `asyncio` + `httpx` with HTTP/2 for concurrent requests
- Processes dates in reverse order (newest to oldest)
- Implements rate limit detection and automatic stopping
- Memory-optimized: releases data immediately after writing to CSV
- Progress checkpointing after each completed date

**Data Flow**:
1. Generates date range from `START_DATE` backwards to `END_YEAR`
2. Filters out already-completed dates from progress file
3. Launches concurrent tasks (default: 20 parallel)
4. Each task fetches one day of papers from OpenAlex API
5. Papers are expanded into author-level rows and appended to monthly CSV files
6. Progress is saved after each completed date

**CSV Organization**:
- Files are organized by data source: `output/openalex/` and `output/arxiv/`
- Files are named `{year}_{month}.csv` (simplified naming)
- Multiple days' data accumulates in the same monthly file
- Format: `author, uid, doi, title, rank, journal, citation_count, tag, state`

**Progress Management**:
- `log/openalex_fetch_progress.json` tracks completed dates
- Dates with zero papers are NOT saved (will retry on next run)
- API rate limit errors trigger immediate shutdown with progress saved
- Supports graceful interruption and resumption

### Memory Management

Critical for handling large daily paper volumes (30k+ papers):
- Paper data is stored in per-task local variables (`all_papers`)
- After writing to CSV, only statistics are returned (not the data itself)
- The `all_papers` list is garbage-collected when the task function returns
- Main function only accumulates counts, not paper objects

### Rate Limiting

OpenAlex free tier has daily request limits:
- On 429 error, checks response JSON for "Rate limit exceeded"
- If limit exceeded, prints retry time and exits immediately
- Does NOT mark failed dates as completed (will retry later)
- Resets at UTC midnight (~22 hours from exhaustion)

### File Organization Rules

**IMPORTANT** - Follow these rules when creating files:

1. **Documentation**: Only `README.md` is allowed in project root. No other `.md` files (e.g., no `quickstart.md`, `contributing.md`, etc.) except when creating skills.

2. **Scripts**: Avoid creating excessive `.sh` or script files. Use Python for tooling.

3. **Code Placement**:
   - If implementing core project functionality → place in appropriate directory (e.g., `src/`)
   - If creating utility scripts to fulfill user requests → MUST place in `temp/` directory

4. **temp/ Directory**:
   - Contains maintenance tools (e.g., `check_duplicates.py`, `merge_csv.py`)
   - For scripts created in response to user instructions
   - Not part of core functionality
   - Scripts are run manually, not automatically

Example: When user asked to check for duplicates and merge CSVs, those tools were created in `temp/`, not `src/`.

### Configuration

Key constants in `openalex_fetcher.py`:
- `START_DATE`: Where to begin fetching (format: YYYYMMDD)
- `END_YEAR`: How far back to fetch
- `MAX_CONCURRENT_REQUESTS`: Number of parallel requests (default: 20)
- `REQUEST_TIMEOUT`: HTTP timeout in seconds
- `MAX_RETRIES`: Retry attempts for transient failures

### Output Files

- **CSV files**: `output/{year}_{month}_openalex_papers.csv`
  - One file per month
  - Multiple days append to same file
  - Format: UTF-8-BOM encoded CSV with all fields quoted

- **Progress file**: `log/openalex_fetch_progress.json`
  ```json
  {
    "current_date": "20260201",
    "completed_dates": ["20260331", "20260330", ...],
    "last_update": "2026-04-13 09:41:07"
  }
  ```

- **Log file**: `log/openalex_fetch_fast.log`
  - Session start/end timestamps
  - Per-date fetch results (paper count, row count, file path)

### Error Handling

- **API Rate Limit**: Immediate shutdown with progress saved
- **HTTP 5xx**: Retry with exponential backoff
- **Timeout**: Retry up to MAX_RETRIES times
- **SSLError**: Retry with longer delays
- **No data**: Date is NOT marked complete (will retry)
- **Other errors**: Logged but date marked incomplete

### Common Issues

**OOM (Out of Memory)**: Caused by returning paper data in task results. Fixed by only returning statistics.

**No papers fetched**: Usually API rate limit exhausted. Check log for "Rate limit exceeded" message.

**Progress file corruption**: Use `temp/check_duplicates.py` to validate and clean.

**Duplicate records**: Run `temp/check_duplicates.py` to verify data integrity.

---

## AI Coding Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### 5. Git Commit Policy

**Do NOT commit automatically unless explicitly asked.**

- User handles all git commits themselves
- Only commit when user explicitly requests it
- If user wants a commit, they will ask: "commit this" or "create a commit"
- Exception: When explicitly told to "commit after each change" or similar

**Rationale:** User prefers control over their git history and will manage commits themselves.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
