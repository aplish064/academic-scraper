"""Row builders for reliable academic CV table imports."""

from __future__ import annotations

from datetime import datetime
import json
import re
from urllib.parse import urlsplit

from .ids import (
    make_experience_id,
    make_funding_id,
    make_person_id,
    make_research_output_id,
)


_OPENALEX_AUTHOR_ID_RE = re.compile(r"^A\d+$", re.IGNORECASE)
_OPENALEX_WORK_ID_RE = re.compile(r"^W\d+$", re.IGNORECASE)
_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", re.IGNORECASE)
_EMPTY_SENTINELS = {"", "nan", "none", "null", "<na>"}


def clean_text(value) -> str:
    """Return a stripped string, treating common missing-value tokens as empty."""
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    text = " ".join(str(value).strip().split())
    if text.lower() in _EMPTY_SENTINELS:
        return ""
    return text


def _non_negative_int_or_none(value):
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def normalize_openalex_id(value: str) -> str:
    """Normalize an OpenAlex author ID to its compact A... form."""
    return _normalize_openalex_entity_id(value, _OPENALEX_AUTHOR_ID_RE, "A")


def normalize_orcid(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    candidate = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    if not _ORCID_RE.fullmatch(candidate):
        return ""
    return candidate


def extract_orcid_bio(orcid_record: dict) -> str:
    biography = (((orcid_record or {}).get("person") or {}).get("biography") or {})
    return clean_text(biography.get("content"))


def extract_orcid_email(orcid_record: dict) -> str:
    emails = ((((orcid_record or {}).get("person") or {}).get("emails") or {}).get("email") or [])
    for email in _ensure_list(emails):
        if not isinstance(email, dict):
            continue
        visibility = clean_text(email.get("visibility")).lower()
        if visibility and visibility != "public":
            continue
        value = clean_text(email.get("email"))
        if value:
            return value
    return ""


def build_profile_row(openalex_author: dict, orcid_record: dict) -> dict:
    author = openalex_author or {}
    record = orcid_record or {}
    openalex_id = normalize_openalex_id(author.get("id") or author.get("openalex_id"))
    if not openalex_id:
        return {}
    orcid = normalize_orcid(_orcid_record_path(record) or author.get("orcid"))

    return {
        "id": make_person_id(openalex_id),
        "openalex_id": openalex_id,
        "orcid": orcid,
        "name": clean_text(author.get("display_name")),
        "bio": extract_orcid_bio(record),
        "country": _openalex_country(author),
        "email": extract_orcid_email(record),
        "h_index": _non_negative_int_or_none((author.get("summary_stats") or {}).get("h_index")),
        "source": "openalex+orcid" if record else "openalex",
        "source_url": _openalex_source_url(author.get("id"), openalex_id),
        "import_time": datetime.now(),
    }


def build_experience_rows(person_id: str, orcid_record: dict) -> list:
    if not clean_text(person_id):
        return []
    rows = []
    for section, summary_key, affiliation_type in (
        ("employments", "employment-summary", "employment"),
        ("educations", "education-summary", "education"),
    ):
        for item in _iter_orcid_affiliation_summaries(orcid_record, section, summary_key):
            organization = item.get("organization") or {}
            address = organization.get("address") or {}
            institution_name = clean_text(organization.get("name"))
            if not institution_name:
                continue

            role_title = clean_text(item.get("role-title"))
            start_date = _date_part(item.get("start-date"))
            end_date = _date_part(item.get("end-date"))
            external_id = clean_text(item.get("put-code")) or clean_text(item.get("path"))
            department_name = clean_text(item.get("department-name"))
            rows.append(
                {
                    "id": make_experience_id(
                        person_id,
                        "orcid",
                        role_title,
                        institution_name,
                        start_date,
                        end_date,
                        external_id=external_id,
                        department_name=department_name,
                    ),
                    "author_id": person_id,
                    "role_title": role_title,
                    "institution_name": institution_name,
                    "department_name": department_name,
                    "city": clean_text(address.get("city")),
                    "affiliation_type": affiliation_type,
                    "province": clean_text(address.get("region")),
                    "date_range": _date_range(start_date, end_date),
                    "country": clean_text(address.get("country")),
                    "source": "orcid",
                    "source_url": _orcid_record_source_url(orcid_record),
                    "import_time": datetime.now(),
                }
            )
    return rows


def build_research_output_row(person_id: str, openalex_work: dict, crossref_work: dict) -> dict:
    if not clean_text(person_id):
        return {}
    work = openalex_work or {}
    crossref = crossref_work or {}
    work_id = _normalize_openalex_work_id(work.get("id") or work.get("openalex_id"))
    if not work_id:
        return {}

    title = _first_list_value(crossref.get("title")) or clean_text(work.get("title") or work.get("display_name"))
    if not title:
        return {}

    source = ((work.get("primary_location") or {}).get("source") or {})
    host_venue = work.get("host_venue") or {}
    work_type = clean_text(crossref.get("type")) or clean_text(work.get("type"))
    venue_name = (
        _first_list_value(crossref.get("container-title"))
        or clean_text(source.get("display_name"))
        or clean_text(host_venue.get("display_name"))
    )
    publication_date = _crossref_date(crossref) or clean_text(work.get("publication_date"))

    authors = [
        clean_text((authorship.get("author") or {}).get("display_name"))
        for authorship in _ensure_list(work.get("authorships"))
        if isinstance(authorship, dict)
    ]
    authors = [author for author in authors if author]

    return {
        "id": make_research_output_id(person_id, work_id),
        "author_id": person_id,
        "work_title": title,
        "work_type": work_type,
        "venue_name": venue_name,
        "publication_date": publication_date,
        "citation_count": _non_negative_int_or_none(work.get("cited_by_count")),
        "authors": json.dumps(authors, ensure_ascii=False),
        "source": "openalex+crossref" if crossref else "openalex",
        "source_url": _openalex_source_url(work.get("id"), work_id),
        "import_time": datetime.now(),
    }


def build_funding_rows(person_id: str, orcid_record: dict) -> list:
    if not clean_text(person_id):
        return []
    rows = []
    for item in _iter_orcid_funding_summaries(orcid_record):
        organization = item.get("organization") or {}
        address = organization.get("address") or {}
        award_title = _funding_title(item)
        funder_name = clean_text(organization.get("name"))
        if not award_title and not funder_name:
            continue

        start_date = _date_part(item.get("start-date"))
        end_date = _date_part(item.get("end-date"))
        funding_external_id = (
            clean_text(item.get("put-code"))
            or clean_text(item.get("path"))
            or "|".join([award_title, funder_name, start_date, end_date, clean_text(item.get("type"))])
        )
        rows.append(
            {
                "id": make_funding_id(person_id, "orcid", funding_external_id, funder_name, award_title),
                "author_id": person_id,
                "end_date": end_date,
                "award_title": award_title,
                "city": clean_text(address.get("city")),
                "funder_name": funder_name,
                "province": clean_text(address.get("region")),
                "funding_type": clean_text(item.get("type")),
                "country": clean_text(address.get("country")),
                "start_date": start_date,
                "source": "orcid",
                "source_url": _orcid_item_source_url(orcid_record, item),
                "import_time": datetime.now(),
            }
        )
    return rows


def _normalize_openalex_entity_id(value, pattern: re.Pattern[str], prefix: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parsed = urlsplit(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    candidate = path.strip().rstrip("/").rsplit("/", 1)[-1].upper()
    if pattern.fullmatch(candidate):
        return candidate
    return ""


def _normalize_openalex_work_id(value) -> str:
    return _normalize_openalex_entity_id(value, _OPENALEX_WORK_ID_RE, "W")


def _openalex_source_url(raw_id, normalized_id: str) -> str:
    raw = clean_text(raw_id)
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if normalized_id:
        return f"https://openalex.org/{normalized_id}"
    return ""


def _openalex_country(openalex_author: dict) -> str:
    for institution in _ensure_list((openalex_author or {}).get("last_known_institutions")):
        if not isinstance(institution, dict):
            continue
        country = clean_text(institution.get("country_code"))
        if country:
            return country
    return ""


def _orcid_record_path(orcid_record: dict) -> str:
    identifier = ((orcid_record or {}).get("orcid-identifier") or {})
    return clean_text(identifier.get("path") or identifier.get("uri"))


def _orcid_record_source_url(orcid_record: dict) -> str:
    orcid = normalize_orcid(_orcid_record_path(orcid_record))
    if not orcid:
        return ""
    return f"https://orcid.org/{orcid}"


def _orcid_item_source_url(orcid_record: dict, item: dict) -> str:
    path = clean_text(item.get("path"))
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/"):
        return f"https://orcid.org{path}"
    if path:
        return f"https://orcid.org/{path}"
    return _orcid_record_source_url(orcid_record)


def _ensure_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _date_part(date_obj) -> str:
    if not isinstance(date_obj, dict):
        return ""
    year = clean_text((date_obj.get("year") or {}).get("value"))
    if not year:
        return ""
    month = clean_text((date_obj.get("month") or {}).get("value"))
    day = clean_text((date_obj.get("day") or {}).get("value"))
    if month:
        month = month.zfill(2)
    if day:
        day = day.zfill(2)
    if day and month:
        return f"{year}-{month}-{day}"
    if month:
        return f"{year}-{month}"
    return year


def _date_range(start_date: str, end_date: str) -> str:
    if start_date or end_date:
        return f"{start_date}-{end_date}"
    return ""


def _iter_orcid_affiliation_summaries(orcid_record: dict, section: str, summary_key: str):
    section_payload = ((((orcid_record or {}).get("activities-summary") or {}).get(section) or {}))
    groups = _ensure_list(section_payload.get("affiliation-group"))
    for group in groups:
        if not isinstance(group, dict):
            continue
        for summary in _ensure_list(group.get("summaries")):
            if not isinstance(summary, dict):
                continue
            item = summary.get(summary_key) or summary
            if isinstance(item, dict) and item:
                yield item


def _iter_orcid_funding_summaries(orcid_record: dict):
    fundings = ((((orcid_record or {}).get("activities-summary") or {}).get("fundings") or {}))
    for group in _ensure_list(fundings.get("group")):
        if not isinstance(group, dict):
            continue
        for summary in _ensure_list(group.get("funding-summary")):
            if isinstance(summary, dict) and summary:
                yield summary


def _first_list_value(value) -> str:
    for item in _ensure_list(value):
        text = clean_text(item)
        if text:
            return text
    return ""


def _crossref_date(crossref_work: dict) -> str:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        date_parts = (((crossref_work or {}).get(key) or {}).get("date-parts") or [])
        if not date_parts:
            continue
        parts = [clean_text(part) for part in _ensure_list(date_parts[0])]
        parts = [part for part in parts if part]
        if not parts:
            continue
        if len(parts) >= 3:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
        if len(parts) == 2:
            return f"{parts[0]}-{parts[1].zfill(2)}"
        return parts[0]
    return ""


def _funding_title(item: dict) -> str:
    title = item.get("title") or {}
    if isinstance(title, dict):
        nested_title = title.get("title") or {}
        if isinstance(nested_title, dict):
            value = clean_text(nested_title.get("value"))
            if value:
                return value
        value = clean_text(title.get("value"))
        if value:
            return value
    return clean_text(title)
