import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docqa.insights import (  # noqa: E402
    daily_volume,
    filter_events,
    read_events,
    summarize,
    top_review_questions,
    top_sources,
    unanswered_csv,
)


def event(
    timestamp: str,
    query: str,
    status: str,
    feedback: str | None = None,
    source: str | None = None,
    missing_terms: list[str] | None = None,
) -> dict:
    return {
        "ts": timestamp,
        "_datetime": datetime.fromisoformat(timestamp),
        "query": query,
        "status": status,
        "feedback": feedback,
        "top_source": source,
        "missing_terms": missing_terms or [],
    }


class TestSupportInsights(unittest.TestCase):
    def test_summary_excludes_feedback_events_from_question_volume(self):
        events = [
            event("2026-10-15T10:00:00", "Reset password", "answer", source="D-01#1"),
            event("2026-10-15T10:01:00", "Reset password", "answer", feedback="up", source="D-01#1"),
            event("2026-10-15T11:00:00", "Salesforce integration?", "no_answer"),
            event("2026-10-15T12:00:00", "Billing dates?", "related"),
            event("2026-10-15T13:00:00", "Short question", "ambiguous"),
        ]
        result = summarize(events)
        self.assertEqual(result["questions"], 4)
        self.assertEqual(result["answered"], 1)
        self.assertEqual(result["needs_review"], 3)
        self.assertEqual(result["positive_feedback"], 1)
        self.assertEqual(result["positive_feedback_rate"], 1.0)
        self.assertEqual(result["answer_rate"], 0.25)

    def test_zero_denominators_return_none(self):
        result = summarize([])
        self.assertIsNone(result["answer_rate"])
        self.assertIsNone(result["positive_feedback_rate"])

    def test_filter_includes_both_boundary_dates(self):
        events = [
            event("2026-10-01T23:59:00", "Before range", "answer"),
            event("2026-10-02T00:00:00", "Start", "answer"),
            event("2026-10-03T12:00:00", "End", "no_answer"),
            event("2026-10-04T00:00:00", "After range", "answer"),
        ]
        result = filter_events(events, date(2026, 10, 2), date(2026, 10, 3))
        self.assertEqual([item["query"] for item in result], ["Start", "End"])

    def test_daily_volume_includes_zero_activity_days(self):
        events = [
            event("2026-10-01T10:00:00", "Answer", "answer"),
            event("2026-10-03T10:00:00", "Gap", "no_answer"),
        ]
        rows = daily_volume(events)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["Answered"], 0)
        self.assertEqual(rows[1]["Needs review"], 0)

    def test_review_questions_group_repeated_text_case_insensitively(self):
        events = [
            event("2026-10-01T10:00:00", "Can I use Salesforce?", "no_answer", missing_terms=["salesforc"]),
            event("2026-10-02T10:00:00", "  CAN I use   Salesforce? ", "related", missing_terms=["salesforc", "integrat"]),
        ]
        rows = top_review_questions(events)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Occurrences"], 2)
        self.assertEqual(rows[0]["Unmatched terms"], "salesforc, integrat")

    def test_sources_and_review_csv(self):
        events = [
            event("2026-10-01T10:00:00", "Password reset", "answer", source="D-01#1"),
            event("2026-10-01T11:00:00", 'Can I export "to Salesforce"?', "no_answer", missing_terms=["salesforc"]),
        ]
        self.assertEqual(top_sources(events), [{"Source passage": "D-01#1", "Answers": 1}])
        csv_data = unanswered_csv(events).decode("utf-8-sig")
        self.assertIn('"Can I export ""to Salesforce""?"', csv_data)
        self.assertIn("salesforc", csv_data)
        self.assertNotIn("Password reset", csv_data)

    def test_reader_reports_bad_records_explicitly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "queries.jsonl"
            path.write_text(
                '{"ts":"2026-10-01T10:00:00","query":"A","status":"answer"}\n'
                'not-json\n',
                encoding="utf-8",
            )
            rows, errors = read_events(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("Line 2", errors[0])


if __name__ == "__main__":
    unittest.main()
