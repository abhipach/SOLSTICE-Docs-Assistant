"""Optional LLM synthesis. Always grounded, always verified, always skippable."""
from __future__ import annotations

import json
import os
import re

from .retrieval import Hit

SYSTEM = """You answer questions from administrators of Solstice Learning, an online-course platform.

RULES
1. Use ONLY the numbered passages provided. Never use outside knowledge.
2. If the passages do not clearly answer the question, set "answerable" to false. Do not guess, infer
   missing numbers, or answer a nearby question instead.
3. If passages differ by plan or role (e.g. Standard vs Enterprise), say so explicitly.
4. Be concise: 1-4 sentences, plain language. Cite passage numbers like [1].
5. Respond with JSON only: {"answerable": true|false, "answer": "...", "citations": [1, 2]}
"""


def available() -> bool:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,\.]*", text))


def synthesize(query: str, hits: list[Hit], model: str | None = None) -> dict | None:
    """Return {'answer', 'citations'} if the LLM answered AND passed grounding checks,
    {'answerable': False} if it declined, or None on any failure (caller falls back)."""
    try:
        import anthropic

        client = anthropic.Anthropic()
        passages = "\n\n".join(
            f"[{i}] ({h.chunk.article} > {h.chunk.heading})\n{h.chunk.text}"
            for i, h in enumerate(hits, 1)
        )
        msg = client.messages.create(
            model=model or os.getenv("DOCQA_MODEL", "claude-sonnet-4-5"),
            max_tokens=500,
            temperature=0,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Passages:\n{passages}\n\nQuestion: {query}"}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except Exception:
        return None

    if not data.get("answerable"):
        return {"answerable": False}

    cites = [c for c in data.get("citations", []) if isinstance(c, int) and 1 <= c <= len(hits)]
    answer = str(data.get("answer", "")).strip()
    if not cites or not answer:
        return {"answerable": False}

    # Grounding check: every number in the answer must appear in a cited passage
    # (or in the question). Catches the most damaging hallucination: invented limits.
    source_text = " ".join(hits[c - 1].chunk.text for c in cites) + " " + query
    cleaned = {n.rstrip(".,") for n in _numbers(re.sub(r"\[\d+\]", "", answer))}
    if not cleaned <= {n.rstrip(".,") for n in _numbers(source_text)}:
        return None  # fall back to extractive answer
    return {"answerable": True, "answer": answer, "citations": cites}
