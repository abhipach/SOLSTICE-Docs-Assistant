"""Optional, evidence-grounded answer synthesis through Gemini."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from .retrieval import Hit

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
DEFAULT_TIMEOUT_SECONDS = 120
_GEMINI_CONFIG: dict[str, object] = {}

SYSTEM = """You answer questions from administrators of Solstice Learning, an online-course platform.

RULES
1. Use ONLY the numbered passages provided. Never use outside knowledge.
2. If the passages do not clearly answer the question, set "answerable" to false. Do not guess, infer
   missing numbers, or answer a nearby question instead.
3. If passages differ by plan or role (e.g. Standard vs Enterprise), say so explicitly.
4. Be concise: 1-4 sentences, plain language. Cite passage numbers like [1].
5. Respond with the requested JSON object only.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["answerable", "answer", "citations"],
    "additionalProperties": False,
}


def model_name() -> str:
    configured_model = _GEMINI_CONFIG.get("model", DEFAULT_GEMINI_MODEL)
    if not isinstance(configured_model, str):
        return DEFAULT_GEMINI_MODEL
    return configured_model.strip() or DEFAULT_GEMINI_MODEL


def timeout_seconds() -> int:
    configured_timeout = _GEMINI_CONFIG.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    return max(1, int(configured_timeout))


def configure(gemini_config: dict[str, object]) -> None:
    global _GEMINI_CONFIG
    _GEMINI_CONFIG = gemini_config


def gemini_api_key() -> str | None:
    value = _GEMINI_CONFIG.get("api_key")
    return value.strip() if value and value.strip() else None


def provider_name() -> str:
    return "gemini"


def has_gemini_api_key() -> bool:
    return gemini_api_key() is not None


def available() -> bool:
    """Whether Gemini is configured and its SDK is installed."""
    if not has_gemini_api_key():
        return False
    try:
        from google import genai  # noqa: F401
    except ImportError:
        return False
    return True


REWRITE_SYSTEM = """You rewrite short, messy or abbreviated user questions about the Solstice Learning
admin documentation into one clear, standard question so a keyword search can match the docs.

RULES
1. Expand abbreviations and slang (e.g. "pwd" -> "password", "2fa" -> "multi-factor authentication",
   "sso" stays "single sign-on") and fix typos. Use the documentation topics listed below to choose
   wording the docs would use.
2. Preserve the user's intent exactly. Do NOT answer the question and do NOT add facts.
3. Keep every specific product, vendor, plan, number or feature name the user mentioned (e.g.
   "Salesforce", "Growth plan"), even if it is not in the topic list. Never replace it with a
   documented topic.
4. If the question is unrelated to the topics below, return it unchanged.
5. Respond with the requested JSON object only.
"""

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
    "additionalProperties": False,
}

MAX_REWRITE_CHARS = 200


def rewrite_query(query: str, topics: list[str], model: str | None = None) -> str | None:
    """Rewrite a vague/abbreviated query in the docs' vocabulary.

    Returns the rewritten question, or None when the model fails, returns junk, or leaves the query
    unchanged - the caller then simply keeps the original query. Only retrieval input is changed;
    the grounding / veto checks downstream still decide whether an answer is shown.
    """
    if not gemini_api_key():
        return None
    selected_model = model or model_name()
    prompt = "Documentation topics:\n" + "\n".join(f"- {t}" for t in topics) + f"\n\nUser question: {query}"
    try:
        raw = asyncio.run(_request_answer(prompt, selected_model, REWRITE_SYSTEM, REWRITE_SCHEMA))
        data = json.loads(raw) if raw else None
    except Exception:
        logger.exception("Gemini query rewrite failed (model=%s); using the original query", selected_model)
        return None

    rewritten = data.get("question") if isinstance(data, dict) else None
    if not isinstance(rewritten, str):
        return None
    rewritten = " ".join(rewritten.split())
    if not rewritten or len(rewritten) > MAX_REWRITE_CHARS:
        return None
    if rewritten.lower().strip(" ?.!") == query.lower().strip(" ?.!"):
        return None
    return rewritten


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d[\d,\.]*", text))


async def _request_gemini_answer(
    prompt: str,
    model: str,
    system: str = SYSTEM,
    schema: dict | None = None,
) -> str | None:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=gemini_api_key(),
        http_options=types.HttpOptions(timeout=timeout_seconds() * 1000),
    )
    try:
        response = await client.aio.interactions.create(
            model=model,
            input=prompt,
            system_instruction=system,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": {
                    key: value
                    for key, value in (schema or RESPONSE_SCHEMA).items()
                    if key != "additionalProperties"
                },
            },
        )
        content = getattr(response, "output_text", None)
        return content if isinstance(content, str) else None
    finally:
        await client.aio.aclose()


async def _request_answer(
    prompt: str,
    model: str,
    system: str = SYSTEM,
    schema: dict | None = None,
) -> str | None:
    if not gemini_api_key():
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return await _request_gemini_answer(prompt, model, system, schema)


def synthesize(query: str, hits: list[Hit], model: str | None = None) -> dict | None:
    """Return a validated answer, an explicit model veto, or None to use extractive text."""
    passages = "\n\n".join(
        f"[{i}] ({hit.chunk.article} > {hit.chunk.heading})\n{hit.chunk.text}"
        for i, hit in enumerate(hits, 1)
    )
    prompt = f"Passages:\n{passages}\n\nQuestion: {query}"
    selected_model = model or model_name()
    selected_provider = provider_name()

    if not gemini_api_key():
        logger.warning("Gemini API key is not configured; using the extractive answer")
        return None

    try:
        raw = asyncio.run(_request_answer(prompt, selected_model))
        if raw is None:
            raise ValueError(f"{selected_provider} SDK returned no assistant message")
        data = json.loads(raw)
    except Exception:
        logger.exception(
            "%s answer synthesis failed (model=%s); using the extractive answer",
            selected_provider.capitalize(),
            selected_model,
        )
        return None

    if not isinstance(data, dict) or not isinstance(data.get("answerable"), bool):
        logger.warning("LLM returned an invalid answer object; using the extractive answer")
        return None
    if not data["answerable"]:
        return {"answerable": False}

    raw_citations = data.get("citations")
    if not isinstance(raw_citations, list):
        logger.warning("LLM answer omitted citations; using the extractive answer")
        return None
    citations = [
        citation
        for citation in raw_citations
        if type(citation) is int and 1 <= citation <= len(hits)
    ]
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip() or not citations:
        logger.warning("LLM answer failed content or citation checks; using the extractive answer")
        return None

    source_text = " ".join(hits[citation - 1].chunk.text for citation in citations) + " " + query
    answer_numbers = {
        number.rstrip(".,")
        for number in _numbers(re.sub(r"\[\d+\]", "", answer))
    }
    source_numbers = {number.rstrip(".,") for number in _numbers(source_text)}
    if not answer_numbers <= source_numbers:
        logger.warning("LLM answer included unsupported numbers; using the extractive answer")
        return None

    return {
        "answerable": True,
        "answer": answer.strip(),
        "citations": citations,
    }
