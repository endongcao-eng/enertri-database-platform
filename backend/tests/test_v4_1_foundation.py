from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_TEST_ROOT = tempfile.TemporaryDirectory(prefix="enertri_v41_")
_ROOT = Path(_TEST_ROOT.name)
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
    "MEDIA_DIR": str(_ROOT / "media"),
    "ARTIFACT_DIR": str(_ROOT / "media" / "artifacts"),
    "WORKSPACE_DIR": str(_ROOT / "media" / "workspace"),
    "FILE_STORE_DIR": str(_ROOT / "media" / "files"),
    "SECRET_KEY": "test-v41",
    "OPENAI_API_KEY": "",
    "TASK_STEP_DELAY_SECONDS": "0.01",
    "APP_BOOTSTRAP_ON_STARTUP": "true",
    "TASK_EXECUTION_MODE": "inline",
    "TEMP_FILE_RETENTION_HOURS": "1",
})

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import User, WorkspaceFile, WorkspaceTask  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.task_queue import claim_next_task, recover_expired_tasks  # noqa: E402
from app.task_service import create_task  # noqa: E402


def _demo_pdf_bytes() -> bytes:
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 60), "Laser Welding Parameter Optimization and Porosity Control", fontsize=16)
    lines = [
        "Abstract",
        "This study investigates laser welding of structural steel and establishes evidence-linked processing parameters for quality control.",
        "Introduction",
        "Laser welding quality depends on heat input, shielding and keyhole stability.",
        "Materials and Methods",
        "The base material was Q355 steel with a thickness of 3 mm.",
        "The laser power was 2.4 kW and travel speed was 12 mm/s.",
        "Table 1 Welding parameters",
    ]
    y = 100
    for line in lines:
        page.insert_text((60, y), line, fontsize=10); y += 24
    x0, y0, colw, rowh = 60, 320, 140, 28
    table = [["Group", "Laser power", "Speed"], ["A", "2.0 kW", "10 mm/s"], ["B", "2.4 kW", "12 mm/s"], ["C", "2.8 kW", "14 mm/s"]]
    for r in range(len(table)+1):
        page.draw_line((x0, y0+r*rowh), (x0+3*colw, y0+r*rowh))
    for c in range(4):
        page.draw_line((x0+c*colw, y0), (x0+c*colw, y0+len(table)*rowh))
    for r,row in enumerate(table):
        for c,cell in enumerate(row):
            page.insert_text((x0+c*colw+5, y0+r*rowh+18), cell, fontsize=9)

    page2 = doc.new_page(width=595, height=842)
    page2_lines = [
        "Results",
        "The highest tensile strength was 612 MPa for parameter group B.",
        "Discussion",
        "Porosity formed because shielding gas was trapped during unstable keyhole collapse; stable keyhole behavior reduced pores.",
        "Conclusions",
        "A laser power of 2.4 kW produced the best combined mechanical performance in this experiment.",
        "References",
        "[1] Zhang et al. Laser welding process monitoring. 2024.",
        "[2] Wang et al. Keyhole stability and pore formation. 2023.",
    ]
    y = 70
    for line in page2_lines:
        page2.insert_text((60, y), line, fontsize=10); y += 30
    data = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return data


