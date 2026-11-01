import json
import unittest
from core import classify, extract, export_csv, label_words, validate_classes


class FakeBedrock:
    def __init__(self, result, stop="end_turn"):
        self.result, self.stop, self.requests = result, stop, []

    def converse(self, **request):
        self.requests.append(request)
        return {"stopReason": self.stop, "output": {"message": {"content": [{"text": json.dumps(self.result)}]}}}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.classes = [
            {"name": "Sales", "description": "Buying a product", "fields": [{"name": "product", "description": "Requested product"}]},
            {"name": "Support", "description": "Help with an existing product", "fields": [{"name": "issue", "description": "Reported issue"}]}]

    def test_classification_then_class_specific_extraction(self):
        transcript = "Speaker 1: My printer is broken."
        classification = classify(FakeBedrock({"class": "Support", "reason": "Existing product problem"}), "model", transcript, self.classes)
        fields = next(c["fields"] for c in self.classes if c["name"] == classification["class"])
        fake = FakeBedrock({"fields": {"issue": {"value": "Broken printer", "evidence": "My printer is broken."}}})
        result = extract(fake, "model", transcript, fields)
        self.assertEqual(result["issue"]["value"], "Broken printer")
        sent = json.loads(fake.requests[0]["messages"][0]["content"][0]["text"])
        self.assertEqual([f["name"] for f in sent["fields"]], ["issue"])

    def test_invalid_class_and_truncated_response_rejected(self):
        for fake in [FakeBedrock({"class": "Invented", "reason": "none"}),
                     FakeBedrock({"class": "Support", "reason": "help"}, "max_tokens")]:
            with self.assertRaises(ValueError):
                classify(fake, "model", "help", self.classes)

    def test_unclassified_is_allowed(self):
        self.assertEqual(classify(FakeBedrock({"class": "Unclassified", "reason": "No match"}), "m", "weather", self.classes)["class"], "Unclassified")

    def test_missing_value_and_fabricated_evidence(self):
        fields = self.classes[0]["fields"]
        missing = FakeBedrock({"fields": {"product": {"value": None, "evidence": None}}})
        self.assertIsNone(extract(missing, "m", "hello", fields)["product"]["value"])
        fabricated = extract(FakeBedrock({"fields": {"product": {"value": "car", "evidence": "invented"}}}), "m", "hello", fields)
        self.assertIsNone(fabricated["product"]["value"])
        self.assertIn("Needs review", fabricated["product"]["warning"])
        with self.assertRaises(ValueError):
            extract(FakeBedrock({"fields": {"issue": {"value": None, "evidence": None}}}), "m", "hello", fields)

    def test_quote_formatting_and_partial_results(self):
        fields = [{"name": "issue"}, {"name": "product"}]
        transcript = "The ‘Printer’\n  is broken."
        fake = FakeBedrock({"fields": {
            "issue": {"value": "Broken printer", "evidence": "the 'Printer' is broken."},
            "product": {"value": "Model X100", "evidence": "Model X100"}}})
        result = extract(fake, "m", transcript, fields)
        self.assertEqual(result["issue"]["value"], "Broken printer")
        self.assertEqual(result["issue"]["evidence"], transcript)
        self.assertIsNone(result["product"]["value"])
        self.assertIn("Needs review", result["product"]["warning"])
        self.assertIn("Needs review", export_csv([{"name": "sample.mp3", "fields": result}]).decode("utf-8-sig"))

    def test_speaker_change_splits_transcript_and_gaps_remain_unknown(self):
        words = [{"start": 0, "end": 1, "text": " Hello"},
                 {"start": 1, "end": 2, "text": " there"},
                 {"start": 2, "end": 3, "text": " bye"}]
        rows = label_words(words, [(0, 1, "Speaker 1"), (1, 2, "Speaker 2")])
        self.assertEqual([r["speaker"] for r in rows], ["Speaker 1", "Speaker 2", "Unknown"])

    def test_duplicate_fields_rejected_and_csv_formulas_neutralized(self):
        bad = [dict(self.classes[0], fields=[{"name": "x"}, {"name": "X"}])]
        with self.assertRaises(ValueError):
            validate_classes(bad)
        result = export_csv([{"name": "=formula.mp3", "class": "Support", "fields": {"issue": {"value": "+formula", "evidence": "quote"}}}]).decode("utf-8-sig")
        self.assertIn("'=formula.mp3", result)
        self.assertIn("'+formula", result)


if __name__ == "__main__":
    unittest.main()
