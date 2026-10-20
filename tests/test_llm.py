import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docqa import llm  # noqa: E402
from docqa.engine import Assistant  # noqa: E402


class TestGeminiSynthesis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.answer = Assistant(ROOT / "starter_kit" / "data").ask(
            "How long is a password reset link valid?"
        )
        cls.hits = cls.answer.sources

    def setUp(self):
        llm.configure({"api_key": "test-gemini-key"})
        self.addCleanup(llm.configure, {})

    def test_default_model_is_configurable(self):
        self.assertEqual(llm.model_name(), "gemini-3.8-flash")
        llm.configure({"api_key": "test-gemini-key", "model": "gemini-test"})
        self.assertEqual(llm.model_name(), "gemini-test")
        llm.configure({"api_key": "test-gemini-key"})
        self.assertEqual(llm.model_name(), llm.DEFAULT_GEMINI_MODEL)

    def test_timeout_is_configurable(self):
        llm.configure({"api_key": "test-gemini-key", "timeout_seconds": 180})
        self.assertEqual(llm.timeout_seconds(), 180)
        llm.configure({"api_key": "test-gemini-key"})
        self.assertEqual(llm.timeout_seconds(), llm.DEFAULT_TIMEOUT_SECONDS)

    def test_missing_key_disables_provider_without_fallback(self):
        llm.configure({})
        self.assertFalse(llm.has_gemini_api_key())
        self.assertFalse(llm.available())
        self.assertEqual(llm.provider_name(), "gemini")

    def test_gemini_request_uses_key_schema_and_timeout(self):
        captured = {}

        class FakeInteractions:
            async def create(self, **kwargs):
                captured["request"] = kwargs
                return SimpleNamespace(output_text='{"answerable": false}')

        class FakeAio:
            def __init__(self):
                self.interactions = FakeInteractions()

            async def aclose(self):
                captured["closed"] = True

        class FakeClient:
            def __init__(self, **kwargs):
                captured["client"] = kwargs
                self.aio = FakeAio()

        fake_genai = SimpleNamespace(Client=FakeClient)
        fake_types = SimpleNamespace(
            HttpOptions=lambda **kwargs: SimpleNamespace(**kwargs)
        )
        fake_google = SimpleNamespace(genai=fake_genai)
        fake_google_genai = SimpleNamespace(types=fake_types)

        llm.configure({"api_key": "test-gemini-key", "timeout_seconds": 180})
        with patch.dict(
            sys.modules,
            {
                "google": fake_google,
                "google.genai": fake_google_genai,
                "google.genai.types": fake_types,
            },
        ):
            result = asyncio.run(llm._request_answer("question", "gemini-test"))

        self.assertEqual(captured["client"]["api_key"], "test-gemini-key")
        self.assertEqual(captured["client"]["http_options"].timeout, 180000)
        self.assertEqual(captured["request"]["model"], "gemini-test")
        self.assertEqual(
            captured["request"]["response_format"]["mime_type"], "application/json"
        )
        self.assertNotIn(
            "additionalProperties",
            captured["request"]["response_format"]["schema"],
        )
        self.assertEqual(captured["request"]["input"], "question")
        self.assertEqual(captured["request"]["system_instruction"], llm.SYSTEM)
        self.assertTrue(captured["closed"])
        self.assertEqual(result, '{"answerable": false}')

    def test_supported_claim_is_accepted_with_valid_citation(self):
        response = {
            "answerable": True,
            "answer": "The reset link is valid for 15 minutes [1].",
            "citations": [1],
        }
        with patch.object(llm, "_request_answer", new=AsyncMock(return_value=json.dumps(response))):
            result = llm.synthesize("How long is the reset link valid?", self.hits)
        self.assertEqual(result, response)

    def test_model_veto_is_preserved(self):
        response = {"answerable": False, "answer": "", "citations": []}
        with patch.object(llm, "_request_answer", new=AsyncMock(return_value=json.dumps(response))):
            result = llm.synthesize("Can I connect to Salesforce?", self.hits)
        self.assertEqual(result, {"answerable": False})

    def test_unsupported_number_falls_back_to_extractive(self):
        response = {
            "answerable": True,
            "answer": "The reset link lasts 90 minutes [1].",
            "citations": [1],
        }
        with patch.object(llm, "_request_answer", new=AsyncMock(return_value=json.dumps(response))):
            with self.assertLogs(llm.logger, level="WARNING"):
                result = llm.synthesize("How long is the reset link valid?", self.hits)
        self.assertIsNone(result)

    def test_provider_failure_is_logged_and_falls_back(self):
        with patch.object(
            llm,
            "_request_answer",
            new=AsyncMock(side_effect=RuntimeError("authentication rejected")),
        ):
            with self.assertLogs(llm.logger, level="ERROR"):
                result = llm.synthesize("How long is the reset link valid?", self.hits)
        self.assertIsNone(result)

