"""Run the golden question set. Exit code 1 on any failure (CI friendly).

    python eval/run_eval.py [--llm] [--questions eval/questions.json]
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
    ap.add_argument("--questions", default=str(ROOT / "eval" / "questions.json"))
    ap.add_argument("--docs", default=str(ROOT / "data" / "docs"))
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    bot = Assistant(a.docs, Config(use_llm=a.llm))
    cases = json.loads(Path(a.questions).read_text())
    fails, false_answers = 0, 0
    for c in cases:
        r = bot.ask(c["q"])
        ok = r.status == c["expect"]
        if ok and c["expect"] == "answer":
            ok = r.sources[0].chunk.article_id == c["article"] or any(
                s.chunk.article_id == c["article"] for s in r.sources)
            text = r.message + " " + " ".join(s.chunk.text for s in r.sources)
            ok = ok and all(m.lower() in text.lower() for m in c.get("must_contain", []))
        if c["expect"] in ("no_answer", "ambiguous") and r.status == "answer":
            false_answers += 1
        fails += (not ok)
        print(f"{'PASS' if ok else 'FAIL'}  [{r.status:<9} conf={r.confidence:.2f}] {c['q']}")
        if a.verbose or not ok:
            print(f"        expected={c['expect']} missing={r.missing_terms} "
                  f"top={[s.chunk.id for s in r.sources[:2]]}")
    print(f"\n{len(cases) - fails}/{len(cases)} passed | false answers on out-of-scope: {false_answers}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
