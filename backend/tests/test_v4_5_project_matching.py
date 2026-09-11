"""V4.5 Stage 3 project requirement, talent matching, and team recommendation tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory(prefix="enertri_v45_match_")
_ROOT = Path(_TEST_ROOT.name)
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
    "MEDIA_DIR": str(_ROOT / "media"),
    "ARTIFACT_DIR": str(_ROOT / "artifacts"),
    "WORKSPACE_DIR": str(_ROOT / "workspace"),
    "SECRET_KEY": "test-v45-secret",
    "APP_BOOTSTRAP_ON_STARTUP": "true",
    "TASK_EXECUTION_MODE": "inline",
})

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class ProjectMatchingTest(unittest.TestCase):
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

    def test_project_requirement_model_and_explainable_matching(self):
        projects = self.client.get("/api/project-matching/projects", headers=self.admin_headers)
        self.assertEqual(projects.status_code, 200, projects.text)
        project = next(row for row in projects.json() if row["title"] == "基于机器学习的材料热物性预测")
        self.assertGreaterEqual(len(project["capability_requirements"]), 5)
        self.assertTrue(any(row["is_critical"] for row in project["capability_requirements"]))

        matches = self.client.get(f"/api/project-matching/projects/{project['id']}/matches", headers=self.admin_headers)
        self.assertEqual(matches.status_code, 200, matches.text)
        data = matches.json()
        self.assertGreaterEqual(data["candidate_count"], 4)
        self.assertGreater(data["candidates"][0]["match_score"], 55)
        self.assertTrue(data["candidates"][0]["capability_details"])
        self.assertIn("satisfaction", data["candidates"][0]["capability_details"][0])
        self.assertIn("gaps", data["candidates"][0])
        self.assertIn("confidence", data["scoring_model"])

    def test_team_recommendation_is_complementary_not_score_sum(self):
        projects = self.client.get("/api/project-matching/projects", headers=self.admin_headers).json()
        project = next(row for row in projects if row["title"] == "基于机器学习的材料热物性预测")
        response = self.client.get(f"/api/project-matching/projects/{project['id']}/teams?team_size=3", headers=self.admin_headers)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["teams"])
        team = data["teams"][0]
        self.assertEqual(len(team["members"]), 3)
        self.assertIn("complementarity_gain", team)
        self.assertTrue(all(member["suggested_responsibilities"] for member in team["members"]))
        self.assertIn("不是简单把个人分数相加", data["note"])

    def test_draft_generation_and_privacy_boundary(self):
        draft = self.client.post(
            "/api/project-matching/draft-requirements",
            headers=self.admin_headers,
            json={"title": "微纳热输运机器学习建模", "description": "使用 Python 对材料热物性数据进行预测和误差分析"},
        )
        self.assertEqual(draft.status_code, 200, draft.text)
        codes = {row["code"] for row in draft.json()["capability_requirements"]}
        self.assertIn("C-ML-RESEARCH", codes)
        self.assertIn("C-PYTHON", codes)

        project_id = self.client.get("/api/project-matching/projects", headers=self.student_headers).json()[0]["id"]
        denied = self.client.get(f"/api/project-matching/projects/{project_id}/matches", headers=self.student_headers)
        self.assertEqual(denied.status_code, 403, denied.text)


if __name__ == "__main__":
    unittest.main()
