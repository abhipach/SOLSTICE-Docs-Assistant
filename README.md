# Solstice Docs Assistant

Plain-English Q&A over the Solstice Learning documentation. Built in Python + Streamlit.
**Core principle (from Elena Torres, Head of Support): say "I don't have an answer for that" rather than make something up.**

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
Works fully offline with no API key. Optional LLM polishing: `export ANTHROPIC_API_KEY=...` and toggle it in the sidebar.

## Use the real case-study files
1. Delete the 6 sample articles in `data/docs/` and drop in the 6 provided `.md` files
   (format: `# Title`, then `## Section` headings; if they are `.txt`/`.html`, see "Adapting" below).
2. Replace `eval/questions.json` with the 5 provided questions plus a few out-of-scope ones.
3. `python eval/run_eval.py -v`, then tune the thresholds (sidebar, or `Config` in `docqa/engine.py`).

## Layout
```
app.py               Streamlit UI (Ask tab + "Doc gaps" tab for Support)
docqa/text.py        tokenizer, stemmer, stop-words, synonym table
docqa/loader.py      markdown -> section-level passages
docqa/retrieval.py   BM25 + idf-weighted query-coverage score
docqa/engine.py      decision layer: answer | related | ambiguous | no_answer
docqa/llm.py         optional grounded LLM synthesis with verification
eval/                golden questions + runner (exit code 1 on failure)
tests/               unit tests            python -m unittest discover -s tests
docs/DESIGN.md       design decisions, trade-offs, limits, how I'd respond to challenges
```

## Behaviour summary
| Status | When | What the admin sees |
|---|---|---|
| `answer` | best passage supports ≥75% of the question's (idf-weighted) terms | the passage text + source |
| `related` | 45-75% | "I can't confirm this answers it" + collapsible passages |
| `ambiguous` | short query matches several *different articles* about equally | "Which did you mean?" buttons |
| `no_answer` | <45%, or LLM vetoes | "I don't have an answer for that in the documentation." |

Every question is logged to `data/logs/queries.jsonl`; declined/unsure/👎 rows appear in the **Doc gaps** tab.

## Adapting
* Other formats: only `docqa/loader.py` needs changing - return `Chunk` objects.
* Domain words admins use that docs don't: add to `_RAW_SYNONYMS` in `docqa/text.py`.
* Tighter/looser: raise `answer_cov` to refuse more; lower to answer more.
