"""Read and summarize the JSONL events used by the Support insights dashboard."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

QUESTION_STATUSES = {"answer", "related", "no_answer", "ambiguous", "empty"}
REVIEW_STATUSES = {"related", "no_answer", "ambiguous"}
_SPACE = re.compile(r"\s+")


def read_events(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read valid log records and report malformed lines instead of hiding them."""
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    log_path = Path(path)
    if not log_path.exists():
        return events, errors

    for line_number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("expected a JSON object")
            timestamp = datetime.fromisoformat(event["ts"])
            query = event["query"]
            status = event["status"]
            if not isinstance(query, str) or not isinstance(status, str):
                raise ValueError("query and status must be strings")
            if status not in QUESTION_STATUSES:
                raise ValueError(f"unsupported status: {status}")
            event["_datetime"] = timestamp
            events.append(event)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"Line {line_number}: {exc}")
    return events, errors


def filter_events(events: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    return [
        event for event in events
        if start <= event["_datetime"].date() <= end
    ]


def question_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event.get("feedback") is None]


def feedback_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event for event in events
        if event.get("feedback") in ("up", "down")
    ]


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    questions = question_events(events)
    feedback = feedback_events(events)
    statuses = Counter(event["status"] for event in questions)
    positive = sum(event.get("feedback") == "up" for event in feedback)
    negative = sum(event.get("feedback") == "down" for event in feedback)
    needs_review = sum(event["status"] in REVIEW_STATUSES for event in questions)
    return {
        "questions": len(questions),
        "answered": statuses["answer"],
        "related": statuses["related"],
        "no_answer": statuses["no_answer"],
        "ambiguous": statuses["ambiguous"],
        "empty": statuses["empty"],
        "needs_review": needs_review,
        "answer_rate": statuses["answer"] / len(questions) if questions else None,
        "positive_feedback": positive,
        "negative_feedback": negative,
        "feedback_count": positive + negative,
        "positive_feedback_rate": positive / (positive + negative) if positive + negative else None,
    }


def daily_volume(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    daily: dict[date, Counter[str]] = defaultdict(Counter)
    for event in question_events(events):
        daily[event["_datetime"].date()][event["status"]] += 1

    if not daily:
        return []
    rows = []
    current = min(daily)
    last = max(daily)
    while current <= last:
        counts = daily[current]
        rows.append(
            {
                "Date": current,
                "Answered": counts["answer"],
                "Needs review": counts["related"] + counts["no_answer"] + counts["ambiguous"],
                "Other": counts["empty"],
            }
        )
        current = date.fromordinal(current.toordinal() + 1)
    return rows


def _normalize_query(query: str) -> str:
    return _SPACE.sub(" ", query.casefold()).strip()


def top_review_questions(events: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for event in question_events(events):
        if event["status"] not in REVIEW_STATUSES:
            continue
        normalized = _normalize_query(event["query"])
        if not normalized:
            continue
        group = groups.setdefault(
            normalized,
            {
                "Question": event["query"].strip(),
                "Occurrences": 0,
                "Statuses": Counter(),
                "Unmatched terms": Counter(),
                "_latest": event["_datetime"],
            },
        )
        group["Occurrences"] += 1
        group["Statuses"][event["status"]] += 1
        group["Unmatched terms"].update(
            term for term in event.get("missing_terms", []) if isinstance(term, str)
        )
        group["_latest"] = max(group["_latest"], event["_datetime"])

    rows = []
    for group in groups.values():
        rows.append(
            {
                "Question": group["Question"],
                "Occurrences": group["Occurrences"],
                "Most common outcome": group["Statuses"].most_common(1)[0][0],
                "Unmatched terms": ", ".join(
                    term for term, _ in group["Unmatched terms"].most_common(5)
                ),
                "_latest": group["_latest"],
            }
        )
    rows.sort(key=lambda row: (-row["Occurrences"], -row["_latest"].timestamp()))
    return [{key: value for key, value in row.items() if key != "_latest"} for row in rows[:limit]]


def top_sources(events: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    sources = Counter(
        event["top_source"]
        for event in question_events(events)
        if event["status"] == "answer" and isinstance(event.get("top_source"), str)
    )
    return [{"Source passage": source, "Answers": count} for source, count in sources.most_common(limit)]


def unanswered_csv(events: list[dict[str, Any]]) -> bytes:
    """Build a spreadsheet-friendly export of filtered questions needing review."""
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["timestamp", "question", "status", "confidence", "unmatched_terms"])
    for event in question_events(events):
        if event["status"] not in REVIEW_STATUSES:
            continue
        writer.writerow(
            [
                event["_datetime"].isoformat(sep=" ", timespec="seconds"),
                event["query"],
                event["status"],
                event.get("confidence", ""),
                ", ".join(
                    term for term in event.get("missing_terms", []) if isinstance(term, str)
                ),
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")
