"""V4.4 Stage 2 evidence-backed research profile acceptance tests."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory(prefix="enertri_v44_profile_")
_ROOT = Path(_TEST_ROOT.name)
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
    "MEDIA_DIR": str(_ROOT / "media"),
    "ARTIFACT_DIR": str(_ROOT / "artifacts"),
    "WORKSPACE_DIR": str(_ROOT / "workspace"),
    "SECRET_KEY": "test-v44-secret",
    "APP_BOOTSTRAP_ON_STARTUP": "true",
    "TASK_EXECUTION_MODE": "inline",
})

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


class ResearchProfileStage2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        student = cls.client.post("/api/auth/login", json={"username": "student", "password": "123456"})
        admin = cls.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        cls.student_user = student.json()["user"]
        cls.admin_user = admin.json()["user"]
        cls.student_headers = {"Authorization": f"Bearer {student.json()['access_token']}"}
        cls.admin_headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        _TEST_ROOT.cleanup()

    def test_seeded_profile_has_traceable_knowledge_and_capability(self):
        response = self.client.get("/api/research-profile/profile", headers=self.student_headers)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["stage"], "V4.4 Stage 2")
        self.assertGreaterEqual(body["summary"]["evidence_count"], 5)
        self.assertGreaterEqual(body["summary"]["verified_evidence_count"], 3)
        self.assertGreater(body["summary"]["evidence_confidence"], 50)

        knowledge = {row["name_zh"]: row for row in body["knowledge"]}
        self.assertIn("微纳尺度传热", knowledge)
        self.assertGreater(knowledge["微纳尺度传热"]["score"], 60)
        self.assertTrue(knowledge["微纳尺度传热"]["trace"])

        capabilities = {row["name_zh"]: row for row in body["capabilities"]}
        self.assertIn("Python 科研计算", capabilities)
        python_cap = capabilities["Python 科研计算"]
        self.assertGreater(python_cap["score"], 45)
        self.assertGreater(python_cap["direct_evidence_score"], 0)
        self.assertTrue(python_cap["trace"])
        self.assertIn("知识准备度", body["scoring_model"]["capability"])

    def test_student_cannot_inspect_other_users_but_admin_can(self):
        denied = self.client.get(
            f"/api/research-profile/profile?user_id={self.admin_user['id']}",
            headers=self.student_headers,
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        allowed = self.client.get(
            f"/api/research-profile/profile?user_id={self.student_user['id']}",
            headers=self.admin_headers,
        )
        self.assertEqual(allowed.status_code, 200, allowed.text)

    def test_new_evidence_enters_pending_and_teacher_can_verify(self):
        resources = self.client.get("/api/capability-standards/resources", headers=self.student_headers).json()
        book = next(row for row in resources if row["code"] == "R-BOOK-MICRO")
        created = self.client.post(
            "/api/research-profile/evidence",
            headers=self.student_headers,
            json={
                "resource_id": book["id"],
                "evidence_type": "book_reading",
                "title": "补充阅读与习题记录",
                "completion_ratio": 0.92,
                "quality_rating": 4.4,
                "verification_status": "pending",
                "notes": "补充阅读并完成部分习题。",
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        evidence = created.json()
        self.assertEqual(evidence["verification_status"], "pending")

        verified = self.client.patch(
            f"/api/research-profile/evidence/{evidence['id']}/verify",
            headers=self.admin_headers,
            json={
                "verification_status": "verified",
                "quality_rating": 4.5,
                "verification_note": "读书笔记与习题记录已核验。",
            },
        )
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertEqual(verified.json()["verification_status"], "verified")
        self.assertEqual(verified.json()["verifier_name"], self.admin_user["display_name"])


if __name__ == "__main__":
    unittest.main()
