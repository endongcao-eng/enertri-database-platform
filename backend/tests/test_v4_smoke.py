"""EnerTri V4.0 offline smoke test.

Run from backend/ after installing requirements:
    python -m unittest tests.test_v4_smoke

External literature and AI calls are replaced with deterministic local test doubles.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

_TEST_ROOT = tempfile.TemporaryDirectory(prefix="enertri_v4_smoke_")
_ROOT = Path(_TEST_ROOT.name)
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
        "MEDIA_DIR": str(_ROOT / "media"),
        "ARTIFACT_DIR": str(_ROOT / "artifacts"),
        "WORKSPACE_DIR": str(_ROOT / "workspace"),
        "SECRET_KEY": "test-secret-only",
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "test-model",
        "SIMULATION_EXECUTION_ENABLED": "false",
        "APP_BOOTSTRAP_ON_STARTUP": "true",
        "TASK_EXECUTION_MODE": "inline",
    }
)

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app import workspace_router  # noqa: E402


def _fake_literature(*args, **kwargs):
    return {
        "source": "OpenAlex-test-double",
        "total": 1,
        "items": [
            {
                "id": "W1",
                "title": "Welding process monitoring",
                "authors": ["Test Author"],
                "year": 2025,
                "doi": "10.0000/test",
                "cited_by_count": 5,
                "open_access": True,
            }
        ],
        "warning": None,
    }


def _fake_hotspots(*args, **kwargs):
    return {
        "source": "OpenAlex-test-double",
        "query": kwargs.get("query") or (args[0] if args else "welding"),
        "recent_window": "2025-2026",
        "comparison_window": "2023-2024",
        "items": [{"topic_id": "T1", "topic": "Weld monitoring", "recent_count": 20, "previous_count": 10, "growth_percent": 100.0, "momentum": 2.0}],
        "note": "test double",
    }


def _fake_ai(prompt: str, **kwargs):
    return "# 测试输出\n- 基于输入生成的离线回归结果\n- 数据不足处需验证"


def _png_bytes() -> bytes:
    image = Image.new("RGB", (32, 32), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class V4SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_ctx = TestClient(app)
        cls.client = cls.client_ctx.__enter__()
        cls.student_token = cls.client.post("/api/auth/login", json={"username": "student", "password": "123456"}).json()["access_token"]
        cls.admin_token = cls.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()["access_token"]
        cls.student_headers = {"Authorization": f"Bearer {cls.student_token}"}
        cls.admin_headers = {"Authorization": f"Bearer {cls.admin_token}"}

    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)
        _TEST_ROOT.cleanup()

    def test_complete_v4_matrix(self):
        checks: list[str] = []

        def expect(name: str, response, status: int = 200):
            self.assertEqual(response.status_code, status, f"{name}: {response.text}")
            checks.append(name)
            return response

        # 1-3: authentication and status
        expect("student_login", self.client.post("/api/auth/login", json={"username": "student", "password": "123456"}))
        expect("admin_login", self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}))
        expect("workspace_status", self.client.get("/api/workspace/status", headers=self.student_headers))

        with patch.object(workspace_router, "search_openalex", side_effect=_fake_literature), patch.object(
            workspace_router, "research_hotspots", side_effect=_fake_hotspots
        ), patch.object(workspace_router.ai_service, "generate_text", side_effect=_fake_ai):
            # 4-5: literature and hotspots
            expect("literature_search", self.client.post("/api/workspace/literature/search", headers=self.student_headers, json={"query": "welding monitoring"}))
            expect("literature_hotspots", self.client.post("/api/workspace/literature/hotspots", headers=self.student_headers, json={"query": "welding monitoring"}))

            # 6-7: paper reading and review
            paper = {"file": ("paper.txt", "materials and methods\nresults\nconclusion", "text/plain")}
            expect("paper_analysis", self.client.post("/api/workspace/papers/analyze", headers=self.admin_headers, files=paper, data={"focus": "method"}))
            paper = {"file": ("paper.txt", "materials and methods\nresults\nconclusion", "text/plain")}
            expect("paper_review", self.client.post("/api/workspace/papers/review", headers=self.admin_headers, files=paper, data={"literature_query": "welding"}))

            base_write = {
                "task_type": "academic_report",
                "title": "离线测试报告",
                "source_text": "test source",
                "literature": [],
                "data": {"current_a": 220},
            }
            # 8-12: markdown/docx/pptx and downloads
            expect("writing_markdown", self.client.post("/api/workspace/writing/generate", headers=self.admin_headers, json={**base_write, "output_format": "markdown"}))
            docx_job = expect("writing_docx", self.client.post("/api/workspace/writing/generate", headers=self.admin_headers, json={**base_write, "output_format": "docx"})).json()
            docx_download = expect("download_docx", self.client.get(docx_job["artifact_url"], headers=self.admin_headers))
            self.assertTrue(docx_download.content.startswith(b"PK"))
            pptx_job = expect("writing_pptx", self.client.post("/api/workspace/writing/generate", headers=self.admin_headers, json={**base_write, "task_type": "academic_ppt", "output_format": "pptx"})).json()
            pptx_download = expect("download_pptx", self.client.get(pptx_job["artifact_url"], headers=self.admin_headers))
            self.assertTrue(pptx_download.content.startswith(b"PK"))

            # 13-14: image and multimodal analysis
            expect(
                "image_analysis",
                self.client.post(
                    "/api/workspace/images/analyze",
                    headers=self.admin_headers,
                    files={"file": ("sem.png", _png_bytes(), "image/png")},
                    data={"analysis_type": "SEM", "context": "fracture surface"},
                ),
            )
            expect(
                "multimodal_analysis",
                self.client.post(
                    "/api/workspace/multimodal/analyze",
                    headers=self.admin_headers,
                    files=[("files", ("frame.png", _png_bytes(), "image/png")), ("files", ("signals.csv", b"time,current\n0,220\n", "text/csv"))],
                    data={"task": "quality assessment", "context": "GMAW"},
                ),
            )

        material = {
            "material_name": "Q355",
            "material_group": "carbon_low_alloy_steel",
            "composition": {"C": 0.18, "Mn": 1.45, "Si": 0.35, "Cr": 0.12, "Ni": 0.15, "Cu": 0.15, "Mo": 0.02},
            "thickness_mm": 20,
            "joint_type": "butt",
            "defect_type": "裂纹",
            "observations": "根部纵向裂纹",
        }
        # 15-19: rule-based welding assistant
        for name, endpoint in [
            ("weldability", "weldability"),
            ("alloy_elements", "elements"),
            ("process_plan", "process"),
            ("filler_selection", "filler"),
            ("defect_analysis", "defect"),
        ]:
            expect(name, self.client.post(f"/api/workspace/welding/{endpoint}", headers=self.student_headers, json=material))

        telemetry = {
            "session_id": "smoke-001",
            "process": "GMAW",
            "samples": [
                {"timestamp_ms": 0, "current_a": 218, "voltage_v": 24.0, "travel_speed_mm_s": 5.0},
                {"timestamp_ms": 100, "current_a": 221, "voltage_v": 24.2, "travel_speed_mm_s": 4.9},
                {"timestamp_ms": 200, "current_a": 219, "voltage_v": 23.8, "travel_speed_mm_s": 5.1},
            ],
        }
        # 20-21: telemetry success and schema rejection
        expect("telemetry_valid", self.client.post("/api/workspace/telemetry/ingest", headers=self.student_headers, json=telemetry))
        expect("telemetry_invalid", self.client.post("/api/workspace/telemetry/ingest", headers=self.student_headers, json={"session_id": "x", "samples": [{}]}), 422)

        # 22-31: five simulation packages and downloads
        simulation_ids: list[int] = []
        for software in ["hypermesh", "ansys_mapdl", "ansys_fluent", "marc", "flow3d"]:
            created = expect(
                f"simulation_create_{software}",
                self.client.post(
                    "/api/workspace/simulations",
                    headers=self.student_headers,
                    json={"name": f"smoke-{software}", "software": software, "parameters": {"current_a": 220, "voltage_v": 24, "travel_speed_mm_s": 5}},
                ),
            ).json()
            simulation_ids.append(created["id"])
            archive = expect(f"simulation_download_{software}", self.client.get(created["package_url"], headers=self.student_headers))
            self.assertTrue(archive.content.startswith(b"PK"))

        # 32-34: execution permissions, disabled runner, job history
        expect("student_run_denied", self.client.post(f"/api/workspace/simulations/{simulation_ids[0]}/run", headers=self.student_headers), 403)
        expect("admin_run_disabled", self.client.post(f"/api/workspace/simulations/{simulation_ids[0]}/run", headers=self.admin_headers), 400)
        jobs = expect("job_history", self.client.get("/api/workspace/jobs", headers=self.student_headers)).json()
        self.assertGreaterEqual(len(jobs), 1)

        self.assertEqual(len(checks), 34, checks)


if __name__ == "__main__":
    unittest.main()
