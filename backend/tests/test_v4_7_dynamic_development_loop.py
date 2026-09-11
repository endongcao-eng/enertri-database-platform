"""V4.7 Stage 5 integrated roadmap and evidence closed-loop tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory(prefix="enertri_v47_loop_")
_ROOT = Path(_TEST_ROOT.name)
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
    "MEDIA_DIR": str(_ROOT / "media"),
    "ARTIFACT_DIR": str(_ROOT / "artifacts"),
    "WORKSPACE_DIR": str(_ROOT / "workspace"),
    "SECRET_KEY": "test-v47-secret",
    "APP_BOOTSTRAP_ON_STARTUP": "true",
    "TASK_EXECUTION_MODE": "inline",
})

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class DynamicDevelopmentLoopStage5Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        student = cls.client.post("/api/auth/login", json={"username": "student", "password": "123456"})
        admin = cls.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        cls.student = student.json()["user"]
        cls.admin = admin.json()["user"]
        cls.student_headers = {"Authorization": f"Bearer {student.json()['access_token']}"}
        cls.admin_headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}
        goals = cls.client.get("/api/development-planning/goals", headers=cls.student_headers).json()
        cls.student_goal = next(g for g in goals if g["goal_type"] == "student_growth")

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        _TEST_ROOT.cleanup()

    def test_integrated_recommendations_cover_five_resource_types(self):
        gid = self.student_goal["id"]
        resp = self.client.get(f"/api/development-execution/goals/{gid}/roadmap", headers=self.student_headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["stage"], "V4.7 Stage 5")
        types = {x["item_type"] for x in data["items"]}
        self.assertTrue({"course", "book", "project_task", "publication", "research_project"}.issubset(types), types)
        self.assertGreaterEqual(len(data["snapshots"]), 1)
        self.assertIn("closed_loop", data)

    def test_completing_standard_resource_generates_pending_evidence_and_snapshot(self):
        gid = self.student_goal["id"]
        roadmap = self.client.get(f"/api/development-execution/goals/{gid}/roadmap", headers=self.student_headers).json()
        item = next(x for x in roadmap["items"] if x["item_type"] in {"course", "book", "project_task"} and x["status"] != "completed")
        done = self.client.patch(
            f"/api/development-execution/items/{item['id']}", headers=self.student_headers,
            json={"status": "completed", "completion_note": "已完成路线要求并提交材料，等待导师核验。"},
        )
        self.assertEqual(done.status_code, 200, done.text)
        payload = done.json()
        self.assertEqual(payload["item"]["status"], "completed")
        self.assertEqual(payload["item"]["progress_percent"], 100)
        self.assertIsNotNone(payload["generated_pending_evidence_id"])
        evidences = self.client.get("/api/research-profile/evidence", headers=self.student_headers)
        self.assertEqual(evidences.status_code, 200, evidences.text)
        self.assertTrue(any(x["id"] == payload["generated_pending_evidence_id"] and x["verification_status"] == "pending" for x in evidences.json()))
        after = self.client.get(f"/api/development-execution/goals/{gid}/roadmap", headers=self.student_headers).json()
        self.assertGreaterEqual(len(after["snapshots"]), 2)
        self.assertGreaterEqual(after["summary"]["completed"], 1)

    def test_privacy_boundary_and_admin_cross_user_access(self):
        gid = self.student_goal["id"]
        admin_goals = self.client.get("/api/development-planning/goals", headers=self.admin_headers).json()
        teacher_goal = next(g for g in admin_goals if g["goal_type"] == "teacher_research_direction")
        denied = self.client.get(f"/api/development-execution/goals/{teacher_goal['id']}/roadmap", headers=self.student_headers)
        self.assertEqual(denied.status_code, 403, denied.text)
        allowed = self.client.get(f"/api/development-execution/goals/{gid}/roadmap", headers=self.admin_headers)
        self.assertEqual(allowed.status_code, 200, allowed.text)


if __name__ == "__main__":
    unittest.main()
