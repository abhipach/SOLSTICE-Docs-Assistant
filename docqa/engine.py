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


NO_ANSWER = "I don't have an answer for that in the documentation."


class Assistant:
    def __init__(self, doc_dir: str | Path, config: Config | None = None):
        self.cfg = config or Config()
        self.index = Index(load_chunks(doc_dir))

    def ask(self, query: str) -> Answer:
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

        # --- related: partial support, never present as a definitive answer
        if conf < cfg.answer_cov:
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

        if cfg.use_llm and llm.available():
            res = llm.synthesize(query, sources)
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
        "feedback": feedback,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
