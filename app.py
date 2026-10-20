"""Solstice Learning docs assistant. Run with: streamlit run app.py"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from docqa import llm
from docqa.auth import (
    DEMO_USERS,
    DUMMY_PASSWORD_HASH,
    AuthConfigurationError,
    verify_password,
)
from docqa.engine import Answer, Assistant, log_event
from docqa.insights import (
    daily_volume,
    filter_events,
    read_events,
    summarize,
    top_review_questions,
    top_sources,
    unanswered_csv,
)

ROOT = Path(__file__).parent
DOCS = ROOT / "starter_kit" / "data"
LOG = ROOT / "data" / "logs" / "queries.jsonl"

st.set_page_config(page_title="Solstice Docs Assistant", page_icon="📘", layout="wide")
st.markdown(
    """
    <style>
      .block-container {max-width: 1120px; padding-top: 2rem; padding-bottom: 3rem;}
      [data-testid="stSidebar"] {border-right: 1px solid #e7edf2;}
      div.stButton > button {border-radius: 8px; min-height: 2.5rem;}
      div[data-testid="stForm"] {border: 1px solid #dce5eb; border-radius: 12px; padding: 1rem;}
      div[data-testid="stChatMessage"] {border: 1px solid #e7edf2; border-radius: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def configured_users() -> dict[str, str]:
    try:
        configured_secrets = st.secrets.to_dict()
    except StreamlitSecretNotFoundError:
        configured_secrets = {}
    gemini_config = configured_secrets.get("gemini", {})
    if not isinstance(gemini_config, dict):
        raise AuthConfigurationError("The [gemini] Streamlit secrets section must be a table")
    gemini_config = dict(gemini_config)
    environment_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if environment_api_key:
        gemini_config["api_key"] = environment_api_key
    environment_model = os.environ.get("GEMINI_MODEL", "").strip()
    if environment_model:
        gemini_config["model"] = environment_model
    environment_timeout = os.environ.get("GEMINI_TIMEOUT_SECONDS", "").strip()
    if environment_timeout:
        try:
            gemini_config["timeout_seconds"] = int(environment_timeout)
        except ValueError as exc:
            raise AuthConfigurationError(
                "GEMINI_TIMEOUT_SECONDS must be a positive integer"
            ) from exc
    gemini_api_key = gemini_config.get("api_key")
    if gemini_api_key is not None:
        if not isinstance(gemini_api_key, str):
            raise AuthConfigurationError("[gemini].api_key must be a string")
    gemini_model = gemini_config.get("model")
    if gemini_model is not None:
        if not isinstance(gemini_model, str):
            raise AuthConfigurationError("[gemini].model must be a string")
    gemini_timeout = gemini_config.get("timeout_seconds")
    if gemini_timeout is not None and (type(gemini_timeout) is not int or gemini_timeout < 1):
        raise AuthConfigurationError("[gemini].timeout_seconds must be a positive integer")
    llm.configure(gemini_config)
    return dict(DEMO_USERS)


def show_login(users: dict[str, str]) -> None:
    left, center, right = st.columns([1, 1.2, 1])
    with center:
        st.write("")
        st.write("")
        st.markdown("### 📘 Solstice Learning")
        st.title("Docs Assistant")
        st.caption("Demo login: username admin, password 123456.")
        with st.form("login_form", clear_on_submit=True):
            username = st.text_input(
                "Username or email", autocomplete="username", key="login_username"
            )
            password = st.text_input(
                "Password", type="password", autocomplete="current-password", key="login_password"
            )
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if st.session_state.pop("login_failed", False):
            st.error("Sign-in failed. Check your credentials or contact your administrator.")
        if submitted:
            normalized = username.strip().casefold()
            encoded = users.get(normalized)
            password_matches = verify_password(password, encoded or DUMMY_PASSWORD_HASH)
            if encoded and password_matches:
                st.session_state.authenticated_user = normalized
                st.session_state.history = []
                st.rerun()
            st.session_state.login_failed = True
            st.rerun()
        st.caption("Access is limited to accounts configured by the application owner.")


try:
    users = configured_users()
except AuthConfigurationError as exc:
    st.error(f"Login configuration error: {exc}")
    st.stop()

if st.session_state.get("authenticated_user") not in users:
    show_login(users)
    st.stop()


@st.cache_resource
def get_bot() -> Assistant:
    return Assistant(DOCS)


bot = get_bot()
st.session_state.setdefault("history", [])
st.session_state.setdefault("use_llm", False)
st.session_state.setdefault("confirm", None)   # {"q": original, "s": LLM suggestion} awaiting Yes/No

with st.sidebar:
    st.markdown("### 📘 Solstice")
    st.caption("Documentation Assistant")
    st.divider()
    st.caption("Signed in as")
    st.write(st.session_state.authenticated_user)
    if st.button("Log out", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    with st.expander("Advanced settings"):
        llm_ok = llm.available()
        st.toggle(
            "Polish answers with an LLM",
            key="use_llm",
            disabled=not llm_ok,
            help=(
                "Optional. Gemini restates your question in the docs' wording (you confirm it first) "
                "and writes the answer from the retrieved passages."
            ),
        )
        if not llm.has_gemini_api_key():
            st.caption("Gemini API key missing. Configure [gemini].api_key in .streamlit/secrets.toml.")
        elif not llm.available():
            st.caption("Gemini SDK unavailable; run python -m pip install -r requirements.txt.")
        else:
            st.caption(f"Gemini API key configured · model: {llm.model_name()}")
        debug = st.checkbox("Show retrieval details", value=False)
        article_count = len({chunk.article_id for chunk in bot.index.chunks})
        st.caption(f"{article_count} documentation articles indexed")

tab_ask, tab_support = st.tabs(["Ask the docs", "Support insights"])


def render_sources(ans: Answer) -> None:
    for i, hit in enumerate(ans.sources, 1):
        st.caption(
            f"Source {i}: Doc ID {hit.chunk.article_id} · "
            f"{hit.chunk.article} · {hit.chunk.heading}"
        )


def render_answer(ans: Answer, key: str, question: str) -> None:
    if ans.rewritten_query:
        st.caption(f"Interpreted as: “{ans.rewritten_query}”")
        if ans.baseline_status in ("no_answer", "related") and ans.status in ("answer", "ambiguous"):
            st.success(
                "✨ LLM impact: searching your exact words gave "
                f"“{'no answer' if ans.baseline_status == 'no_answer' else 'only loosely related sections'}”. "
                "The reworded question found this answer."
            )
    if ans.status == "answer":
        if st.session_state.use_llm and ans.mode == "extractive":
            st.info("Gemini could not polish this response, so the answer is shown directly from the documentation.")
        st.success("Answer from the documentation")
        st.markdown(ans.message)
        render_sources(ans)
    elif ans.status == "related":
        st.warning(ans.message)
        for hit in ans.sources:
            with st.expander(
                f"Doc ID {hit.chunk.article_id} · {hit.chunk.article} · {hit.chunk.heading}"
            ):
                st.markdown(hit.chunk.text)
    elif ans.status == "ambiguous":
        st.info(ans.message)
        for hit in ans.options:
            if st.button(
                f"Doc ID {hit.chunk.article_id} · {hit.chunk.article}: {hit.chunk.heading}",
                key=f"{key}-{hit.chunk.id}",
            ):
                st.session_state.pending = hit.chunk.heading
                st.rerun()
    elif ans.status == "no_answer":
        st.warning(ans.message)
        st.caption("Try rephrasing, or contact Support. This question was added to the Support review log.")
    else:
        st.info(ans.message)

    if debug and ans.status != "empty":
        st.json(
            {
                "status": ans.status,
                "confidence": round(ans.confidence, 2),
                "mode": ans.mode,
                "missing_terms": ans.missing_terms,
                "top": [
                    (hit.chunk.id, round(hit.rank, 2), round(hit.coverage, 2))
                    for hit in ans.sources
                ],
            }
        )

    if ans.status in ("answer", "related"):
        left, right, _ = st.columns([1, 1, 8])
        if left.button("👍 Helpful", key=f"up-{key}"):
            log_event(LOG, question, ans, "up")
            st.toast("Thanks for the feedback.")
        if right.button("👎 Not helpful", key=f"down-{key}"):
            log_event(LOG, question, ans, "down")
            st.toast("Thanks — Support can review this answer.")


def ask_question(question: str, rewritten: str | None = None, confirm: bool = True) -> None:
    """Answer now, or - with the LLM on - first offer a cleaner version of the question."""
    st.session_state.confirm = None
    if confirm and rewritten is None and st.session_state.use_llm:
        with st.spinner("Checking how to best phrase your question…"):
            suggestion = bot.suggest_rewrite(question, use_llm=True)
        if suggestion:
            st.session_state.confirm = {"q": question, "s": suggestion}
            return
    with st.spinner("Finding an answer in the documentation…"):
        answer = bot.ask(question, use_llm=st.session_state.use_llm, rewritten=rewritten)
    log_event(LOG, question, answer)
    st.session_state.history.append({"q": question, "a": answer})


def render_confirm() -> None:
    pending = st.session_state.confirm
    with st.chat_message("user"):
        st.write(pending["q"])
    with st.chat_message("assistant"):
        st.markdown(f"Did you mean: **{pending['s']}**")
        yes, no, _ = st.columns([1, 1.4, 6])
        if yes.button("✅ Yes", key="confirm-yes", type="primary"):
            ask_question(pending["q"], rewritten=pending["s"])
            st.rerun()
        if no.button("No, use my wording", key="confirm-no"):
            ask_question(pending["q"], confirm=False)
            st.rerun()


with tab_ask:
    chosen = st.session_state.pop("pending", None)
    if chosen:
        ask_question(chosen, confirm=False)
    st.title("Find an answer in the Solstice docs")
    st.caption(
        "Ask in your own words. Answers are grounded in documentation; if the docs do not cover it, "
        "we’ll say so."
    )

    with st.form("question_form", clear_on_submit=True):
        question = st.text_input(
            "What would you like to know?",
            placeholder="For example: How long is a password reset link valid?",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Find answer", type="primary")
    if submitted and question.strip():
        ask_question(question.strip())
        st.rerun()
    elif submitted:
        st.info("Enter a question to get started.")

    st.markdown("**Try a common question**")
    examples = [
        "How do I reset my password?",
        "What are the API rate limits for Growth?",
        "What is the export row limit?",
        "Does Solstice integrate with Salesforce?",
    ]
    for row_start in (0, 2):
        columns = st.columns(2)
        for offset, example in enumerate(examples[row_start : row_start + 2]):
            if columns[offset].button(example, key=f"example-{row_start}-{offset}"):
                ask_question(example)
                st.rerun()

    history = st.session_state.history
    if st.session_state.confirm:
        render_confirm()
    elif history:
        current = history[-1]
        with st.chat_message("user"):
            st.write(current["q"])
        with st.chat_message("assistant"):
            render_answer(current["a"], str(len(history) - 1), current["q"])

        if len(history) > 1:
            with st.expander(f"Previous questions ({len(history) - 1})"):
                for index, turn in enumerate(history[:-1]):
                    with st.chat_message("user"):
                        st.write(turn["q"])
                    with st.chat_message("assistant"):
                        render_answer(turn["a"], str(index), turn["q"])

with tab_support:
    st.title("Support insights")
    st.caption("Monitor question demand, documentation coverage, user feedback, and recurring content gaps.")

    events, log_errors = read_events(LOG)
    if log_errors:
        st.warning(
            f"{len(log_errors)} log record(s) could not be read; dashboard figures exclude them. "
            f"First issue: {log_errors[0]}"
        )

    today = date.today()
    filter_col, _, refresh_col = st.columns([2, 5, 1])
    period = filter_col.selectbox(
        "Reporting period",
        ["Last 7 days", "Last 30 days", "Last 90 days", "All activity"],
        index=1,
        key="support_reporting_period",
    )
    if refresh_col.button("Refresh", help="Reload the latest query log"):
        st.rerun()
    if period == "All activity":
        start_date = min((event["_datetime"].date() for event in events), default=today)
    else:
        days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[period]
        start_date = today - timedelta(days=days - 1)
    filtered = filter_events(events, start_date, today)
    metrics = summarize(filtered)

    st.caption(f"{start_date:%d %b %Y} – {today:%d %b %Y} · source: local query log")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Questions", metrics["questions"])
    metric_cols[1].metric(
        "Answered from docs",
        f"{metrics['answer_rate']:.0%}" if metrics["answer_rate"] is not None else "—",
        help="Answered questions divided by all submitted questions in the selected period.",
    )
    metric_cols[2].metric("Needs review", metrics["needs_review"])
    metric_cols[3].metric(
        "Positive feedback",
        (
            f"{metrics['positive_feedback_rate']:.0%}"
            if metrics["positive_feedback_rate"] is not None
            else "—"
        ),
        help=(
            f"{metrics['positive_feedback']} helpful / "
            f"{metrics['feedback_count']} rated answers."
        ),
    )

    if not metrics["questions"]:
        st.info("No questions were logged during this period.")
    else:
        st.markdown("#### Question volume and outcomes")
        st.bar_chart(daily_volume(filtered), x="Date", y=["Answered", "Needs review", "Other"])
        outcome_cols = st.columns(5)
        outcome_cols[0].metric("Answered", metrics["answered"])
        outcome_cols[1].metric("Related", metrics["related"])
        outcome_cols[2].metric("No answer", metrics["no_answer"])
        outcome_cols[3].metric("Ambiguous", metrics["ambiguous"])
        outcome_cols[4].metric("Empty", metrics["empty"])

    st.divider()
    review_col, source_col = st.columns([1.4, 1])
    with review_col:
        st.markdown("#### Repeated questions to review")
        review_rows = top_review_questions(filtered)
        if review_rows:
            st.dataframe(review_rows, width="stretch", hide_index=True)
        else:
            st.success("No unanswered, partial, or ambiguous questions in this period.")
    with source_col:
        st.markdown("#### Most-used source passages")
        source_rows = top_sources(filtered)
        if source_rows:
            st.dataframe(source_rows, width="stretch", hide_index=True)
        else:
            st.info("No documentation-backed answers in this period.")

    st.download_button(
        "Download review questions (CSV)",
        data=unanswered_csv(filtered),
        file_name=f"support-review-{today.isoformat()}.csv",
        mime="text/csv",
        disabled=not review_rows,
    )
    with st.expander("Metric definitions"):
        st.markdown(
            "- **Questions:** original user submissions; feedback events are not counted as questions.\n"
            "- **Answered from docs:** answered submissions divided by all submissions in the period. "
            "This is not the same as support-ticket deflection.\n"
            "- **Needs review:** related, no-answer, and ambiguous submissions.\n"
            "- **Positive feedback:** helpful ratings divided by all explicit helpful/unhelpful ratings.\n"
            "- **Repeated questions:** normalized exact-text matches among submissions needing review."
        )
