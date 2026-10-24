from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp(prefix="enertri_worker_health_"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_ROOT / 'test.db'}",
        "MEDIA_DIR": str(_ROOT / "media"),
        "FILE_STORE_DIR": str(_ROOT / "media" / "files"),
        "SECRET_KEY": "worker-health-test-secret-32-bytes-minimum",
        "APP_BOOTSTRAP_ON_STARTUP": "true",
        "TASK_EXECUTION_MODE": "database_worker",
        "HEALTH_MIN_FREE_BYTES": "1",
    }
)

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.task_queue import touch_worker_heartbeat  # noqa: E402


class WorkerHealthTest(unittest.TestCase):
    def test_readiness_requires_and_reports_worker_heartbeat(self):
        with TestClient(app) as client:
            before = client.get("/api/ready")
            self.assertEqual(before.status_code, 503, before.text)
            self.assertTrue(touch_worker_heartbeat("health-test-worker"))
            after = client.get("/api/ready")
            self.assertEqual(after.status_code, 200, after.text)
            health = client.get("/api/health").json()
            self.assertTrue(health["dependencies"]["worker"]["ok"])
            self.assertTrue(health["dependencies"]["worker"]["workers"])


if __name__ == "__main__":
    unittest.main()
