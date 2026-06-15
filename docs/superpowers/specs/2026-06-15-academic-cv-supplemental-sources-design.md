# Academic CV Supplemental Sources Design

Date: 2026-06-15

Status: Draft for review

## Goal

Extend the Academic CV Builder with conservative supplemental source logic for
ORCID and Semantic Scholar while keeping OpenAlex as the primary identity and
works backbone.

The final CV tables should contain only reliable confirmed facts. Candidate
records, match scores, and disambiguation evidence are internal runtime
mechanics and must not be written to the final CV tables.

## Current Baseline

The current CV Builder creates four final tables under `academic_cv`:

- `personal_profile`
- `education_work_experience`
- `research_outputs`
- `funding_info`

Current source roles:

- ClickHouse `academic_db.OpenAlex` seeds authors and provides local work ID
  fallback candidates.
- OpenAlex Author API provides the primary author record.
- OpenAlex Works API provides current work candidates by author and work
  details.
- ORCID API is used only when OpenAlex already provides an ORCID.
- Crossref API enriches work metadata by DOI.

Recent schema decisions already made:

- `semantic_author_id` is not part of `personal_profile`.
- `dblp_pid` is not part of `personal_profile`.
- The research output table already has a venue field through the existing
  venue column; this design does not add or rename the venue field.

## Scope

In scope:

- Add `h_index` to `personal_profile`.
- Add `citation_count` to `research_outputs`.
- Use OpenAlex author `summary_stats.h_index` as the primary h-index source.
- Use OpenAlex work `cited_by_count` as the primary citation-count source.
- Add a conservative ORCID resolver for cases where OpenAlex has no ORCID.
- Add a conservative Semantic Scholar resolver for work supplementation and
  author disambiguation.
- Keep all resolver candidates, scores, and evidence out of the final four
  CV tables.

Out of scope:

- Adding `semantic_author_id`, `dblp_pid`, or any other external author ID to
  final tables.
- Adding evidence, score, candidate, or match-status columns to final tables.
- Using Semantic Scholar affiliations or homepage as direct profile or
  experience fields.
- Scraping personal homepages or institutional profile pages.
- Renaming the existing venue field.
- Building a manual review workflow.

## Final Table Changes

### `academic_cv.personal_profile`

Add:

```sql
h_index Nullable(UInt32)
```

Recommended column placement:

```text
id
openalex_id
orcid
name
bio
country
email
h_index
source
source_url
import_time
```

Rationale:

- `h_index` can be unknown. `Nullable(UInt32)` avoids treating unknown as true
  zero.
- OpenAlex is the primary source.
- Semantic Scholar may fill this field only after the S2 author identity is
  reliably confirmed through work-level evidence.

### `academic_cv.research_outputs`

Add:

```sql
citation_count Nullable(UInt32)
```

Recommended column placement:

```text
id
author_id
work_title
work_type
venue
publication_date
citation_count
authors
source
source_url
import_time
```

If the implementation code still names the venue column `venue_name`, preserve
that existing field name unless a separate schema rename is explicitly
approved. This design only adds `citation_count`.

Rationale:

- Citation count can be unknown. `Nullable(UInt32)` preserves the distinction
  between unknown and zero.
- OpenAlex work `cited_by_count` is the primary citation source.
- Semantic Scholar `citationCount` may fill this field only for S2 papers that
  are reliably matched to the current author/work.

## Source Priority

### Author profile fields

```text
id: local deterministic ID from OpenAlex author ID
openalex_id: OpenAlex author ID
orcid: OpenAlex ORCID, or confirmed ORCID resolver result
name: OpenAlex author display_name
bio: confirmed ORCID record biography
country: OpenAlex last_known_institutions country code
email: confirmed ORCID record public email
h_index: OpenAlex summary_stats.h_index, then confirmed S2 author hIndex
```

### Education and work experience

Use only confirmed ORCID records.

Do not use Semantic Scholar affiliations for final experience rows because they
usually lack role title, department, city, date range, and provenance precision
needed by the current schema.

