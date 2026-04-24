from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "we",
}


@dataclass(slots=True)
class ReviewAssessment:
    needs_review: bool
    review_hints: list[str]


def dedupe_validated_entities(
    entity_key: str,
    items: list[dict[str, Any]],
    *,
    max_evidence_items: int,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for item in sorted(items, key=_item_sort_key):
        matched_index = next(
            (index for index, existing in enumerate(deduped) if _items_match(entity_key, existing, item)),
            None,
        )
        if matched_index is None:
            deduped.append(_limit_evidence(item, max_evidence_items))
            continue
        deduped[matched_index] = _merge_items(entity_key, deduped[matched_index], item, max_evidence_items=max_evidence_items)
    return deduped


def normalize_owner(value: Any, evidence_texts: list[str]) -> str | None:
    owner = _nullable_string(value)
    if not owner:
        return None
    evidence_blob = " ".join(text.lower() for text in evidence_texts)
    owner_tokens = [token for token in _text_tokens(owner) if token not in STOPWORDS]
    if not owner_tokens:
        return None
    if all(token in evidence_blob for token in owner_tokens):
        return owner
    return None


def normalize_due_date(value: Any, evidence_texts: list[str]) -> str | None:
    due_date = _nullable_string(value)
    if not due_date:
        return None
    due_date_lower = due_date.lower()
    evidence_blob = " ".join(text.lower() for text in evidence_texts)
    if due_date_lower in evidence_blob:
        return due_date
    due_tokens = [token for token in _text_tokens(due_date) if token not in STOPWORDS]
    if due_tokens and all(token in evidence_blob for token in due_tokens):
        return due_date
    return None


def assess_review(item: dict[str, Any], *, low_confidence_threshold: float) -> ReviewAssessment:
    hints: list[str] = []
    if item.get("review_status") != "accepted":
        hints.append("Pending reviewer validation")
    if float(item.get("confidence") or 0.0) < low_confidence_threshold:
        hints.append("Low extraction confidence")
    if item.get("explicit_or_inferred") == "inferred":
        hints.append("Inference rather than direct statement")
    if len(item.get("evidence") or []) < 2:
        hints.append("Single supporting evidence link")
    if "owner" in item and not item.get("owner"):
        hints.append("Owner not explicitly supported")
    if "due_date" in item and not item.get("due_date"):
        hints.append("Due date not explicitly supported")
    return ReviewAssessment(needs_review=bool(hints), review_hints=hints)


def _items_match(entity_key: str, left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_norm = _normalized_text(left.get("text"))
    right_norm = _normalized_text(right.get("text"))
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return _owner_compatible(left, right)

    similarity = _jaccard(set(left_norm.split()), set(right_norm.split()))
    if entity_key == "action_items":
        return similarity >= 0.62 and _owner_compatible(left, right)
    if entity_key == "decisions":
        return similarity >= 0.68
    if entity_key == "risks_issues":
        return similarity >= 0.66
    if entity_key == "open_questions":
        return similarity >= 0.72
    return similarity >= 0.64


def _merge_items(
    entity_key: str,
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    max_evidence_items: int,
) -> dict[str, Any]:
    merged = dict(left)
    merged["text"] = _preferred_text(left, right)
    merged["confidence"] = round(max(float(left.get("confidence") or 0.0), float(right.get("confidence") or 0.0)), 4)
    merged["explicit_or_inferred"] = (
        "explicit"
        if left.get("explicit_or_inferred") == "explicit" or right.get("explicit_or_inferred") == "explicit"
        else "inferred"
    )
    merged["review_status"] = "pending"
    merged["evidence"] = _merge_evidence(left.get("evidence") or [], right.get("evidence") or [], max_evidence_items)
    if entity_key == "action_items":
        merged["owner"] = _prefer_value(left.get("owner"), right.get("owner"))
        merged["due_date"] = _prefer_value(left.get("due_date"), right.get("due_date"))
        merged["priority"] = _prefer_value(left.get("priority"), right.get("priority"))
    return merged


def _merge_evidence(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    max_evidence_items: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[int | None, int, int]] = set()
    for item in sorted(left + right, key=lambda evidence: (int(evidence.get("start_ms") or 0), int(evidence.get("end_ms") or 0))):
        key = (
            int(item["transcript_segment_id"]) if item.get("transcript_segment_id") is not None else None,
            int(item["start_ms"]),
            int(item["end_ms"]),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged[:max_evidence_items]


def _limit_evidence(item: dict[str, Any], max_evidence_items: int) -> dict[str, Any]:
    normalized = dict(item)
    normalized["evidence"] = _merge_evidence(item.get("evidence") or [], [], max_evidence_items)
    return normalized


def _owner_compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_owner = _nullable_string(left.get("owner"))
    right_owner = _nullable_string(right.get("owner"))
    if not left_owner or not right_owner:
        return True
    return left_owner.lower() == right_owner.lower()


def _preferred_text(left: dict[str, Any], right: dict[str, Any]) -> str:
    left_text = str(left.get("text") or "").strip()
    right_text = str(right.get("text") or "").strip()
    left_confidence = float(left.get("confidence") or 0.0)
    right_confidence = float(right.get("confidence") or 0.0)
    if right_confidence > left_confidence:
        return right_text or left_text
    if left_confidence > right_confidence:
        return left_text or right_text
    return right_text if len(right_text) > len(left_text) else left_text


def _prefer_value(left: Any, right: Any) -> str | None:
    left_value = _nullable_string(left)
    right_value = _nullable_string(right)
    if left_value and right_value:
        return left_value if len(left_value) >= len(right_value) else right_value
    return left_value or right_value


def _item_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    evidence = item.get("evidence") or []
    first_start = int(evidence[0]["start_ms"]) if evidence else 0
    return (first_start, -float(item.get("confidence") or 0.0), str(item.get("text") or ""))


def _normalized_text(value: Any) -> str:
    return " ".join(token for token in _text_tokens(str(value or "")) if token not in STOPWORDS)


def _text_tokens(value: str) -> list[str]:
    tokens = []
    current = []
    for char in value.lower():
        if char.isalnum():
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return [token for token in tokens if len(token) > 1]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _nullable_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
