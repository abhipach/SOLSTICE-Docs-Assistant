"""Decision layer: answer / related / ambiguous / no_answer."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import llm
from .loader import load_chunks
from .retrieval import Hit, Index


@dataclass
class Config:
    answer_cov: float = 0.75     # >= : answer confidently
    related_cov: float = 0.45    # >= : show "related, not sure" ; < : decline
    ambiguity_margin: float = 0.10
    ambiguity_max_terms: int = 3
    topic_gate_max_terms: int = 2
    top_k: int = 3
    use_llm: bool = False


@dataclass
class Answer:
    status: str                  # answer | related | ambiguous | no_answer | empty
    message: str
    confidence: float = 0.0
    sources: list[Hit] = field(default_factory=list)
    options: list[Hit] = field(default_factory=list)   # for ambiguous
    mode: str = "extractive"     # extractive | llm
    missing_terms: list[str] = field(default_factory=list)
    rewritten_query: str | None = None   # set when the LLM reworded the question to match the docs
    baseline_status: str | None = None   # status the plain (no-LLM) search gave for the original text


NO_ANSWER = "I don't have an answer for that in the documentation."


class Assistant:
    def __init__(self, doc_dir: str | Path, config: Config | None = None):
        self.cfg = config or Config()
        self.index = Index(load_chunks(doc_dir))

    def _llm_on(self, use_llm: bool | None) -> bool:
        return bool((self.cfg.use_llm if use_llm is None else use_llm) and llm.available())

    def suggest_rewrite(self, query: str, *, use_llm: bool | None = None) -> str | None:
        """LLM's cleaner version of the question ("reset pwd" -> "How do I reset my password?"),
        or None when the LLM is off/unavailable or the question needs no change. Used for the
        "Did you mean ...?" confirmation step."""
        if not self._llm_on(use_llm):
            return None
        return llm.rewrite_query(query, self.index.topics())

    def ask(
        self,
        query: str,
        *,
        use_llm: bool | None = None,
        rewritten: str | None = None,
        auto_rewrite: bool = True,
    ) -> Answer:
        """Answer a question.

        Without an LLM the query is matched as typed, so "reset pwd" is honestly declined.
        With an LLM enabled the question can be reworded into the docs' vocabulary:
          * rewritten=...   the user confirmed a suggestion; search with it (see suggest_rewrite).
          * auto_rewrite    no confirmation UI (CLI/eval): if the first try fails, rewrite and retry.
        Either way the reworded query goes through the same coverage gates, so rewriting can only help
        retrieval, never force an answer. The result records `baseline_status` - what the plain,
        no-LLM search would have said - so the benefit of the LLM is visible.
        """
        llm_on = self._llm_on(use_llm)
        if rewritten and llm_on:
            ans = self._decide(rewritten, llm_on, original_query=query)
            ans.rewritten_query = rewritten
            ans.baseline_status = self._decide(query, False).status
            return ans

        first = self._decide(query, llm_on)
        if not llm_on or not auto_rewrite or first.status not in ("no_answer", "related"):
            return first

        rewritten = self.suggest_rewrite(query, use_llm=use_llm)
        if not rewritten:
            return first
        second = self._decide(rewritten, llm_on, original_query=query)
        # Keep the retry only if it is a real improvement; otherwise the original verdict stands.
        if second.status in ("answer", "ambiguous") or (
            second.status == "related" and first.status == "no_answer"
        ):
            second.rewritten_query = rewritten
            second.baseline_status = first.status
            return second
        return first

    def _decide(self, query: str, llm_on: bool, original_query: str | None = None) -> Answer:
        cfg = self.cfg
        groups, hits = self.index.search(query, k=8)
        if not groups:
            return Answer("empty", "Type a question about your Solstice account, e.g. “How do I export a report?”")
        if not hits:
            return Answer("no_answer", NO_ANSWER, 0.0, missing_terms=[g.term for g in groups])

        top = hits[0]
        conf = top.coverage
        # Terms the best passage does not support - shown to the user so refusals are explainable.
        missing = top.missing

        if conf < cfg.related_cov:
            return Answer("no_answer", NO_ANSWER, conf, missing_terms=missing)

        # --- ambiguity: short query matching passages in different articles with similar strength
        if conf >= cfg.related_cov and len(groups) <= cfg.ambiguity_max_terms:
            rivals = [
                h for h in hits[1:]
                if h.chunk.article_id != top.chunk.article_id
                and h.coverage >= cfg.related_cov
                and h.rank >= top.rank * (1 - cfg.ambiguity_margin)
            ]
            if rivals:
                opts, seen = [], set()
                for h in [top] + rivals:
                    if h.chunk.article_id not in seen:
                        seen.add(h.chunk.article_id)
                        opts.append(h)
                return Answer(
                    "ambiguous",
                    "Your question could refer to more than one topic. Which did you mean?",
                    conf, options=opts[:4],
                )

        # --- related: partial support, never present as a definitive answer.
        # Also applies to very short queries (<= topic_gate_max_terms content terms) where no term
        # touches the passage's title/heading: the match is then likely incidental (e.g. "contact
        # support" matching an export article's closing sentence). Heuristic; tune on real traffic.
        incidental = not top.topic_match and len(groups) <= cfg.topic_gate_max_terms
        if conf < cfg.answer_cov or incidental:
            return Answer(
                "related",
                "I couldn't find a direct answer, but these sections may be relevant. "
                "I can't confirm they answer your question.",
                conf, sources=hits[: cfg.top_k], missing_terms=missing,
            )

        # --- confident answer
        # Sources = top passage + any near-equal ones (e.g. self-service AND admin reset paths)
        sources = [top] + [
            h for h in hits[1:]
            if h.coverage >= cfg.answer_cov and h.rank >= 0.8 * top.rank
        ][: cfg.top_k - 1]

        if llm_on:
            res = llm.synthesize(original_query or query, sources)
            if res is not None:
                if not res.get("answerable"):
                    # LLM is a second, independent veto on the retrieval gate.
                    return Answer("no_answer", NO_ANSWER, conf, missing_terms=missing)
                cited = [sources[c - 1] for c in res["citations"]]
                return Answer("answer", res["answer"], conf, cited, mode="llm")

        body = "\n\n".join(s.chunk.text for s in sources)
        return Answer("answer", body, conf, sources)


def log_event(path: str | Path, query: str, ans: Answer, feedback: str | None = None) -> None:
    """Append-only JSONL. 'no_answer'/'related' rows are the doc-gap backlog for Support."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "query": query,
        "status": ans.status,
        "confidence": round(ans.confidence, 3),
        "top_source": ans.sources[0].chunk.id if ans.sources else None,
        "missing_terms": ans.missing_terms,
        "rewritten_query": ans.rewritten_query,
        "baseline_status": ans.baseline_status,
        "feedback": feedback,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
