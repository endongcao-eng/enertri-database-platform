"""Web deployment regression tests; run in a separate process from legacy suites."""
import os
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
ROOT = tempfile.TemporaryDirectory()
os.environ.update(DATABASE_URL="sqlite:///"+str(Path(ROOT.name)/"test.db"), MEDIA_DIR=str(Path(ROOT.name)/"media"), SECRET_KEY="isolated-test-secret", APP_ENV="development", APP_BOOTSTRAP_ON_STARTUP="true", TASK_EXECUTION_MODE="inline")
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, MEDIA_DIR
from app.models import Term
from app.quiz_store import save_quiz, consume_quiz
from app.production import validate_production


class WebTrialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx=TestClient(app);cls.client=cls.ctx.__enter__()
        with SessionLocal.begin() as db:
            term=Term(zh="测试",en="Test",definition_zh_academic="测试",review_status="approved")
            db.add(term);db.flush();cls.term=term.id

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None,None,None)

    def test_private_media_cannot_bypass_auth(self):
        for folder in ("files", "artifacts", "workspace"):
            d=MEDIA_DIR/folder; d.mkdir(exist_ok=True);(d/"secret.txt").write_text("private")
            self.assertEqual(self.client.get(f"/media/{folder}/secret.txt").status_code,404)
        (MEDIA_DIR/"videos"/"test.txt").write_text("public")
        self.assertEqual(self.client.get("/media/videos/test.txt").status_code,200)

    def test_quiz_shared_between_processes_and_one_use(self):
        save_quiz("cross-process", self.term, {"q": {"answer":"A"}})
        code=f"from app.quiz_store import consume_quiz; assert consume_quiz('cross-process',{self.term})['q']['answer']=='A'"
        subprocess.run([sys.executable,"-c",code],check=True,env=os.environ.copy())
        self.assertIsNone(consume_quiz("cross-process",self.term))

    def test_quiz_expiration_and_wrong_term(self):
        save_quiz("expired",self.term,{},ttl=-1)
        self.assertIsNone(consume_quiz("expired",self.term))
        save_quiz("bound",self.term,{"q":1})
        self.assertIsNone(consume_quiz("bound",self.term+1))
        self.assertEqual(consume_quiz("bound",self.term),{"q":1})

    def test_readiness_and_no_filesystem_disclosure(self):
        self.assertEqual(self.client.get("/api/ready").status_code,200)
        self.assertNotIn("media_dir",self.client.get("/api/health").json())
        with patch("app.migration_bootstrap.current_revision", return_value="old"):
            self.assertEqual(self.client.get("/api/ready").status_code,503)

    def test_unsafe_production_refused(self):
        with patch.dict(os.environ, {"APP_ENV":"production","SECRET_KEY":"dev-secret-change-me"}):
            with self.assertRaises(RuntimeError): validate_production()

    def test_safe_production_config_accepted(self):
        with patch.dict(os.environ, {"APP_ENV":"production","SECRET_KEY":"a"*64,"DATABASE_URL":"postgresql+psycopg://u:p@db/app","TASK_EXECUTION_MODE":"database_worker","APP_BOOTSTRAP_ON_STARTUP":"false"}):
            validate_production()
