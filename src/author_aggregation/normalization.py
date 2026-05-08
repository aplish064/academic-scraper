import hashlib
import html
import re
from typing import Optional


DOI_PREFIX_RE = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
PUNCT_TRANSLATION = str.maketrans(
    {
        ".": " ",
        ",": " ",
        ";": " ",
        ":": " ",
        "-": " ",
        "_": " ",
        "(": " ",
        ")": " ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
        "/": " ",
        "\\": " ",
        "\"": " ",
        "'": " ",
        "`": " ",
        "$": "",
        "=": "",
        "^": "",
        "*": " ",
        "!": " ",
        "?": " ",
    }
)


def collapse_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_author_name(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html.unescape(str(value)).lower()
    text = text.translate(PUNCT_TRANSLATION)
    return collapse_space(text)


def normalize_title(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html.unescape(str(value)).lower()
    text = HTML_TAG_RE.sub(" ", text)
    text = text.replace("\\", " ")
    text = text.translate(PUNCT_TRANSLATION)
    return collapse_space(text)


def normalize_doi(value: Optional[str]) -> str:
    if not value:
        return ""
    text = DOI_PREFIX_RE.sub("", str(value).strip()).lower()
    return text.rstrip("/")


def stable_u64(*parts: object) -> int:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.blake2b(value.encode("utf-8"), digest_size=16).hexdigest()[:length]


def build_source_row_key(
    source: str,
    source_paper_id: str,
    author_rank: int,
    source_author_id: str,
    normalized_author_name: str,
) -> str:
    author_component = source_author_id.strip() if source_author_id else f"name_{short_hash(normalized_author_name)}"
    return f"{source}:{source_paper_id}:{author_rank}:{author_component}"
