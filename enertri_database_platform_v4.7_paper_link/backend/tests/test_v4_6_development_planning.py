"""V4.6 Stage 4 learning path and teacher research-direction gap analysis tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory(prefix="enertri_v46_plan_")
_ROOT = Path(_TEST_ROOT.name)
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
    "MEDIA_DIR": str(_ROOT / "media"),
    "ARTIFACT_DIR": str(_ROOT / "artifacts"),
    "WORKSPACE_DIR": str(_ROOT / "workspace"),
    "SECRET_KEY": "test-v46-secret",
    "APP_BOOTSTRAP_ON_STARTUP": "true",
    "TASK_EXECUTION_MODE": "inline",
})

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class DevelopmentPlanningStage4Test(unittest.TestCase):
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

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        _TEST_ROOT.cleanup()

    def test_student_goal_recommends_courses_books_and_practice_from_gaps(self):
        goals = self.client.get("/api/development-planning/goals", headers=self.student_headers)
        self.assertEqual(goals.status_code, 200, goals.text)
        goal = next(row for row in goals.json() if row["goal_type"] == "student_growth")
        analysis = self.client.get(f"/api/development-planning/goals/{goal['id']}/analysis", headers=self.student_headers)
        self.assertEqual(analysis.status_code, 200, analysis.text)
        data = analysis.json()
        self.assertEqual(data["stage"], "V4.6 Stage 4")
        self.assertGreaterEqual(len(data["knowledge_gaps"]), 1)
        self.assertTrue(data["course_recommendations"])
        self.assertTrue(data["learning_path"])
        self.assertTrue(any(row["code"] == "R-COURSE-CHIP" for row in data["course_recommendations"]))
        self.assertIn("resource_priority", data["scoring_model"])

    def test_teacher_new_direction_exposes_gap_learning_resources_and_collaborators(self):
        goals = self.client.get("/api/development-planning/goals", headers=self.admin_headers)
        self.assertEqual(goals.status_code, 200, goals.text)
        goal = next(row for row in goals.json() if row["goal_type"] == "teacher_research_direction")
        analysis = self.client.get(f"/api/development-planning/goals/{goal['id']}/analysis", headers=self.admin_headers)
        self.assertEqual(analysis.status_code, 200, analysis.text)
        data = analysis.json()
        gap_codes = {row["code"] for row in data["knowledge_gaps"]}
        self.assertTrue({"K-GNN", "K-DL"} & gap_codes)
        recommendation_codes = {row["code"] for row in data["recommendations"]}
        self.assertIn("R-COURSE-DL", recommendation_codes)
        self.assertIn("R-BOOK-GNN", recommendation_codes)
        self.assertTrue(data["collaborator_recommendations"])
        self.assertTrue(data["literature_queries"])

    def test_preview_and_privacy_boundary(self):
        preview = self.client.post(
            "/api/development-planning/preview",
            headers=self.student_headers,
            json={
                "goal_type": "student_growth",
                "title": "芯片热管理科研方向",
                "description": "希望补齐芯片热管理、材料热物性、数值模拟能力",
            },
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIn("target_fit", preview.json())
        denied = self.client.get(f"/api/development-planning/goals?user_id={self.admin['id']}", headers=self.student_headers)
        self.assertEqual(denied.status_code, 403, denied.text)


if __name__ == "__main__":
    unittest.main()
