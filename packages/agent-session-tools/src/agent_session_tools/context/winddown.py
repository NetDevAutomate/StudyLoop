"""Strict, bounded parsing for transactional wind-down requests."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

MAX_REQUEST_BYTES = 256 * 1024
_KINDS = frozenset({"Decision", "Finding", "Problem", "Preference", "Procedure"})
_TAG = re.compile(r"[a-z0-9][a-z0-9._/-]{0,63}\Z")
_CONCEPT_FIELDS = frozenset(
    {"type", "title", "description", "tags", "confidence", "quotes"}
)
_QUOTE_FIELDS = frozenset({"quote", "evidence_id", "start", "end"})
_LOCATOR_FIELDS = frozenset({"evidence_id", "start", "end"})
type Kind = Literal["Decision", "Finding", "Problem", "Preference", "Procedure"]


@dataclass(frozen=True)
class _Issue:
    """Stable JSON-pointer-like validation issue."""

    path: str
    code: str
    message: str


@dataclass(frozen=True)
class _Quote:
    """A literal quote, optionally carrying its complete evidence locator."""

    quote: str
    evidence_id: str | None = None
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class _Concept:
    """Canonical validated wind-down concept."""

    kind: Kind
    title: str
    description: str
    tags: tuple[str, ...]
    confidence: float
    quotes: tuple[_Quote, ...]


class _DuplicateKey(ValueError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(key)


class _InvalidConstant(ValueError):
    pass


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _issue(path: str, code: str, message: str) -> _Issue:
    return _Issue(path=path, code=code, message=message)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _constant(value: str) -> Any:
    raise _InvalidConstant(value)


def _serialized(document: object) -> tuple[Any | None, tuple[_Issue, ...]]:
    if isinstance(document, bytes):
        raw_bytes = document
        try:
            raw = document.decode("utf-8")
        except UnicodeDecodeError:
            return None, (_issue("/", "invalid_json", "Request must be UTF-8 JSON"),)
    elif isinstance(document, str):
        raw = document
        raw_bytes = document.encode("utf-8")
    else:
        try:
            raw = json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return None, (
                _issue("/", "invalid_document", "Request must contain JSON values"),
            )
        raw_bytes = raw.encode("utf-8")
    if len(raw_bytes) > MAX_REQUEST_BYTES:
        return None, (
            _issue(
                "/",
                "request_too_large",
                f"Serialized request exceeds {MAX_REQUEST_BYTES} bytes",
            ),
        )
    try:
        return (
            json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant),
            (),
        )
    except _DuplicateKey as exc:
        return None, (
            _issue(
                "/",
                "duplicate_key",
                f"Duplicate JSON object key: {exc.key}",
            ),
        )
    except (json.JSONDecodeError, _InvalidConstant):
        return None, (_issue("/", "invalid_json", "Request must be valid JSON"),)


def _exact_fields(
    value: dict[str, Any],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
    path: str,
) -> list[_Issue]:
    issues = [
        _issue(f"{path}/{_pointer(key)}", "missing_field", f"Missing field: {key}")
        for key in sorted(required - value.keys())
    ]
    issues.extend(
        _issue(f"{path}/{_pointer(key)}", "extra_field", f"Unexpected field: {key}")
        for key in sorted(value.keys() - allowed)
    )
    return issues


def _bounded_text(
    value: Any,
    *,
    path: str,
    maximum: int,
    trim: bool,
) -> tuple[str | None, list[_Issue]]:
    if not isinstance(value, str):
        return None, [_issue(path, "invalid_type", "Value must be text")]
    canonical = value.strip() if trim else value
    if not value.strip():
        return None, [_issue(path, "blank", "Value must not be blank")]
    if len(canonical) > maximum:
        return None, [
            _issue(path, "too_long", f"Value must be at most {maximum} code points")
        ]
    return canonical, []


def _validate_quotes(value: Any, path: str) -> tuple[tuple[_Quote, ...], list[_Issue]]:
    if not isinstance(value, list):
        return (), [_issue(path, "invalid_type", "Quotes must be an array")]
    issues: list[_Issue] = []
    if len(value) < 1:
        issues.append(_issue(path, "too_few_items", "At least one quote is required"))
    if len(value) > 8:
        issues.append(
            _issue(path, "too_many_items", "At most eight quotes are allowed")
        )
    parsed: list[_Quote] = []
    seen: set[tuple[str, str | None, int | None, int | None]] = set()
    for index, raw in enumerate(value):
        quote_path = f"{path}/{index}"
        before = len(issues)
        if not isinstance(raw, dict):
            issues.append(_issue(quote_path, "invalid_type", "Quote must be an object"))
            continue
        issues.extend(
            _exact_fields(
                raw,
                required=frozenset({"quote"}),
                allowed=_QUOTE_FIELDS,
                path=quote_path,
            )
        )
        quote, quote_issues = _bounded_text(
            raw.get("quote"),
            path=f"{quote_path}/quote",
            maximum=2000,
            trim=False,
        )
        issues.extend(quote_issues)
        present = _LOCATOR_FIELDS.intersection(raw)
        if present and present != _LOCATOR_FIELDS:
            issues.append(
                _issue(
                    quote_path,
                    "incomplete_locator",
                    "evidence_id, start, and end must be supplied together",
                )
            )
        evidence_id: str | None = None
        start: int | None = None
        end: int | None = None
        if present == _LOCATOR_FIELDS:
            evidence_id, evidence_issues = _bounded_text(
                raw.get("evidence_id"),
                path=f"{quote_path}/evidence_id",
                maximum=128,
                trim=True,
            )
            issues.extend(evidence_issues)
            raw_start = raw.get("start")
            raw_end = raw.get("end")
            if type(raw_start) is not int:
                issues.append(
                    _issue(
                        f"{quote_path}/start",
                        "invalid_type",
                        "Offset must be an integer Unicode code-point offset",
                    )
                )
            else:
                start = raw_start
            if type(raw_end) is not int:
                issues.append(
                    _issue(
                        f"{quote_path}/end",
                        "invalid_type",
                        "Offset must be an integer Unicode code-point offset",
                    )
                )
            else:
                end = raw_end
            if (
                type(raw_start) is int
                and type(raw_end) is int
                and not (0 <= raw_start < raw_end)
            ):
                issues.append(
                    _issue(
                        quote_path,
                        "invalid_range",
                        "Locator must satisfy 0 <= start < end",
                    )
                )
        if len(issues) != before or quote is None:
            continue
        item = _Quote(quote=quote, evidence_id=evidence_id, start=start, end=end)
        key = (item.quote, item.evidence_id, item.start, item.end)
        if key in seen:
            issues.append(
                _issue(quote_path, "duplicate_item", "Quote objects must be unique")
            )
            continue
        seen.add(key)
        parsed.append(item)
    return tuple(parsed), issues


def _parse_winddown(
    document: object,
) -> tuple[tuple[_Concept, ...], tuple[_Issue, ...]]:
    """Parse and validate one strict wind-down request without performing writes."""
    value, serialization_issues = _serialized(document)
    if serialization_issues:
        return (), serialization_issues
    if not isinstance(value, dict):
        return (), (_issue("/", "invalid_type", "Request must be an object"),)
    issues = _exact_fields(
        value,
        required=frozenset({"concepts"}),
        allowed=frozenset({"concepts"}),
        path="",
    )
    raw_concepts = value.get("concepts")
    if not isinstance(raw_concepts, list):
        issues.append(_issue("/concepts", "invalid_type", "Concepts must be an array"))
        return (), tuple(issues)
    if len(raw_concepts) > 8:
        issues.append(
            _issue("/concepts", "too_many_items", "At most eight concepts are allowed")
        )
    parsed: list[_Concept] = []
    seen_concepts: set[tuple[str, str, str, tuple[str, ...], float]] = set()
    for index, raw in enumerate(raw_concepts):
        path = f"/concepts/{index}"
        before = len(issues)
        if not isinstance(raw, dict):
            issues.append(_issue(path, "invalid_type", "Concept must be an object"))
            continue
        issues.extend(
            _exact_fields(
                raw,
                required=_CONCEPT_FIELDS,
                allowed=_CONCEPT_FIELDS,
                path=path,
            )
        )
        raw_kind = raw.get("type")
        kind: str | None = None
        if not isinstance(raw_kind, str):
            issues.append(_issue(f"{path}/type", "invalid_type", "Type must be text"))
        elif raw_kind not in _KINDS:
            issues.append(
                _issue(f"{path}/type", "invalid_choice", "Unknown concept type")
            )
        else:
            kind = raw_kind
        title, title_issues = _bounded_text(
            raw.get("title"), path=f"{path}/title", maximum=120, trim=True
        )
        issues.extend(title_issues)
        if title is not None and len(re.findall(r"\w+", title, flags=re.UNICODE)) > 12:
            issues.append(
                _issue(
                    f"{path}/title",
                    "too_many_words",
                    "Title must contain at most twelve Unicode words",
                )
            )
        description, description_issues = _bounded_text(
            raw.get("description"),
            path=f"{path}/description",
            maximum=4000,
            trim=True,
        )
        issues.extend(description_issues)
        raw_tags = raw.get("tags")
        tags: tuple[str, ...] = ()
        if not isinstance(raw_tags, list):
            issues.append(
                _issue(f"{path}/tags", "invalid_type", "Tags must be an array")
            )
        else:
            if len(raw_tags) < 2:
                issues.append(
                    _issue(
                        f"{path}/tags",
                        "too_few_items",
                        "At least two tags are required",
                    )
                )
            if len(raw_tags) > 5:
                issues.append(
                    _issue(
                        f"{path}/tags",
                        "too_many_items",
                        "At most five tags are allowed",
                    )
                )
            valid_tags: list[str] = []
            seen_tags: set[str] = set()
            for tag_index, tag in enumerate(raw_tags):
                tag_path = f"{path}/tags/{tag_index}"
                if not isinstance(tag, str):
                    issues.append(_issue(tag_path, "invalid_type", "Tag must be text"))
                elif not _TAG.fullmatch(tag):
                    issues.append(
                        _issue(tag_path, "invalid_format", "Tag has an invalid format")
                    )
                elif tag in seen_tags:
                    issues.append(
                        _issue(tag_path, "duplicate_item", "Tags must be unique")
                    )
                else:
                    seen_tags.add(tag)
                    valid_tags.append(tag)
            tags = tuple(sorted(valid_tags))
        raw_confidence = raw.get("confidence")
        confidence: float | None = None
        if isinstance(raw_confidence, bool) or not isinstance(
            raw_confidence, (int, float)
        ):
            issues.append(
                _issue(
                    f"{path}/confidence",
                    "invalid_type",
                    "Confidence must be numeric but not boolean",
                )
            )
        elif (
            not math.isfinite(float(raw_confidence)) or not 0.5 <= raw_confidence <= 1.0
        ):
            issues.append(
                _issue(
                    f"{path}/confidence",
                    "out_of_range",
                    "Confidence must be between 0.5 and 1.0",
                )
            )
        else:
            confidence = float(raw_confidence)
        quotes, quote_issues = _validate_quotes(raw.get("quotes"), f"{path}/quotes")
        issues.extend(quote_issues)
        if (
            len(issues) != before
            or kind is None
            or title is None
            or description is None
            or confidence is None
        ):
            continue
        canonical = (kind, title, description, tags, confidence)
        if canonical in seen_concepts:
            issues.append(
                _issue(path, "duplicate_concept", "Canonical concepts must be unique")
            )
            continue
        seen_concepts.add(canonical)
        parsed.append(
            _Concept(
                kind=cast(Kind, kind),
                title=title,
                description=description,
                tags=tags,
                confidence=confidence,
                quotes=quotes,
            )
        )
    return tuple(parsed), tuple(issues)


def _parse_bind_document(
    document: object,
) -> tuple[tuple[_Quote, ...], tuple[_Issue, ...]]:
    """Parse a strict legacy-bind request containing quote locators only."""
    value, serialization_issues = _serialized(document)
    if serialization_issues:
        return (), serialization_issues
    if not isinstance(value, dict):
        return (), (_issue("/", "invalid_type", "Request must be an object"),)
    issues = _exact_fields(
        value,
        required=frozenset({"quotes"}),
        allowed=frozenset({"quotes"}),
        path="",
    )
    quotes, quote_issues = _validate_quotes(value.get("quotes"), "/quotes")
    issues.extend(quote_issues)
    return quotes, tuple(issues)
