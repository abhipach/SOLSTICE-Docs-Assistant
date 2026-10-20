# Solution Design - Solstice Docs Assistant

## 1. Problem and success criteria
Admins repeatedly ask questions that *are* in the docs (password resets, export limits, billing) but are hard to find.
Elena's non-negotiable: **if the docs don't cover it, say so - never invent an answer.** I therefore optimise for
**precision and honest refusals**, not for always producing text. Success criteria (measured in `eval/run_eval.py`):
1. In-scope questions return the right passage with the required facts.
2. **Zero false answers on out-of-scope questions** (headline metric).
3. Ambiguous questions get a clarifying choice, not a guess.
4. Target sub-second latency without an LLM, low cost, explainable decisions.

## 2. Assumptions
| Open question | Decision | Reason |
|---|---|---|
| How to search | Section-level passages, BM25 + a coverage score | Small, structured, terminology-heavy docs: lexical search is strong, debuggable, free |
| How confident to be | Three bands (answer / related / decline) driven by *coverage* | One number a support lead can understand and tune |
| LLM or not | **Optional, off by default**, never the sole judge | See section 5 |
| What "not covered" means | A required, rare query term is absent from the best passage | Catches "export to **Salesforce**" even though "export" matches |
| Scale | Hundreds of passages, in-memory index | Swap-out path in section 7 |
| Plan-dependent facts | Return sibling passages (e.g. Growth *and* Enterprise limits) | Silently picking one plan would be a wrong answer |
| Access | One fixed demo login (`admin`/`123456`) | Local demo only; replace with SSO before any real use |

## 3. Architecture
```
question -> tokenise/stem/stop-words -> synonym groups -> BM25 + coverage retrieval
         -> decision layer (engine.py)
              coverage < 0.45 ............................. no_answer
              short query, >=2 articles within 10% ........ ambiguous (ask which)
              coverage < 0.75, or very short query whose
              terms miss the passage title/heading ........ related (shown, not asserted)
              otherwise ................................... answer + Doc ID source
                   -> [optional Gemini synthesis] -> verified output
         no_answer / related -> [optional Gemini rewrite] -> user confirms -> search again
         -> log (query, status, confidence, unmatched terms) -> Support insights tab
```
**Why coverage:** BM25 is relative - a "best" passage exists even for nonsense. Refusing needs an *absolute* signal.
Rare unseen words (Salesforce, residency) have maximal idf and count against confidence; numbers help ranking but are
not required. Unmatched terms are recorded in the query log and shown in retrieval details when enabled; they are not
always displayed to users. **Incidental-match guard:** a 2-word query such as "contact support" fully matched a closing
aside in the export article; very short queries whose terms never touch the passage's title/heading are therefore
downgraded to "related".

## 4. Passage granularity
One passage per `##` section (split above 140 words on paragraph boundaries); the provided JSON docs are one overview
section each. Title and heading are up-weighted. Sections are self-contained answers; smaller chunks lose context
(a limit without its plan), larger ones dilute scores. Answer sources display the document ID, title, and section
heading. The app loads `starter_kit/data`; `data/docs` is a separate synthetic Markdown corpus used only for
regression evaluation.

## 5. LLM: whether and how
**Default is extractive**: the answer is the docs' own text, so it cannot hallucinate, costs nothing and works offline.
When enabled, Gemini has two separate uses. If initial retrieval returns `no_answer` or `related`, the UI may ask Gemini
to suggest a clearer query and asks the user to confirm before searching again; the CLI/evaluation path can retry
automatically. After retrieval finds a confident answer, Gemini may synthesize it from the retrieved passages. The
synthesis must cite those passages; it can veto (`answerable=false` -> we decline); every number in its answer must
appear in a cited passage; API/parse failures fall back to the extractive answer. In either flow, retrieval coverage
remains the gate: the LLM cannot make unsupported documentation count as evidence. The default model is
`gemini-3.8-flash`, accessed through the Google GenAI SDK Interactions API. Query rewriting and synthesis can make two
separate API calls for a single confirmed question, so latency and rate limits are operational considerations.

## 6. Ambiguity handling
Query ambiguity (<=3 terms, strong matches in >=2 articles) shows options as buttons; plan-specific facts are returned
together; partial matches are labelled "related"; a small auditable synonym table bridges vocabulary (forgot->reset).

## 7. Evaluation, limitations, next steps
* `python eval/run_eval.py -v`: the 5 provided questions (5/5, zero false answers on Salesforce).
* `--docs starter_kit/data --questions eval/starter_extra.json`: 11 cases with required facts (e.g. "15 minutes") and
  extra out-of-scope probes. `--docs data/docs --questions eval/questions.json`: 16 regression cases. Both were written
  alongside the engine, so this is regression coverage, not unbiased accuracy; next step is hold-out questions from
  real tickets.
* Lexical matching misses paraphrases ("my login stopped working"); the cost is over-refusal. Next: hybrid with
  embeddings, keeping coverage as the veto. Synonyms are manual - mine them from the Support insights review queue.
* Thresholds (0.75/0.45, the short-query guard) are starting points, set in `Config` in `engine.py` (not UI sliders);
  re-tune on real traffic using declined questions and thumbs-down feedback.
* No negation understanding, single-turn only, answers are whole passages (highlighting the best sentence is next).
* The demo login is not a security boundary; the query log stores raw questions, so define access and retention first.
* Index is built at startup; re-index on doc publish. Beyond ~10^5 passages use FTS5/pgvector/Elasticsearch behind `Index.search`.
* The Docker image uses Python 3.11 slim, runs as a non-root user, serves on port 8501, and includes a health check.
  Compose can supply Gemini settings from the environment and persists query logs in a named volume. Keys must be
  injected at runtime, never included in the image. The included `admin` / `123456` login remains demo-only; the
  container is not production-ready for untrusted/public deployment without replacing authentication and adding access
  controls.

## 8. If challenged
* *Why not RAG?* Not fabricating is the top requirement; a gated extractive design makes it structural, the LLM is additive.
* *Why was my question refused?* Retrieval details (when enabled) and the query log show unmatched terms: add a synonym or doc content, or tune the threshold.
* *Contradicting docs?* Both passages are returned with sources, never silently merged.
