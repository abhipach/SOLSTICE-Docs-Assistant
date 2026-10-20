"""Load JSON or Markdown articles and split them into searchable passages."""
from __future__ import annotations

import json
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
    head_tokens: frozenset = frozenset()   # stems of article title + section heading


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


def _chunks_for_article(
    article: str, article_id: str, sections: list[tuple[str, str]]
) -> list[Chunk]:
    chunks: list[Chunk] = []
    n = 0
    for heading, body in sections:
        for piece in _split_paragraphs(body):
            n += 1
            toks = tokenize(f"{article} {heading} {heading} {piece}")
            chunks.append(
                Chunk(f"{article_id}#{n}", article, article_id, heading, piece, toks,
                      frozenset(tokenize(f"{article} {heading}")))
            )
    return chunks


def _load_json(path: Path) -> list[Chunk]:
    data = json.loads(path.read_text(encoding="utf-8"))
    docs = data.get("docs") if isinstance(data, dict) else None
    if not isinstance(docs, list):
        raise ValueError(f"Expected a 'docs' list in {path}")

    chunks: list[Chunk] = []
    for i, doc in enumerate(docs, 1):
        if not isinstance(doc, dict):
            raise ValueError(f"Document {i} in {path} must be an object")
        doc_id, title, content = doc.get("doc_id"), doc.get("title"), doc.get("content")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (doc_id, title, content)
        ):
            raise ValueError(f"Document {i} in {path} needs non-empty doc_id, title, and content")
        chunks.extend(_chunks_for_article(title, doc_id, [("Overview", content)]))
    if not chunks:
        raise ValueError(f"No documents found in {path}")
    return chunks


def load_chunks(doc_dir: str | Path) -> list[Chunk]:
    doc_path = Path(doc_dir)
    if doc_path.is_file():
        if doc_path.suffix.lower() == ".json":
            return _load_json(doc_path)
        raise ValueError(f"Unsupported documentation file: {doc_path}")

    json_path = doc_path / "docs.json"
    markdown_paths = list(doc_path.glob("*.md"))
    if json_path.exists() and markdown_paths:
        raise ValueError(f"Use either docs.json or Markdown articles in {doc_path}, not both")
    if json_path.exists():
        return _load_json(json_path)

    chunks: list[Chunk] = []
    for path in sorted(markdown_paths):
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

        chunks.extend(_chunks_for_article(title, path.stem, sections))
    if not chunks:
        raise FileNotFoundError(f"No .md articles found in {doc_dir}")
    return chunks