class TestQueryRewrite(unittest.TestCase):
    def setUp(self):
        llm.configure({"api_key": "test-gemini-key"})
        self.addCleanup(llm.configure, {})
        self.bot = Assistant(ROOT / "data" / "docs")

    def _rewrite(self, question):
        return patch.object(
            llm, "_request_answer", new=AsyncMock(return_value=json.dumps({"question": question}))
        )

    def _llm_on(self):
        return patch.object(llm, "available", return_value=True)

    def test_without_llm_abbreviation_is_declined(self):
        r = self.bot.ask("reset pwd", use_llm=False)
        self.assertEqual(r.status, "no_answer")
        self.assertIsNone(r.rewritten_query)

    def test_llm_rewrite_recovers_abbreviation(self):
        synth = {"answerable": True, "answer": "Use Forgot password [1].", "citations": [1]}
        with self._llm_on(), self._rewrite("How do I reset my password?"), \
                patch.object(llm, "synthesize", return_value=synth) as syn:
            r = self.bot.ask("reset pwd", use_llm=True)
        self.assertEqual(r.status, "answer")
        self.assertEqual(r.rewritten_query, "How do I reset my password?")
        self.assertEqual(syn.call_args.args[0], "reset pwd")   # LLM still sees the user's own words

    def test_rewrite_cannot_force_answer_for_unknown_vendor(self):
        with self._llm_on(), self._rewrite("Can I connect Solstice to Salesforce?"):
            r = self.bot.ask("salesforce sync?", use_llm=True)
        self.assertNotEqual(r.status, "answer")

    def test_rewrite_failure_keeps_original_verdict(self):
        with self._llm_on(), patch.object(
            llm, "_request_answer", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            with self.assertLogs(llm.logger, level="ERROR"):
                r = self.bot.ask("reset pwd", use_llm=True)
        self.assertEqual(r.status, "no_answer")
        self.assertIsNone(r.rewritten_query)

    def test_confident_answer_skips_rewrite(self):
        with self._llm_on(), patch.object(llm, "rewrite_query") as rw, \
                patch.object(llm, "synthesize", return_value=None):
            r = self.bot.ask("How do I reset my password?", use_llm=True)
        self.assertEqual(r.status, "answer")
        rw.assert_not_called()

    def test_suggest_rewrite_is_none_without_llm(self):
        self.assertIsNone(self.bot.suggest_rewrite("reset pwd", use_llm=False))

    def test_suggest_rewrite_returns_llm_version(self):
        with self._llm_on(), self._rewrite("How do I reset my password?"):
            self.assertEqual(self.bot.suggest_rewrite("reset pwd", use_llm=True), "How do I reset my password?")

    def test_confirmed_rewrite_records_impact(self):
        synth = {"answerable": True, "answer": "Use Forgot password [1].", "citations": [1]}
        with self._llm_on(), patch.object(llm, "synthesize", return_value=synth):
            r = self.bot.ask("reset pwd", use_llm=True, rewritten="How do I reset my password?")
        self.assertEqual(r.status, "answer")
        self.assertEqual(r.baseline_status, "no_answer")   # what plain search said for "reset pwd"
        self.assertEqual(r.rewritten_query, "How do I reset my password?")

    def test_confirmed_rewrite_returns_document_answer_when_synthesis_fails(self):
        with self._llm_on(), patch.object(llm, "synthesize", return_value=None):
            result = Assistant(ROOT / "starter_kit" / "data").ask(
                "API rate limit",
                use_llm=True,
                rewritten="What are the API rate limits?",
            )
        self.assertEqual(result.status, "answer")
        self.assertIn("60 requests per minute", result.message)
        self.assertIn("300 requests per minute", result.message)
        self.assertEqual(result.mode, "extractive")

    def test_declined_suggestion_uses_original_wording(self):
        with self._llm_on(), patch.object(llm, "rewrite_query") as rw:
            r = self.bot.ask("reset pwd", use_llm=True, auto_rewrite=False)
        self.assertEqual(r.status, "no_answer")
        rw.assert_not_called()

    def test_junk_rewrite_is_ignored(self):
        with self._rewrite("x" * 500):
            self.assertIsNone(llm.rewrite_query("reset pwd", ["A > B"]))
        with self._rewrite("Reset pwd?"):
            self.assertIsNone(llm.rewrite_query("reset pwd", ["A > B"]))


if __name__ == "__main__":
    unittest.main()