class V41FoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        with SessionLocal() as db:
            if not db.query(User).filter(User.username == "system_root").first():
                db.add(User(username="system_root", password_hash=hash_password("root123456"), role="system_admin", display_name="系统管理员"))
            if not db.query(User).filter(User.username == "reviewer").first():
                db.add(User(username="reviewer", password_hash=hash_password("review123456"), role="review_expert", display_name="审稿专家"))
            db.commit()
        student = cls.client.post("/api/auth/login", json={"username": "student", "password": "123456"}).json()
        admin = cls.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"}).json()
        system_root = cls.client.post("/api/auth/login", json={"username": "system_root", "password": "root123456"}).json()
        reviewer = cls.client.post("/api/auth/login", json={"username": "reviewer", "password": "review123456"}).json()
        cls.student_headers = {"Authorization": f"Bearer {student['access_token']}"}
        cls.admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
        cls.system_headers = {"Authorization": f"Bearer {system_root['access_token']}"}
        cls.reviewer_headers = {"Authorization": f"Bearer {reviewer['access_token']}"}

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        _TEST_ROOT.cleanup()

    def wait_task(self, task_id: int, timeout: float = 8.0, headers=None):
        deadline = time.time() + timeout
        seen = []
        while time.time() < deadline:
            response = self.client.get(f"/api/tasks/{task_id}", headers=headers or self.student_headers)
            self.assertEqual(response.status_code, 200, response.text)
            task = response.json()
            seen.append((task["status"], task["progress"]))
            if task["status"] in {"succeeded", "failed", "cancelled"}:
                return task, seen
            time.sleep(0.03)
        self.fail(f"task {task_id} timeout: {seen}")

    def test_v42_paper_knowledge_pipeline_and_qa(self):
        bases = self.client.get("/api/knowledge/bases", headers=self.student_headers)
        self.assertEqual(bases.status_code, 200, bases.text)
        personal = next(row for row in bases.json() if row["scope_type"] == "personal")
        uploaded = self.client.post(
            "/api/knowledge/documents/upload", headers=self.student_headers,
            files={"file": ("laser-welding-demo.pdf", _demo_pdf_bytes(), "application/pdf")},
            data={"knowledge_base_id": str(personal["id"]), "confidentiality": "internal", "allow_external_ai": "false"},
        )
        self.assertEqual(uploaded.status_code, 202, uploaded.text)
        completed, _ = self.wait_task(uploaded.json()["id"], timeout=20.0)
        self.assertEqual(completed["status"], "succeeded", completed)
        document_id = uploaded.json()["document_id"]
        detail = self.client.get(f"/api/knowledge/documents/{document_id}", headers=self.student_headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        doc = detail.json()
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(doc["page_count"], 2)
        self.assertGreaterEqual(len(doc["pages"]), 2)
        self.assertGreaterEqual(len(doc["tables"]), 1, doc)
        facts = doc["structure"].get("key_facts") or []
        self.assertTrue(any(f["type"] == "laser_power" and f["value"] == "2.4" for f in facts), facts)
        self.assertTrue(any(f["type"] == "tensile_strength" and f["value"] == "612" for f in facts), facts)

        qa = self.client.post(
            f"/api/knowledge/documents/{document_id}/qa", headers=self.student_headers,
            json={"question": "激光功率是多少？"},
        )
        self.assertEqual(qa.status_code, 200, qa.text)
        answer = qa.json()
        self.assertIn("2.4", answer["answer"])
        self.assertTrue(answer["evidence"])
        self.assertEqual(answer["evidence"][0]["page"], 1)
        self.assertEqual(answer["evidence"][0]["section"], "Materials and Methods")
        self.assertIn("#page=1", answer["evidence"][0]["page_url"])

        tensile = self.client.post(
            f"/api/knowledge/documents/{document_id}/qa", headers=self.student_headers,
            json={"question": "最高抗拉强度对应哪组参数？"},
        )
        self.assertEqual(tensile.status_code, 200, tensile.text)
        self.assertIn("612", tensile.json()["answer"])
        self.assertIn("B", tensile.json()["answer"])
        self.assertEqual(tensile.json()["evidence"][0]["section"], "Results")

        material = self.client.post(
            f"/api/knowledge/documents/{document_id}/qa", headers=self.student_headers,
            json={"question": "这篇论文使用了什么母材？"},
        )
        self.assertEqual(material.status_code, 200, material.text)
        self.assertIn("Q355", material.json()["answer"])
        self.assertEqual(material.json()["evidence"][0]["section"], "Materials and Methods")

        qa2 = self.client.post(
            f"/api/knowledge/documents/{document_id}/qa", headers=self.student_headers,
            json={"question": "作者如何解释气孔形成？"},
        )
        self.assertEqual(qa2.status_code, 200, qa2.text)
        self.assertIn("trapped", qa2.json()["answer"].lower())
        self.assertTrue(any(e["page"] == 2 for e in qa2.json()["evidence"]))
        self.assertEqual(qa2.json()["evidence"][0]["section"], "Discussion")


    def test_v42_blocker_permissions_and_system_admin_protection(self):
        users = self.client.get("/api/admin/users", headers=self.admin_headers).json()
        root = next(row for row in users if row["username"] == "system_root")
        ordinary_admin_attempt = self.client.patch(
            f"/api/admin/users/{root['id']}/role",
            headers=self.admin_headers,
            json={"role": "admin", "is_active": False, "confirmation": "system_root"},
        )
        self.assertEqual(ordinary_admin_attempt.status_code, 403, ordinary_admin_attempt.text)

        last_root_attempt = self.client.patch(
            f"/api/admin/users/{root['id']}/role",
            headers=self.system_headers,
            json={"role": "admin", "is_active": True, "confirmation": "system_root"},
        )
        self.assertEqual(last_root_attempt.status_code, 409, last_root_attempt.text)
        self.assertIn("最后一个", last_root_attempt.json()["detail"])

        missing_confirmation = self.client.patch(
            f"/api/admin/users/{root['id']}/role",
            headers=self.system_headers,
            json={"role": "system_admin", "is_active": True},
        )
        self.assertEqual(missing_confirmation.status_code, 409, missing_confirmation.text)

        admin_task = self.client.post(
            "/api/tasks/ppt-generation", headers=self.admin_headers,
            json={"title": "权限隔离任务", "source_text": "# 权限测试\n- reviewer 只能查看", "use_external_ai": False},
        )
        self.assertEqual(admin_task.status_code, 202, admin_task.text)
        task_id = admin_task.json()["id"]
        viewed = self.client.get(f"/api/tasks/{task_id}", headers=self.reviewer_headers)
        self.assertEqual(viewed.status_code, 200, viewed.text)
        retried = self.client.post(f"/api/tasks/{task_id}/retry", headers=self.reviewer_headers)
        self.assertEqual(retried.status_code, 403, retried.text)
        cancelled = self.client.post(f"/api/tasks/{task_id}/cancel", headers=self.reviewer_headers)
        self.assertEqual(cancelled.status_code, 403, cancelled.text)

        admin_file = self.client.post(
            "/api/files/upload", headers=self.admin_headers,
            files={"file": ("admin-note.txt", b"administrator owned file", "text/plain")},
            data={"confidentiality": "internal", "allow_external_ai": "false"},
        )
        self.assertEqual(admin_file.status_code, 200, admin_file.text)
        visible = self.client.get("/api/files?scope=all", headers=self.reviewer_headers)
        self.assertEqual(visible.status_code, 200, visible.text)
        self.assertTrue(any(row["id"] == admin_file.json()["id"] for row in visible.json()))
        denied_download = self.client.get(f"/api/files/{admin_file.json()['id']}/download", headers=self.reviewer_headers)
        self.assertEqual(denied_download.status_code, 404, denied_download.text)

        student_export = self.client.get("/api/data/export", headers=self.student_headers)
        self.assertEqual(student_export.status_code, 403, student_export.text)

    def test_v42_blocker_file_content_validation(self):
        bad_pdf = self.client.post(
            "/api/tasks/paper-analysis", headers=self.student_headers,
            files={"file": ("forged.pdf", b"this is not a pdf", "application/pdf")},
            data={"focus": "", "confidentiality": "internal", "allow_external_ai": "false"},
        )
        self.assertEqual(bad_pdf.status_code, 202, bad_pdf.text)
        body = bad_pdf.json()
        self.assertEqual(body["status"], "failed")
        self.assertIn("校验", body["current_step"])
        failed_files = self.client.get("/api/files?parse_status=failed", headers=self.student_headers).json()
        forged = next(row for row in failed_files if row["original_name"] == "forged.pdf")
        self.assertEqual(forged["parse_status"], "failed")
        self.assertFalse(forged["validation"]["valid"])
        self.assertEqual(self.client.get(f"/api/files/{forged['id']}/download", headers=self.student_headers).status_code, 404)

        direct_bad = self.client.post(
            "/api/files/upload", headers=self.student_headers,
            files={"file": ("image.png", b"not a png", "image/png")},
            data={"confidentiality": "internal", "allow_external_ai": "false"},
        )
        self.assertEqual(direct_bad.status_code, 400, direct_bad.text)
        self.assertEqual(direct_bad.json()["detail"]["parse_status"], "failed")

    def test_v42_database_worker_lease_recovery(self):
        with SessionLocal() as db:
            student = db.query(User).filter(User.username == "student").first()
            task = create_task(db, user_id=student.id, task_type="ppt_generation", title="DB worker claim", input_data={"title": "x", "source_text": "x"}, timeout_seconds=60)
            task_id = task.id
        claim = claim_next_task("worker-test-A")
        self.assertIsNotNone(claim)
        self.assertEqual(claim["id"], task_id)
        with SessionLocal() as db:
            claimed = db.get(WorkspaceTask, task_id)
            self.assertEqual(claimed.status, "running")
            self.assertEqual(claimed.worker_id, "worker-test-A")
            self.assertEqual(claimed.attempt_count, 1)
            claimed.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
            db.commit()
        self.assertEqual(recover_expired_tasks(), 0)
        with SessionLocal() as db:
            claimed = db.get(WorkspaceTask, task_id)
            self.assertEqual(claimed.status, "running")
            claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        self.assertEqual(recover_expired_tasks(), 1)
        with SessionLocal() as db:
            recovered = db.get(WorkspaceTask, task_id)
            self.assertEqual(recovered.status, "failed")
            self.assertEqual(recovered.current_step, "Worker 租约过期")
            self.assertIsNone(recovered.worker_id)


    def test_v41_acceptance_flow(self):
        permission = self.client.get("/api/auth/permissions", headers=self.student_headers)
        self.assertEqual(permission.status_code, 200)
        self.assertEqual(permission.json()["role"], "learning_user")

        paper = self.client.post(
            "/api/tasks/paper-analysis",
            headers=self.student_headers,
            files={"file": ("demo-paper.txt", b"Abstract\nMethods\nCurrent 220 A. Results stable. Conclusion.", "text/plain")},
            data={"focus": "methods", "confidentiality": "restricted", "allow_external_ai": "true"},
        )
        self.assertEqual(paper.status_code, 202, paper.text)
        paper_task, paper_seen = self.wait_task(paper.json()["id"])
        self.assertEqual(paper_task["status"], "succeeded")
        self.assertFalse(paper_task["result"]["external_ai_used"])
        self.assertGreaterEqual(len(paper_task["events"]), 5)
        self.assertTrue(any(progress > 0 for _, progress in paper_seen))

        ppt = self.client.post(
            "/api/tasks/ppt-generation",
            headers=self.student_headers,
            json={"title": "V4.1 验收汇报", "source_text": "# 背景\n- 工程基础升级\n# 成果\n- 任务中心\n- 文件管理\n- 审计日志", "use_external_ai": False},
        )
        self.assertEqual(ppt.status_code, 202, ppt.text)
        ppt_task, _ = self.wait_task(ppt.json()["id"])
        self.assertEqual(ppt_task["status"], "succeeded", ppt_task)
        download = self.client.get(ppt_task["result"]["download_url"], headers=self.student_headers)
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.content.startswith(b"PK"))

        video = self.client.post(
            "/api/tasks/video-analysis",
            headers=self.student_headers,
            files={"file": ("demo-video.mp4", b"not-a-real-video-but-valid-upload-flow", "video/mp4")},
            data={"focus": "process stability", "confidentiality": "restricted", "allow_external_ai": "true"},
        )
        self.assertEqual(video.status_code, 202, video.text)
        video_task, _ = self.wait_task(video.json()["id"], timeout=12.0)
        self.assertEqual(video_task["status"], "failed", video_task)
        self.assertIn("校验", video_task["current_step"])

        forbidden_simulation = self.client.post(
            "/api/tasks/simulation-package",
            headers=self.student_headers,
            json={"name": "权限验证", "software": "ansys_mapdl", "parameters": {"current_a": 180}},
        )
        self.assertEqual(forbidden_simulation.status_code, 403, forbidden_simulation.text)

        simulation = self.client.post(
            "/api/tasks/simulation-package",
            headers=self.admin_headers,
            json={
                "name": "V4.1 仿真验收",
                "software": "ansys_mapdl",
                "software_version": "2025 R1",
                "parameters": {"current_a": 220, "voltage_v": 24, "travel_speed_mm_s": 5, "mesh_size_mm": 2},
            },
        )
        self.assertEqual(simulation.status_code, 202, simulation.text)
        simulation_task, _ = self.wait_task(simulation.json()["id"], timeout=12.0, headers=self.admin_headers)
        self.assertEqual(simulation_task["status"], "succeeded", simulation_task)
        simulation_zip = self.client.get(simulation_task["result"]["download_url"], headers=self.admin_headers)
        self.assertEqual(simulation_zip.status_code, 200, simulation_zip.text)
        self.assertTrue(simulation_zip.content.startswith(b"PK"))

        files = self.client.get("/api/files", headers=self.student_headers).json()
        self.assertGreaterEqual(len(files), 2)
        restricted = next(item for item in files if item["original_name"] == "demo-paper.txt")
        self.assertEqual(restricted["confidentiality"], "restricted")
        self.assertFalse(restricted["external_ai_allowed"])
        self.assertEqual(len(restricted["sha256"]), 64)

        duplicate = self.client.post(
            "/api/files/upload",
            headers=self.student_headers,
            files={"file": ("copy.txt", b"Abstract\nMethods\nCurrent 220 A. Results stable. Conclusion.", "text/plain")},
            data={"confidentiality": "internal", "allow_external_ai": "false"},
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate_detected"])
        self.assertEqual(duplicate.json()["id"], restricted["id"])

        # A later restricted upload of identical bytes must tighten, never weaken, policy.
        first_admin_copy = self.client.post(
            "/api/files/upload",
            headers=self.admin_headers,
            files={"file": ("policy-first.txt", b"same bytes policy test", "text/plain")},
            data={"confidentiality": "internal", "allow_external_ai": "true"},
        )
        self.assertEqual(first_admin_copy.status_code, 200, first_admin_copy.text)
        self.assertTrue(first_admin_copy.json()["external_ai_allowed"])
        tightened_copy = self.client.post(
            "/api/files/upload",
            headers=self.admin_headers,
            files={"file": ("policy-restricted.txt", b"same bytes policy test", "text/plain")},
            data={"confidentiality": "restricted", "allow_external_ai": "true"},
        )
        self.assertEqual(tightened_copy.status_code, 200, tightened_copy.text)
        self.assertTrue(tightened_copy.json()["duplicate_detected"])
        self.assertEqual(tightened_copy.json()["id"], first_admin_copy.json()["id"])
        self.assertEqual(tightened_copy.json()["confidentiality"], "restricted")
        self.assertFalse(tightened_copy.json()["external_ai_allowed"])

        temporary = self.client.post(
            "/api/files/upload",
            headers=self.student_headers,
            files={"file": ("temporary.txt", b"temporary cleanup payload", "text/plain")},
            data={"confidentiality": "internal", "allow_external_ai": "false", "temporary": "true"},
        )
        self.assertEqual(temporary.status_code, 200, temporary.text)
        temporary_id = temporary.json()["id"]
        self.assertIsNotNone(temporary.json()["expires_at"])
        with SessionLocal() as db:
            row = db.get(WorkspaceFile, temporary_id)
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
        cleanup = self.client.post("/api/admin/files/cleanup", headers=self.admin_headers)
        self.assertEqual(cleanup.status_code, 200, cleanup.text)
        self.assertGreaterEqual(cleanup.json()["deleted_count"], 1)
        file_ids = {item["id"] for item in self.client.get("/api/files", headers=self.student_headers).json()}
        self.assertNotIn(temporary_id, file_ids)

        migration = self.client.get("/api/admin/migrations", headers=self.admin_headers)
        self.assertEqual(migration.status_code, 200)
        self.assertEqual(migration.json()["current_revision"], "v4_7_template_library")
        self.assertEqual(migration.json()["status"], "succeeded")

        users = self.client.get("/api/admin/users", headers=self.admin_headers)
        self.assertEqual(users.status_code, 200, users.text)
        student_row = next(row for row in users.json() if row["username"] == "student")
        promoted = self.client.patch(
            f"/api/admin/users/{student_row['id']}/role",
            headers=self.admin_headers,
            json={"role": "researcher", "is_active": True},
        )
        self.assertEqual(promoted.status_code, 200, promoted.text)
        self.assertEqual(promoted.json()["role"], "researcher")
        current_permissions = self.client.get("/api/auth/permissions", headers=self.student_headers).json()
        self.assertIn("ai.external", current_permissions["permissions"])
        forbidden_grant = self.client.patch(
            f"/api/admin/users/{student_row['id']}/role",
            headers=self.admin_headers,
            json={"role": "system_admin", "is_active": True},
        )
        self.assertEqual(forbidden_grant.status_code, 403)
        restored = self.client.patch(
            f"/api/admin/users/{student_row['id']}/role",
            headers=self.admin_headers,
            json={"role": "learning_user", "is_active": True},
        )
        self.assertEqual(restored.status_code, 200, restored.text)

        logs = self.client.get("/api/admin/audit-logs", headers=self.admin_headers)
        self.assertEqual(logs.status_code, 200)
        actions = {row["action"] for row in logs.json()}
        self.assertIn("database.migration.completed", actions)
        self.assertIn("task.created", actions)
        self.assertIn("task.succeeded", actions)
        self.assertIn("file.downloaded", actions)
        self.assertIn("file.cleanup", actions)
        self.assertIn("user.role.updated", actions)


if __name__ == "__main__":
    unittest.main()
