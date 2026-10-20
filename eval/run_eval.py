"""Run the provided or custom golden question set. Exit code 1 on any failure.

    python eval/run_eval.py
    python eval/run_eval.py --docs data/docs --questions eval/questions.json
Metrics that matter for this customer: a wrong ANSWER to an out-of-scope question
(hallucination) is counted separately and is the headline number.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docqa.engine import Assistant, Config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--questions",
        default=str(ROOT / "starter_kit" / "data" / "example_questions.json"),
    )
    ap.add_argument("--docs", default=str(ROOT / "starter_kit" / "data"))
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    bot = Assistant(a.docs, Config(use_llm=a.llm))
    question_data = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    cases = question_data.get("example_questions", []) if isinstance(question_data, dict) else question_data
    if not isinstance(cases, list) or not cases:
        ap.error("The questions file must contain a non-empty list of examples")

    fails, false_answers = 0, 0
    for c in cases:
        query = c.get("q", c.get("question"))
        expected_doc = c.get("article", c.get("expected_doc_id"))
        expected = c.get("expect", "answer" if expected_doc else "no_answer")
        if not isinstance(query, str) or not query.strip():
            ap.error("Each example must include a non-empty 'q' or 'question'")
        r = bot.ask(query)
        ok = r.status == expected
        if ok and expected == "answer":
            ok = any(s.chunk.article_id == expected_doc for s in r.sources)
            text = r.message + " " + " ".join(s.chunk.text for s in r.sources)
            ok = ok and all(m.lower() in text.lower() for m in c.get("must_contain", []))
        if expected != "answer" and r.status == "answer":
            false_answers += 1
        fails += (not ok)
        print(f"{'PASS' if ok else 'FAIL'}  [{r.status:<9} conf={r.confidence:.2f}] {query}")
        if a.verbose or not ok:
            print(f"        expected={expected} missing={r.missing_terms} "
                  f"top={[s.chunk.id for s in r.sources[:2]]}")
    print(f"\n{len(cases) - fails}/{len(cases)} passed | false answers on out-of-scope: {false_answers}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
