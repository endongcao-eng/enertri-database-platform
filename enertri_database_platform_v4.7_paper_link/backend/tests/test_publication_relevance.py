from __future__ import annotations

import unittest

from app.publication_service import filter_relevant_publications


class PublicationRelevanceTest(unittest.TestCase):
    def test_space_energy_search_rejects_space_only_cultural_article(self):
        rows = [
            {"title": "杭州茶文化资源发展空间可能性的探索", "abstract": "文化资源空间发展研究", "journal": "社会科学", "keywords": []},
            {"title": "Space based solar power for orbital energy systems", "abstract": "A study of space energy conversion and power transmission.", "journal": "Energy", "keywords": ["space energy", "solar"]},
        ]
        accepted, filtered = filter_relevant_publications(rows, "空间 能源")
        self.assertEqual(filtered, 1)
        self.assertEqual(len(accepted), 1)
        self.assertIn("solar", accepted[0]["title"].lower())
        self.assertGreaterEqual(accepted[0]["relevance_score"], 70)

    def test_welding_query_keeps_engineering_result(self):
        rows = [
            {"title": "Laser welding process window for aluminum alloy", "abstract": "The welding parameters and thermal behavior are analyzed.", "journal": "Materials", "keywords": ["welding", "alloy"]},
        ]
        accepted, filtered = filter_relevant_publications(rows, "激光焊接")
        self.assertEqual(filtered, 0)
        self.assertEqual(len(accepted), 1)
        self.assertIn("welding", accepted[0]["relevance_reasons"])


if __name__ == "__main__":
    unittest.main()
