# Design Document - Solstice Docs Assistant

## 1. Problem and success criteria
Admins ask a small set of repeat questions (password resets, export limits, billing cycles) that *are*
in the docs but hard to find. The customer's one non-negotiable: **if the docs don't cover it, say so -
never invent an answer.** So the system is optimised for **precision of answers and honesty of refusals**,
not for always producing text.

Success criteria I chose (and how they are measured in `eval/run_eval.py`):
1. In-scope questions return the right passage (retrieval accuracy + required facts present).
2. **Zero false answers on out-of-scope questions** (headline metric).
3. Ambiguous questions get a clarifying choice, not a guess.
4. Latency well under a second without an LLM; low cost; explainable decisions.

## 2. Ambiguities in the brief and how I resolved them
| Ambiguity | Decision | Reason |
|---|---|---|
| "How to search across documents" - not specified | Section-level passages, BM25, plus a coverage score | Docs are tiny, structured, terminology-heavy; lexical search is strong, debuggable and free |
| "How confident an answer must be" - not specified | Three bands (answer / related / decline) driven by *coverage* | A single number a support lead can understand and tune |
| "Whether to use an LLM at all" | **Optional, off by default**, never the sole judge | See §5 |
| What counts as "doesn't cover"? | A required, rare term of the question absent from the best passage | Catches "export to **Salesforce**" even though "export" matches strongly |
| Corpus size/scale | Assume hundreds, not millions of passages | In-memory index; swap-out path in §8 |
| Plan-dependent facts | Return all sibling passages (Standard *and* Enterprise limits) | Picking one plan silently would be a wrong answer |

## 3. Architecture
```
question → tokenise/stem/stop-words → synonym groups
        → BM25 over section passages  ┐
        → coverage = Σidf(covered terms) / Σidf(all terms)  ┘ rank = 0.4·bm25_norm + 0.6·coverage
        → decision layer (engine.py)
             coverage < 0.45 ............ no_answer
             short query, ≥2 articles ... ambiguous (ask which)
             coverage < 0.75 ............ related (show, don't assert)
             else ....................... answer  → [optional LLM] → verified output
        → log (query, status, confidence, unmatched terms) → Doc-gaps tab
```

### Why *coverage* is the key idea
BM25 scores are relative: the "best" passage always exists, even for nonsense. Refusing requires an
**absolute** signal. Coverage asks "what fraction of what the user asked for (weighted by how
informative each word is) appears in this passage?" Properties:
* Unknown/rare words (Salesforce, residency) have maximal idf and are *unmatched* → strong refusal signal.
* Numbers help ranking but are not required, so "export 200,000 rows" still finds the 100,000-row limit.
* Explainable: the UI/logs list the **unmatched terms** behind every refusal.

## 4. Passage granularity
One passage per `##` section (split on paragraphs above 140 words); title and heading are indexed and
up-weighted. Sections are self-contained "answers" in help docs; smaller chunks lose context (a limit
without its plan), larger ones dilute scores.

## 5. LLM: whether and how
**Default (no LLM): extractive.** The answer is the doc's own text → cannot hallucinate, costs nothing, is
fast, and works offline. Trade-off: less conversational, may include a sentence or two more than needed.

**Optional LLM layer** (`docqa/llm.py`) only improves *wording*, with these guards:
1. Runs only after the retrieval gate already said "answer".
2. Prompt: use only numbered passages; JSON output with `answerable` and citations.
3. **Veto power:** if the model says not answerable → we decline (two independent gates).
4. **Number grounding check:** every number in the answer must appear in a cited passage, otherwise
   we discard it and show the extractive answer. Invented limits/prices are the most harmful error.
5. Any API/parse failure → silent fall back to extractive. The product never depends on the LLM.
6. temperature 0, citations required, passages are the only context (no chat memory).

I deliberately did **not** let the LLM decide *whether* the docs cover the question from the whole
corpus: LLMs are the component most prone to the failure the customer fears.

## 6. Handling ambiguity
* **Query ambiguity**: ≤3 content terms and strong matches in ≥2 different articles within 10% rank →
  show options as buttons (e.g. "When does it expire?" → invitation links / export links / SCIM token).
* **Content ambiguity**: plan-specific facts are returned together.
* **Partial match**: "related" band shows candidates but explicitly does not claim an answer.
* **Vocabulary mismatch**: small, auditable synonym table (forgot→reset, bill→invoice, max→limit).

## 7. Evaluation
`eval/questions.json` (16 cases: 10 answerable, 5 out-of-scope, 1 ambiguous). Run `python eval/run_eval.py -v`.
Reports pass/fail and **false answers on out-of-scope questions**. Current result: 16/16, 0 false answers
on the sample corpus. Caveat: the questions were written alongside the engine, so this is a regression
suite, not an unbiased accuracy estimate. Next step: hold-out questions from real support tickets.

Errors I found while building and fixed (kept as regression tests): stemmer mismatch `invoice`/`invoiced`;
filler words ("new", "one", "what's") lowering coverage and wrongly refusing; "max size" not matching
"up to 2 GB" (synonym).

## 8. Limitations and what I'd do with more time
* **Lexical matching misses paraphrases** with no word overlap ("my login stopped working"). Fix: add
  embedding retrieval (hybrid), keep coverage as the veto. Not done because it adds a model dependency
  and the customer's priority is precision over recall; the cost is occasional *over-refusal*.
* Synonyms are manual; mine them from the Doc-gaps log.
* Over-refusal vs. under-refusal is a dial: raise `answer_cov` for safer, lower for more helpful. Tune on
  real traffic by looking at 👎 feedback and declined questions.
* No negation understanding ("can't set password" vs "set password").
* Single-turn only (no follow-up context); in-memory index (fine for <10⁵ passages; beyond that use
  SQLite FTS5/pgvector/Elasticsearch behind the same `Index.search` interface).
* No auth/PII handling: the query log stores raw questions - add retention policy before production.
* Docs staleness: index rebuilt at startup; a webhook/CI step should re-index on doc publish.

## 9. Responding when challenged
* *"Why not just use an LLM/RAG with embeddings?"* - Customer's top requirement is not fabricating. An
  extractive, gated design makes that property structural; the LLM is additive and verifiable. Embeddings
  are the planned recall upgrade; I'd justify it with measured misses.
* *"Why does it refuse a question I think is answerable?"* - The UI/log shows unmatched terms; either add
  a synonym/doc content or lower the threshold. That's the intended feedback loop.
* *"Is 0.75/0.45 principled?"* - They're starting points chosen to give zero false answers on my eval with
  margin; they should be re-tuned on real questions. Exposed as sliders for that reason.
* *"What if the docs contradict each other?"* - Both passages are returned with their sources (never
  silently merged); flag for content owners via the Doc-gaps process.
