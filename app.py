"""Solstice Learning - Docs Assistant (Streamlit).   Run:  streamlit run app.py"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from docqa import llm
from docqa.engine import Answer, Assistant, Config, log_event

ROOT = Path(__file__).parent
DOCS = ROOT / "data" / "docs"
LOG = ROOT / "data" / "logs" / "queries.jsonl"

st.set_page_config(page_title="Solstice Docs Assistant", page_icon="📘", layout="centered")


@st.cache_resource
def get_bot() -> Assistant:
    return Assistant(DOCS)


bot = get_bot()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Settings")
    llm_ok = llm.available()
    use_llm = st.toggle(
        "Polish answers with an LLM", value=False, disabled=not llm_ok,
        help="Needs ANTHROPIC_API_KEY. The LLM only sees retrieved passages, can veto an "
             "answer, and its numbers are verified against the source.",
    )
    if not llm_ok:
        st.caption("LLM off: running fully offline (retrieval only).")
    st.subheader("Confidence gates")
    bot.cfg.answer_cov = st.slider("Answer above", 0.5, 1.0, bot.cfg.answer_cov, 0.05)
    bot.cfg.related_cov = st.slider("Decline below", 0.1, 0.8, bot.cfg.related_cov, 0.05)
    bot.cfg.use_llm = use_llm
    debug = st.checkbox("Show retrieval details", value=False)
    st.caption(f"{len(bot.index.chunks)} passages indexed from {len(list(DOCS.glob('*.md')))} articles")

tab_ask, tab_gaps = st.tabs(["Ask", "Doc gaps (for Support)"])

# ------------------------------------------------------------------ helpers
def render_sources(ans: Answer) -> None:
    for i, h in enumerate(ans.sources, 1):
        st.caption(f"[{i}] 📄 {h.chunk.article} › {h.chunk.heading}")


def render(ans: Answer, key: str) -> None:
    if ans.status == "answer":
        st.success("Answer from the documentation")
        st.markdown(ans.message)
        render_sources(ans)
    elif ans.status == "related":
        st.warning(ans.message)
        for h in ans.sources:
            with st.expander(f"{h.chunk.article} › {h.chunk.heading}"):
                st.markdown(h.chunk.text)
    elif ans.status == "ambiguous":
        st.info(ans.message)
        for h in ans.options:
            if st.button(f"{h.chunk.article}: {h.chunk.heading}", key=f"{key}-{h.chunk.id}"):
                st.session_state.pending = f"{h.chunk.heading}"
                st.rerun()
    elif ans.status == "no_answer":
        st.error(ans.message)
        st.caption("This question has been logged so Support can consider adding it to the docs.")
    else:
        st.write(ans.message)

    if debug and ans.status != "empty":
        st.json({"status": ans.status, "confidence": round(ans.confidence, 2),
                 "mode": ans.mode, "missing_terms": ans.missing_terms,
                 "top": [(s.chunk.id, round(s.rank, 2), round(s.coverage, 2)) for s in ans.sources]})

    if ans.status in ("answer", "related"):
        c1, c2, _ = st.columns([1, 1, 6])
        if c1.button("👍", key=f"up-{key}"):
            log_event(LOG, st.session_state.history[int(key)]["q"], ans, "up")
            st.toast("Thanks!")
        if c2.button("👎", key=f"dn-{key}"):
            log_event(LOG, st.session_state.history[int(key)]["q"], ans, "down")
            st.toast("Thanks - flagged for review.")


# ------------------------------------------------------------------ ask tab
with tab_ask:
    st.title("📘 Solstice Docs Assistant")
    st.caption("Ask a question in plain English. Answers come only from the Solstice documentation; "
               "if it isn't covered, I'll say so.")

    st.session_state.setdefault("history", [])
    for i, turn in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.write(turn["q"])
        with st.chat_message("assistant"):
            render(turn["a"], str(i))

    q = st.chat_input("e.g. How do I reset a user's password?") or st.session_state.pop("pending", None)
    if q:
        ans = bot.ask(q)
        log_event(LOG, q, ans)
        st.session_state.history.append({"q": q, "a": ans})
        st.rerun()

    with st.expander("Try an example"):
        for ex in ["How do I reset my password?", "What's the export row limit?",
                   "When am I invoiced?", "Does Solstice integrate with Salesforce?"]:
            if st.button(ex, key=f"ex-{ex}"):
                st.session_state.pending = ex
                st.rerun()

# ------------------------------------------------------------------ gaps tab
with tab_gaps:
    st.subheader("Questions the docs couldn't answer")
    st.caption("Turns declined questions into a content backlog for the Support team.")
    if LOG.exists():
        rows = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
        gaps = [r for r in rows if r["status"] in ("no_answer", "related")]
        down = [r for r in rows if r.get("feedback") == "down"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Questions", len([r for r in rows if r["feedback"] is None]))
        c2.metric("Declined / unsure", len(gaps))
        c3.metric("👎 feedback", len(down))
        if gaps or down:
            st.dataframe(
                [{"time": r["ts"], "question": r["query"], "status": r["status"],
                  "confidence": r["confidence"], "unmatched terms": ", ".join(r["missing_terms"])}
                 for r in gaps + down],
                use_container_width=True,
            )
    else:
        st.info("No questions logged yet.")
