"""Load markdown articles and split them into section-level passages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .text import tokenize

MAX_WORDS = 140  # split overly long sections on paragraph boundaries


@dataclass
class Chunk:
    id: str
    article: str      # article title
    article_id: str   # file stem
    heading: str
    text: str
    tokens: list[str]


def _split_paragraphs(body: str) -> list[str]:
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    out, cur = [], []
    for p in paras:
        if cur and sum(len(x.split()) for x in cur) + len(p.split()) > MAX_WORDS:
            out.append("\n\n".join(cur))
            cur = []
        cur.append(p)
    if cur:
        out.append("\n\n".join(cur))
    return out


def load_chunks(doc_dir: str | Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(doc_dir).glob("*.md")):
        title, heading, buf = path.stem, "Overview", []
        sections: list[tuple[str, str]] = []

        def flush():
            body = "\n".join(buf).strip()
            if body:
                sections.append((heading, body))

        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                flush()
                heading, buf = line[3:].strip(), []
            else:
                buf.append(line)
        flush()

        n = 0
        for head, body in sections:
            for piece in _split_paragraphs(body):
                n += 1
                # heading and title are repeated so they get extra weight
                toks = tokenize(f"{title} {head} {head} {piece}")
                chunks.append(Chunk(f"{path.stem}#{n}", title, path.stem, head, piece, toks))
    if not chunks:
        raise FileNotFoundError(f"No .md articles found in {doc_dir}")
    return chunks
