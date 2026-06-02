# Academic Scraper Agent Instructions

This file provides repository-specific instructions for `/home/hkustgz/Us/academic-scraper`.

## Model Routing

- For future code-writing or code-modification tasks in this repository, the main GPT-5.5 high agent must act as coordinator only.
- The coordinator owns task intake, context gathering, implementation planning, subagent dispatch, progress reporting, review, integration decisions, and final write-up.
- Actual code implementation, bug fixes, refactors, and test edits must be delegated to a `GPT-5.3-Codex-Spark` subagent whenever subagent tools are available.
- The dispatched coding subagent must receive a concrete, bounded task, the relevant file or module ownership, and an explicit instruction not to revert or overwrite unrelated user changes.
- The coordinator may make direct edits only for non-code documentation or instruction files, or when subagent tools are unavailable or blocked. If the coordinator must edit code directly, it must state the reason clearly before editing.
- The coordinator must review subagent changes before presenting the work as complete, and must run or request appropriate verification for the changed surface.
- After a subagent completes and its result has been reviewed or integrated, close that subagent promptly so it does not continue occupying an agent thread slot.

## Non-Code Work

- The GPT-5.5 high coordinator may directly handle planning, architecture notes, PR descriptions, documentation prose, repo instruction updates, and analysis-only requests.
- Keep changes surgical and scoped to the user's request.

## Communication Rules

- In every assistant response for this repository, address the user as `aplish` exactly once at the beginning of the response and exactly once at the end of the response.
- Keep all other wording concise and task-focused.

## Project Overview

- Academic Scraper collects academic paper data from APIs such as OpenAlex and related sources.
- The main OpenAlex fetcher uses `asyncio` and `httpx` with HTTP/2 for high-concurrency collection.
- Preserve resumability, progress checkpointing, and memory-conscious processing when touching fetcher code.

## Environment And Commands

- Always use the repository virtual environment for Python execution:
  - `/home/hkustgz/Us/academic-scraper/venv/bin/python <script>`
  - Or activate it with `source /home/hkustgz/Us/academic-scraper/venv/bin/activate`.
- Do not use system `python3` directly for project runs or tests; it may miss installed dependencies.
- Main fetcher:
  - `/home/hkustgz/Us/academic-scraper/venv/bin/python -m src.papers.openalex_fetcher`
- Maintenance tools:
  - `/home/hkustgz/Us/academic-scraper/venv/bin/python temp/check_duplicates.py`
  - `/home/hkustgz/Us/academic-scraper/venv/bin/python temp/merge_csv.py`
- If installing dependencies is explicitly approved, use:
  - `/home/hkustgz/Us/academic-scraper/venv/bin/pip install <package>`

## Architecture Notes

- `src/papers/openalex_fetcher.py` is the main async fetcher.
- OpenAlex progress is tracked in `log/papers/openalex/openalex_fetch_progress.json`.
- Output CSV files are organized by source under directories such as `output/openalex/` and `output/arxiv/`.
- Monthly CSV files accumulate multiple days of data.
- Fetching proceeds from newer dates toward older dates and skips already completed dates.
- API rate-limit failures should stop promptly with progress preserved; failed dates must remain retryable.
- For large daily volumes, avoid accumulating paper objects in long-lived parent scopes. Task functions should release fetched paper data after writing and return only statistics where possible.

## File Organization

- Keep root documentation minimal. `README.md`, `AGENTS.md`, and the existing `CLAUDE.md` are allowed in the project root; avoid adding other root-level `.md` files unless the user explicitly asks.
- Prefer Python for project tooling. Avoid adding shell scripts unless there is a concrete need.
- Put core project functionality in the appropriate source directory, usually `src/`.
- Put repository test files in `temp/`, not in a top-level `tests/` directory, unless the user explicitly asks for another location.
- Put one-off or manual utility scripts created for user requests in `temp/`, not `src/`.
- `temp/` scripts are maintenance tools and should not become part of the automatic runtime path unless explicitly promoted.

## Coding Guidelines

- State assumptions when they affect implementation choices.
- Prefer the simplest solution that fully satisfies the request.
- Do not add speculative features, generic abstractions, or configurability that was not requested.
- Keep edits surgical. Do not refactor adjacent code, reformat unrelated sections, or remove pre-existing dead code unless asked.
- Match the existing local style even when a different style would be personally preferred.
- Remove imports, variables, functions, or files only when they were made obsolete by the current change.
- For bug fixes, prefer a reproducing test or command before changing behavior, then verify the same path after the fix.
- For multi-step tasks, use a short plan with explicit verification checks.

## Git Policy

- Do not commit automatically.
- Only create commits when the user explicitly asks for a commit.
