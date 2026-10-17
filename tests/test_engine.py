import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docqa.engine import Assistant, Config
from docqa.text import tokenize

bot = Assistant(ROOT / "data" / "docs", Config())


class TestText(unittest.TestCase):
    def test_stem_consistency(self):
        self.assertEqual(tokenize("invoices invoiced invoice"), ["invoic"] * 3)
        self.assertEqual(tokenize("expires expired expire"), ["expir"] * 3)

    def test_stopwords(self):
        self.assertEqual(tokenize("how do I the"), [])


class TestDecisions(unittest.TestCase):
    def test_answer_has_source(self):
        r = bot.ask("How do I reset my password?")
        self.assertEqual(r.status, "answer")
        self.assertTrue(r.sources)

    def test_unknown_rare_term_blocks_answer(self):
        # 'export' is covered, but 'Salesforce' is not in the docs -> must not answer
        r = bot.ask("Can I export reports to Salesforce?")
        self.assertNotEqual(r.status, "answer")

    def test_gibberish_declines(self):
        self.assertEqual(bot.ask("asdkjh qwoeiu").status, "no_answer")

    def test_empty(self):
        self.assertEqual(bot.ask("   ?? ").status, "empty")

    def test_plan_specific_answer_includes_both_plans(self):
        r = bot.ask("What is the export row limit?")
        text = " ".join(s.chunk.text for s in r.sources)
        self.assertIn("10,000", text)
        self.assertIn("100,000", text)

    def test_ambiguous_returns_options(self):
        r = bot.ask("When does it expire?")
        self.assertEqual(r.status, "ambiguous")
        self.assertGreaterEqual(len(r.options), 2)


if __name__ == "__main__":
    unittest.main()