### Research outputs

```text
work identity: OpenAlex work ID for OpenAlex-backed rows; deterministic internal ID derived from the best reliable external work key
work_title: Crossref title by DOI, then OpenAlex title, then confirmed S2 title
work_type: Crossref type, then OpenAlex type, then confirmed S2 publication type if mapped safely
venue: existing venue logic; Crossref container-title, OpenAlex source display_name, or confirmed S2 venue
publication_date: Crossref date, then OpenAlex publication_date, then confirmed S2 year/date if available
citation_count: OpenAlex cited_by_count, then confirmed S2 citationCount
authors: author list from the confirmed work source
```

### Funding

Use only confirmed ORCID records.

S2 and Crossref do not provide funding data that maps reliably into the current
`funding_info` table.

## ORCID Supplemental Resolver

### Purpose

Find a reliable ORCID record when OpenAlex has no ORCID for an author.

The resolver is only a supplement. It must not use name search alone to accept
an ORCID.

### Inputs

- OpenAlex author record.
- OpenAlex works already confirmed for the author.
- Work-level DOI, title, publication year, author names, and author rank.

### Candidate recall

ORCID candidates may be recalled by:

- DOI search against ORCID works.
- Exact or highly normalized title search against ORCID works.
- Author name search only as a broad recall fallback.

Name-only recall must never confirm a record.

### Confirmation rules

Confirm an ORCID only when at least one of these rules passes:

1. At least two works with exact DOI matches appear in the same ORCID record.
2. One exact DOI match appears in the ORCID record, and the author name matches
   one known alias with high similarity.
3. Two title/year matches appear in the ORCID record, and the author name
   matches one known alias with high similarity.

Known aliases are built from:

- OpenAlex author `display_name`.
- OpenAlex authorship display names for works attributed to the author.
- ORCID record name fields for the candidate record.

Institution overlap may support a match but must not confirm by itself.

### Output

The resolver returns either:

- a confirmed ORCID string and ORCID record, or
- no result.

It must not return candidates, scores, or evidence to final table builders.

## Semantic Scholar Supplemental Resolver

### Purpose

Use Semantic Scholar for work supplementation and author disambiguation after
OpenAlex establishes the primary author identity.

S2 author search by name is not reliable enough for direct acceptance.

### Inputs

- OpenAlex author record.
- OpenAlex works already confirmed for the author.
- DOI, title, year, author list, and OpenAlex author rank for each work.

### S2 paper matching

For each confirmed OpenAlex work:

1. If DOI exists, query S2 paper by DOI.
2. If DOI does not exist, query S2 paper search by title.
3. Accept the S2 paper only when:
   - DOI matches exactly, or title normalization is highly similar and year is
     compatible.
   - The S2 author list contains an author at the same or nearby rank whose
     name is similar to a known alias.

### S2 author confirmation

Confirm an S2 author only when multiple matched S2 papers point to the same S2
author identity, or when a single DOI-exact matched paper also has strong rank
and name agreement.

Recommended acceptance rules:

1. Strong: two DOI-exact S2 paper matches point to the same S2 author.
2. Acceptable: one DOI-exact S2 paper match points to an S2 author, with same
   author rank and high name similarity.
3. Acceptable: two title/year S2 paper matches point to the same S2 author,
   with high name similarity and no conflicting author rank evidence.

Reject:

- Name-only S2 author search hits.
- Single title-only matches without DOI.
- S2 authors where matched papers point to conflicting S2 author IDs.

### S2 work supplementation

After S2 author confirmation:

1. Fetch S2 author papers.
2. For each S2 paper, check whether it already exists in `research_outputs` by
   DOI or normalized title/year.
3. Add a supplemental research row only when the paper can be attributed to the
   current author by DOI/title, year, author rank, and name similarity.

S2 supplemental works with no DOI are allowed only when title/year and author
attribution are strong. Ambiguous rows are discarded.

### S2 author fields

Allowed internal uses:

