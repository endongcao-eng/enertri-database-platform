"""V4.3 Stage 1 capability standard library acceptance tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory(prefix="enertri_v43_standard_")
_ROOT = Path(_TEST_ROOT.name)
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
    "MEDIA_DIR": str(_ROOT / "media"),
    "ARTIFACT_DIR": str(_ROOT / "artifacts"),
    "WORKSPACE_DIR": str(_ROOT / "workspace"),
    "SECRET_KEY": "test-v43-secret",
    "APP_BOOTSTRAP_ON_STARTUP": "true",
    "TASK_EXECUTION_MODE": "inline",
})

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class CapabilityStandardLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        student = cls.client.post("/api/auth/login", json={"username": "student", "password": "123456"})
        admin = cls.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        cls.student_headers = {"Authorization": f"Bearer {student.json()['access_token']}"}
        cls.admin_headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        _TEST_ROOT.cleanup()

    def test_stage1_catalog_and_mapping_simulation(self):
        overview = self.client.get("/api/capability-standards/overview", headers=self.student_headers)
        self.assertEqual(overview.status_code, 200, overview.text)
        body = overview.json()
        self.assertGreaterEqual(body["knowledge_nodes"], 15)
        self.assertGreaterEqual(body["capabilities"], 8)
        self.assertGreaterEqual(body["resources"], 6)
        self.assertGreater(body["mapping_links"], 30)

        resources = self.client.get("/api/capability-standards/resources", headers=self.student_headers).json()
        selected = [r["id"] for r in resources if r["code"] in {"R-COURSE-HEAT", "R-BOOK-MICRO", "R-TASK-MICRO"}]
        self.assertEqual(len(selected), 3)
        simulation = self.client.post(
            "/api/capability-standards/simulate",
            headers=self.student_headers,
            json={"resource_ids": selected},
        )
        self.assertEqual(simulation.status_code, 200, simulation.text)
        result = simulation.json()
        knowledge = {row["name_zh"]: row for row in result["knowledge"]}
        capabilities = {row["name_zh"]: row for row in result["capabilities"]}
        self.assertIn("微纳尺度传热", knowledge)
        self.assertGreater(knowledge["微纳尺度传热"]["mapping_score"], 70)
        self.assertIn("数值建模与求解", capabilities)
        self.assertIn("Python 科研计算", capabilities)
        self.assertTrue(capabilities["Python 科研计算"]["trace"])
        self.assertIn("不是学生能力分", result["note"])

    def test_read_is_open_to_student_but_maintenance_is_admin_only(self):
        denied = self.client.post(
            "/api/capability-standards/knowledge-nodes",
            headers=self.student_headers,
            json={"code": "K-TEST-DENY", "name_zh": "测试节点", "domain": "test", "node_type": "concept"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        created = self.client.post(
            "/api/capability-standards/knowledge-nodes",
            headers=self.admin_headers,
            json={"code": "K-TEST-ADMIN", "name_zh": "管理员测试知识", "domain": "测试域", "node_type": "concept"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["code"], "K-TEST-ADMIN")


if __name__ == "__main__":
    unittest.main()
