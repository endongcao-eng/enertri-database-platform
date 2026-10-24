from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.publication_service import evaluate_relevance_dataset


class EnergyRelevanceEvaluationTest(unittest.TestCase):
    def test_curated_energy_set_has_no_cultural_false_positive(self):
        fixture = Path(__file__).parent / "fixtures" / "energy_relevance_eval.json"
        metrics = evaluate_relevance_dataset(json.loads(fixture.read_text(encoding="utf-8")))
        self.assertEqual(metrics["count"], 6)
        self.assertEqual(metrics["false_positive"], 0)
        self.assertGreaterEqual(metrics["precision"], 0.95)
        self.assertGreaterEqual(metrics["recall"], 0.75)


if __name__ == "__main__":
    unittest.main()