- `authorId`: identify the confirmed S2 author during runtime.
- `name`: alias matching.
- `externalIds`: disambiguation support only.
- `paperCount`: sanity check only.
- `citationCount`: sanity check only.
- `hIndex`: may fill `personal_profile.h_index` only after S2 author
  confirmation.
- `papers`: work supplementation.

Not used for final table fields:

- `homepage`
- `affiliations`
- `url`
- raw `externalIds`
- raw `authorId`

## Name Matching

Name matching is supporting evidence, not primary evidence.

Normalize names by:

- lowercasing
- trimming whitespace
- removing punctuation
- collapsing spaces
- comparing both full normalized names and token sets

Build aliases from:

- OpenAlex author display name.
- OpenAlex authorship display names on confirmed works.
- Confirmed ORCID name fields, when available.
- S2 paper author names on already matched papers.

Use name similarity to support DOI/title evidence. Do not accept any ORCID or
S2 identity from name similarity alone.

## Reliability Rules

The pipeline follows this rule:

```text
reliably confirmed -> write final table rows
not reliably confirmed -> discard
```

Do not write any of the following to final CV tables:

- candidate ORCID records
- candidate S2 authors
- match scores
- evidence JSON
- resolver status
- failure reasons
- `semantic_author_id`
- `dblp_pid`

Queue-level operational errors may still be stored in `author_build_queue` as
they are runtime failures, not identity evidence.

## Error Handling

Source failures should degrade conservatively:

- If ORCID resolver fails, keep OpenAlex-only profile fields and do not write
  ORCID-derived child rows.
- If S2 resolver fails, keep OpenAlex and Crossref-derived research rows.
- If Crossref fails for one DOI, keep the OpenAlex work row when OpenAlex work
  details are reliable.
- If OpenAlex author lookup fails, skip the author as current logic already
  does.

API timeouts, 404s, and rate limits should not create partially trusted ORCID
or S2 identity matches.

## Implementation Shape

The later implementation plan should keep responsibilities separated:

- `OpenAlexClient`: existing author/work access plus h-index/citation fields
  already present in returned payloads.
- `OrcidClient`: existing record access plus search helpers for DOI/title
  candidate recall.
- `SemanticScholarClient`: new Graph API client for paper lookup, paper search,
  and confirmed author paper fetch.
- `OrcidResolver`: work-evidence-based ORCID confirmation.
- `SemanticScholarResolver`: work-evidence-based S2 confirmation and
  supplemental works.
- `builders.py`: add h-index and citation count extraction into final rows.
- `schema.py`: add nullable numeric fields.
- `runner.py`: orchestrate resolvers without exposing candidates to final
  tables.

## Validation Strategy

Unit tests should cover:

- `personal_profile` includes `h_index` when OpenAlex provides it.
- `personal_profile.h_index` is null when no reliable source provides it.
- `research_outputs.citation_count` uses OpenAlex `cited_by_count`.
- ORCID resolver rejects name-only matches.
- ORCID resolver accepts DOI-backed matches.
- S2 resolver rejects name-only author search hits.
- S2 resolver confirms an S2 author from DOI/title plus rank/name evidence.
- S2 supplemental works are deduplicated against OpenAlex works.
- Final builders never emit `semantic_author_id`, `dblp_pid`, candidate,
  score, or evidence fields.

Integration checks should cover:

- Processing a sample of 20 authors still produces four CSV files.
- `personal_profile.csv` contains `h_index`.
- `research_outputs.csv` contains `citation_count`.
- All child table `author_id` values still link to `personal_profile.id`.
- No final CSV contains resolver candidate, score, or evidence columns.

## Open Questions

None blocking for implementation.

The current design assumes nullable numeric fields:

- `personal_profile.h_index Nullable(UInt32)`
- `research_outputs.citation_count Nullable(UInt32)`

If ClickHouse export or downstream consumers require empty-string CSV behavior
instead of nullable numeric fields, the implementation plan should explicitly
choose a conversion strategy at export time rather than changing unknown values
to zero in storage.
