"""Identity matching helpers for supplemental CV evidence."""

import re
from difflib import SequenceMatcher
from typing import Iterable, Optional


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_title(value) -> str:
    """Normalize a title for conservative matching comparisons."""
    return _normalize_text(value)


def normalize_name(value) -> str:
    """Normalize a person name for conservative matching comparisons."""
    return _normalize_text(value)


def titles_are_similar(left, right) -> bool:
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)

    if len(left_normalized) < 20 or len(right_normalized) < 20:
        return False
    if left_normalized == right_normalized:
        return True
    return SequenceMatcher(None, left_normalized, right_normalized).ratio() >= 0.94


def names_are_similar(name, aliases: Iterable) -> bool:
    normalized_name = normalize_name(name)
    if not normalized_name:
        return False

    name_tokens = normalized_name.split()
    for alias in aliases or []:
        normalized_alias = normalize_name(alias)
        if not normalized_alias:
            continue
        if normalized_name == normalized_alias:
            return True
        alias_tokens = normalized_alias.split()
        if _has_two_token_overlap_with_same_last_name(name_tokens, alias_tokens):
            return True
        if _initial_last_name_match(name_tokens, alias_tokens):
            return True
        if _same_last_name(name_tokens, alias_tokens) and (
            SequenceMatcher(None, normalized_name, normalized_alias).ratio() >= 0.88
        ):
            return True

    return False


def years_are_compatible(left_year, right_year) -> bool:
    left = _parse_int(left_year)
    right = _parse_int(right_year)
    if left is None or right is None:
        return True
    return left == right


def author_rank_matches(left_rank, right_rank) -> bool:
    left = _parse_int(left_rank)
    right = _parse_int(right_rank)
    if left is None or right is None:
        return False
    return abs(left - right) <= 1


def _normalize_text(value) -> str:
    if value is None:
        return ""
    normalized = _NON_ALNUM_RE.sub(" ", str(value).strip().lower())
    return " ".join(normalized.split())


def _parse_int(value) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _initial_last_name_match(left_tokens, right_tokens) -> bool:
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False

    return _tokens_match_initial_last(left_tokens, right_tokens) or _tokens_match_initial_last(
        right_tokens, left_tokens
    )


def _has_two_token_overlap_with_same_last_name(left_tokens, right_tokens) -> bool:
    if not _same_last_name(left_tokens, right_tokens):
        return False
    return len(set(left_tokens) & set(right_tokens)) >= 2


def _same_last_name(left_tokens, right_tokens) -> bool:
    if not left_tokens or not right_tokens:
        return False
    return left_tokens[-1] == right_tokens[-1]


def _tokens_match_initial_last(full_tokens, initial_tokens) -> bool:
    full_first = full_tokens[0]
    full_last = full_tokens[-1]
    alias_first = initial_tokens[0]
    alias_last = initial_tokens[-1]

    return len(alias_first) == 1 and full_first.startswith(alias_first) and full_last == alias_last
