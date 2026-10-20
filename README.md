# Solstice Docs Assistant

Plain-English Q&A over Solstice Learning documentation, built with Python and Streamlit. The default app uses the provided starter-kit documents and questions. Answers are retrieved from documentation; when the docs do not support an answer, the assistant abstains instead of guessing.

## Quick start

From the repository root:

```bash
# macOS/Linux: python3 -m venv .venv && source .venv/bin/activate
```

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

The app works in retrieval-only mode without an API key. Optional answer polishing uses the Gemini API. Configure the local Streamlit secret described below, then enable **Polish answers with an LLM** in the sidebar. The default model is `gemini-3.8-flash`.

The Streamlit app loads `starter_kit/data` by default. The Markdown corpus in `data/docs` is used by the separate regression evaluation; questions covered only by that corpus will not be answerable in the default app unless `DOCS` in `app.py` is changed.

## Support insights

The **Support insights** tab summarizes the local query log with date-range filters, question volume and outcomes, answer-from-docs rate, explicit helpful/unhelpful feedback, repeated questions needing review, and most-used source passages. It can export the filtered review queue as CSV. Feedback events are kept separate from question counts; “answered from docs” is not presented as ticket deflection. A newly selected reporting period is applied immediately, and **Refresh** reloads the log from disk.

The log contains raw question text. Restrict access to the Support insights view and apply appropriate log retention and privacy controls before using it with real customer traffic.

## Demo login

Sign in with the fixed demo credentials: username `admin`, password `123456`. There is no signup or additional-user setup. This shared, weak password is for local demonstrations only; do not deploy this login publicly or use it for real customer data. Replace it with managed SSO/OIDC and proper access controls before production. The Gemini key remains in the local, git-ignored `.streamlit\secrets.toml` file; never commit that file.

### Configure Gemini answer polishing

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (git-ignored) and add your Gemini API key:

```toml
[gemini]
api_key = "YOUR_GEMINI_API_KEY"
model = "gemini-3.8-flash"
timeout_seconds = 120
```

The app reads the key and settings directly from this file; no environment variable or `.env` file is used. The LLM backend is Gemini only; a missing key or API failure leaves the extractive answer in place. Restart Streamlit after changing the secrets file. Never commit real keys or share them in chat.

The Gemini integration uses the SDK's Interactions API. `requirements.txt` requires `google-genai` 2.0.0 or newer; reinstall dependencies after updating an existing checkout with `python -m pip install --upgrade -r requirements.txt`.

## Run with Docker

Build and start the container from the project root:

```powershell
docker compose up --build -d
```

Open <http://localhost:8501>. Sign in with the demo credentials shown on the login screen. The app runs without a Gemini key; to enable Gemini, set the following environment variables before starting Compose:

```powershell
$env:GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
$env:GEMINI_MODEL = "gemini-3.8-flash"
$env:GEMINI_TIMEOUT_SECONDS = "120"
docker compose up --build -d
```

The API key is supplied at runtime and is not baked into the image. Alternatively, place it in your deployment platform's secret manager. `compose.yaml` persists query logs in a named Docker volume. To stop the container, run `docker compose down`; to also delete the saved logs, run `docker compose down --volumes`.

You can also build and run the image directly:

```powershell
docker build -t solstice-docs-assistant .
docker run --rm -p 8501:8501 -e GEMINI_API_KEY solstice-docs-assistant
```

The included login is demo-only (`admin` / `123456`) and is not suitable for a public or production deployment. Do not expose this container to untrusted networks without replacing the demo authentication and adding appropriate access controls. `.dockerignore` excludes local Streamlit secrets, environment files, caches, tests, and logs from the image build context.

## Run the provided example questions

The default evaluation runs the five questions shipped in `starter_kit/data/example_questions.json` against `starter_kit/data/docs.json`:

```powershell
python eval/run_eval.py -v
```

A stricter starter-corpus check (required facts such as "15 minutes", plus extra out-of-scope probes):

```bash
python eval/run_eval.py --docs starter_kit/data --questions eval/starter_extra.json -v
```

## Run the custom-corpus regression evaluation

The repository also includes a separate Markdown corpus in `data/docs/` and a 16-case regression set in `eval/questions.json`:

```powershell
python eval/run_eval.py --docs data/docs --questions eval/questions.json -v
```

Both evaluation commands return a non-zero exit code on a failed expected status, source, or required fact.

## Documentation formats

The loader accepts either:

- A directory containing `docs.json` with a top-level `docs` list. Each document needs `doc_id`, `title`, and `content` strings. This is the provided starter-kit format.
- A directory containing Markdown articles (`.md`) with `#` titles and `##` sections.
- A path directly to a JSON file using the same `docs` structure.

Do not mix `docs.json` and Markdown articles in the same directory; the loader rejects this to prevent accidentally indexing two different corpora.

## Layout

```text
app.py                    Streamlit UI and default starter-kit corpus
docqa/                    Loader, text processing, retrieval, answer policy, optional LLM
starter_kit/data/         Provided JSON seed docs and example questions
data/docs/                Additional Markdown corpus for regression evaluation
eval/run_eval.py          Evaluates either provided or custom question sets
eval/questions.json       Custom-corpus regression cases
tests/                    Unit tests for both corpora
SOLUTION_DESIGN.md        Design decisions, trade-offs, and limitations
```

Run the unit tests with:

```powershell
python -m unittest discover -s tests -v
```

## Known limitations

- Very short queries whose terms miss a passage's title/heading are shown as "related" rather than answered (e.g. "What roles can I assign?"); this over-refuses some answerable questions by design.
- Answers are whole passages; the key sentence is not highlighted yet.
- Keyword/BM25 retrieval can miss paraphrases with little vocabulary overlap.
- The confidence thresholds and synonym map need tuning against real admin questions.
- Optional LLM output has citation and numeric checks, but retrieval-only answers provide the strongest grounding.
- Query logs store raw questions in `data/logs/queries.jsonl`; define access controls and retention before production.
- Documentation is indexed at app startup; production use should refresh the index when docs change.
