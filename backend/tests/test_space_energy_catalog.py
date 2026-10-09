from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import SpaceEnergyLiterature
from app.space_energy_catalog import (
    SpaceEnergyCatalogError,
    connection_status,
    list_literatures,
    map_literature,
)


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class SpaceEnergyCatalogTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SpaceEnergyLiterature.__table__.create(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_maps_matching_literature_fields_and_mirrors_after_live_read(self):
        payload = {
            "total": 1,
            "offset": 0,
            "limit": 100,
            "items": [{
                "id": "paper-001", "title": "A space energy paper", "authors": ["A. Author", "B. Author"],
                "year": 2025, "source": "Space Journal", "abstract": "Abstract text", "doi": "10.1234/example",
                "url": "https://example.org/paper", "tags": ["solar", "power"],
            }],
        }
        with patch("app.space_energy_catalog.httpx.get", return_value=_Response(payload)) as request:
            result = list_literatures(self.db, limit=100)

        request.assert_called_once()
        paper = result["items"][0]
        self.assertEqual(paper["id"], "paper-001")
        self.assertEqual(paper["authors"], ["A. Author", "B. Author"])
        self.assertEqual(paper["source"], "Space Journal")
        self.assertEqual(paper["open_url"], "https://example.org/paper")
        mirrored = self.db.get(SpaceEnergyLiterature, "paper-001")
        self.assertEqual(mirrored.authors, "A. Author,B. Author")
        self.assertEqual(mirrored.tags, "solar,power")

    def test_connection_status_is_offline_when_upstream_is_unreachable(self):
        with patch("app.space_energy_catalog.httpx.get", side_effect=httpx.ConnectError("offline")):
            status = connection_status()
        self.assertFalse(status["available"])
        self.assertIn("暂不可用", status["message"])

    def test_mapping_keeps_the_upstream_id_and_target_schema_fields(self):
        result = map_literature({"id": "stable-id", "title": "Title", "authors": "A,B", "tags": "x,y", "source_file": "PDF/a.pdf"})
        self.assertEqual(result["id"], "stable-id")
        self.assertEqual(result["authors"], ["A", "B"])
        self.assertEqual(result["tags"], ["x", "y"])
        self.assertEqual(result["source_file"], "PDF/a.pdf")


if __name__ == "__main__":
    unittest.main()
