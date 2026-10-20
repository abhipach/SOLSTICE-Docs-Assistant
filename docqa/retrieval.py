"""BM25 retrieval + an independent, interpretable coverage score."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from .loader import Chunk
from .text import STOP, SYNONYMS, stem, tokenize

import re

_NUM = re.compile(r"^\d+$")
SYN_WEIGHT = 0.7


@dataclass
class Group:
    term: str
    alts: list[str]      # [term] + synonyms
    required: bool       # numbers help ranking but are not required for coverage


@dataclass
class Hit:
    chunk: Chunk
    bm25: float
    coverage: float      # 0..1 idf-weighted share of query terms found in the passage
    rank: float
    missing: list[str]
    topic_match: bool = True   # a query term (or synonym) appears in the article title/heading


class Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.tf = [Counter(c.tokens) for c in chunks]
        self.dl = [len(c.tokens) for c in chunks]
        self.avgdl = sum(self.dl) / len(self.dl)
        self.N = len(chunks)
        self.df: Counter = Counter()
        for tf in self.tf:
            self.df.update(tf.keys())

    def idf(self, term: str) -> float:
        """Unknown terms get the highest idf: a rare unseen word (e.g. 'Salesforce')
        should count *against* confidence, not be ignored."""
        df = self.df.get(term, 0)
        return math.log(1 + (self.N - df + 0.5) / (df + 0.5))

    def topics(self) -> list[str]:
        """Unique 'Article > Heading' labels, used to steer LLM query rewriting."""
        seen: dict[str, None] = {}
        for c in self.chunks:
            seen[f"{c.article} > {c.heading}"] = None
        return list(seen)

    # ---------------------------------------------------------------- query
    def groups(self, query: str) -> list[Group]:
        seen, groups = set(), []
        for raw in re.findall(r"[a-z0-9]+", query.lower()):
            if raw in STOP:
                continue
            t = stem(raw)
            if t in seen:
                continue
            seen.add(t)
            alts = [t] + [s for s in SYNONYMS.get(t, []) if s != t]
            groups.append(Group(t, alts, required=not _NUM.match(t)))
        return groups

    def _bm25_term(self, term: str, i: int) -> float:
        f = self.tf[i].get(term, 0)
        if not f:
            return 0.0
        denom = f + self.k1 * (1 - self.b + self.b * self.dl[i] / self.avgdl)
        return self.idf(term) * f * (self.k1 + 1) / denom

    def search(self, query: str, k: int = 5) -> tuple[list[Group], list[Hit]]:
        groups = self.groups(query)
        if not groups:
            return groups, []
        req = [g for g in groups if g.required]
        denom = sum(self.idf(g.term) for g in req) or 1.0

        raw = []
        for i, ch in enumerate(self.chunks):
            score = 0.0
            for g in groups:
                s = self._bm25_term(g.term, i)
                for alt in g.alts[1:]:
                    s = max(s, SYN_WEIGHT * self._bm25_term(alt, i))
                score += s
            covered_w, missing = 0.0, []
            for g in req:
                if any(self.tf[i].get(a, 0) for a in g.alts):
                    covered_w += self.idf(g.term)
                else:
                    missing.append(g.term)
            raw.append((score, covered_w / denom, missing, ch))

        top = max(r[0] for r in raw) or 1.0
        hits = [
            Hit(ch, s, cov, 0.4 * (s / top) + 0.6 * cov, miss,
                any(a in ch.head_tokens for g in groups for a in g.alts))
            for s, cov, miss, ch in raw
            if s > 0
        ]
        hits.sort(key=lambda h: h.rank, reverse=True)
        return groups, hits[:k]
