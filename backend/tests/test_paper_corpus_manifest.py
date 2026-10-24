from __future__ import annotations

import json
import unittest
import tempfile
from pathlib import Path


class PaperCorpusManifestTest(unittest.TestCase):
    def test_corpus_covers_required_research_layouts(self):
        path = Path(__file__).parent / "fixtures" / "paper_corpus" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        cases = {case["id"]: case for case in manifest["cases"]}
        for required in ("four_tables_ruled", "two_column_energy", "scanned_english", "scanned_chinese"):
            self.assertIn(required, cases)
        self.assertEqual(cases["four_tables_ruled"]["expected_tables"], 4)
        self.assertTrue(cases["four_tables_ruled"]["expected_bbox"])
        self.assertEqual(cases["scanned_chinese"]["ocr_lang"], "chi_sim+eng")
        self.assertTrue(all(case.get("source_anchor") for case in manifest["cases"]))

    def test_four_table_layout_is_detectable_with_bbox_metadata(self):
        import fitz
        import pdfplumber
        from app.paper_pipeline import _extract_pdf_tables
        from .fixtures.paper_corpus.build_layout_fixtures import build_four_tables
        with tempfile.TemporaryDirectory() as directory:
            path = build_four_tables(Path(directory) / "four-tables.pdf")
            pdf = fitz.open(str(path))
            pages = [{"page_number": 1, "text": pdf[0].get_text("text")}]
            tables, diagnostics = _extract_pdf_tables(pdf, pages, path, pdfplumber)
            self.assertGreaterEqual(len(tables), 4, diagnostics)
            self.assertTrue(all(item.get("bbox") and item.get("confidence", 0) > 0 for item in tables[:4]))
            self.assertEqual([item["page_number"] for item in tables[:4]], [1, 1, 1, 1])
            pdf.close()


if __name__ == "__main__":
    unittest.main()
