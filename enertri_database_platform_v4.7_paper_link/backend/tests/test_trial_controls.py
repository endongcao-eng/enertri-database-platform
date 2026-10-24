import os,tempfile,unittest,json,sys,subprocess,re
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
TMP=tempfile.TemporaryDirectory();root=Path(TMP.name)
os.environ.update(DATABASE_URL='sqlite:///'+str(root/'db.sqlite'),MEDIA_DIR=str(root/'media'),SECRET_KEY='test-controls-secret-which-is-long-enough',APP_ENV='development',APP_BOOTSTRAP_ON_STARTUP='true',TASK_EXECUTION_MODE='database_worker')
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import delete,update
from app.main import app
from app.database import SessionLocal
from app.models import User,WorkspaceTask,RateBucket,AIBudgetReservation,KnowledgeBase,KnowledgeDocument
from app.security import hash_password,create_access_token
from app.controls import rate_limit,reserve_ai,finish_ai
from app.task_service import create_task
from app.task_queue import claim_next_task
from app.ai_service import AIService,AIFile,AIUnavailableError

class TrialControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx=TestClient(app);cls.c=cls.ctx.__enter__();cls.ids={}
        with SessionLocal.begin() as db:
            for name,role in [('alice','learning_user'),('bob','learning_user'),('research','researcher'),('review','review_expert'),('operator','admin')]:
                u=User(username=name,display_name=name,role=role,password_hash=hash_password('OriginalPassword-12345'));db.add(u);db.flush();cls.ids[name]=u.id
    @classmethod
    def tearDownClass(cls):cls.ctx.__exit__(None,None,None)
    def h(self,name):
        with SessionLocal() as db:
            u=db.get(User,self.ids[name]);return {'Authorization':'Bearer '+create_access_token(u.username,u.role,token_version=u.token_version)}
    def setUp(self):
        with SessionLocal.begin() as db:db.execute(delete(RateBucket));db.execute(delete(AIBudgetReservation))
    def test_login_limit(self):
        with patch.dict(os.environ,LOGIN_ACCOUNT_LIMIT='2',LOGIN_IP_LIMIT='100'):
            for i in range(2):self.assertEqual(self.c.post('/api/auth/login',json={'username':'nonexistent','password':'x'},headers={'X-Forwarded-For':str(i)}).status_code,401)
            r=self.c.post('/api/auth/login',json={'username':'nonexistent','password':'x'});self.assertEqual(r.status_code,429);self.assertIn('retry-after',r.headers)
    def test_rate_limit_shared_atomic_across_processes(self):
        code="from app.controls import rate_limit;from fastapi import HTTPException\ntry:rate_limit(['shared'],[3],900)\nexcept HTTPException:raise SystemExit(42)"
        with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:subprocess.run([sys.executable,'-c',code],env=os.environ.copy(),capture_output=True).returncode,range(8)))
        self.assertEqual(results.count(0),3,results);self.assertEqual(results.count(42),5,results)
    def test_forced_change_revokes_old_tokens(self):
        with SessionLocal.begin() as db:db.execute(update(User).where(User.id==self.ids['alice']).values(must_change_password=True))
        old=self.h('alice');self.assertEqual(self.c.get('/api/research-profile/profile',headers=old).status_code,403)
        r=self.c.post('/api/auth/password',headers=old,json={'current_password':'OriginalPassword-12345','new_password':'NewPersonalPassword-67890'});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.c.get('/api/auth/me',headers=old).status_code,401)
        r=self.c.post('/api/auth/login',json={'username':'alice','password':'NewPersonalPassword-67890'});self.assertEqual(r.status_code,200);self.assertFalse(r.json()['user']['must_change_password'])
    def test_wrong_current_password(self):
        r=self.c.post('/api/auth/password',headers=self.h('bob'),json={'current_password':'wrong','new_password':'NewPersonalPassword-67890'});self.assertEqual(r.status_code,400)
    def test_logout_revokes_all_sessions(self):
        old=self.h('bob');self.assertEqual(self.c.post('/api/auth/logout',headers=old).status_code,200);self.assertEqual(self.c.get('/api/auth/me',headers=old).status_code,401)
    def test_task_admission_and_worker_limit(self):
        with SessionLocal.begin() as db:db.execute(delete(WorkspaceTask))
        with patch.dict(os.environ,TASK_USER_ACTIVE_LIMIT='2',TASK_GLOBAL_ACTIVE_LIMIT='3',TASK_GLOBAL_RUNNING_LIMIT='1',TASK_USER_RUNNING_LIMIT='1'):
            with SessionLocal() as db:
                for _ in range(2):create_task(db,user_id=self.ids['alice'],task_type='ppt_generation',title='quota-test',input_data={})
                with self.assertRaises(HTTPException):create_task(db,user_id=self.ids['alice'],task_type='ppt_generation',title='excess',input_data={})
                create_task(db,user_id=self.ids['bob'],task_type='ppt_generation',title='quota-test',input_data={})
                with self.assertRaises(HTTPException):create_task(db,user_id=self.ids['bob'],task_type='ppt_generation',title='excess',input_data={})
            self.assertIsNotNone(claim_next_task('worker-a'));self.assertIsNone(claim_next_task('worker-b'))
    def test_ai_failure_not_refunded(self):
        with patch.dict(os.environ,AI_REQUEST_RESERVATION_USD='0.10',AI_USER_DAILY_USD='0.20',AI_GLOBAL_DAILY_USD='0.20'):
            rid=reserve_ai(self.ids['research'])
            with self.assertRaises(HTTPException):reserve_ai(self.ids['research'])
            finish_ai(rid,failed=True);rid=reserve_ai(self.ids['research']);finish_ai(rid)
            with self.assertRaises(HTTPException):reserve_ai(self.ids['research'])
    def test_ai_owner_files_input_bounds(self):
        with patch.dict(os.environ,OPENAI_API_KEY='test',AI_BUDGET_ENABLED='true',AI_BUDGET_MODEL='test',OPENAI_MODEL='test',AI_INPUT_USD_PER_MILLION='1',AI_OUTPUT_USD_PER_MILLION='1'):
            service=AIService()
            with patch.object(service,'_unmetered_generate_text',return_value=('answer',{'input_tokens':10})) as upstream:
                with self.assertRaises(HTTPException):service.generate_text('hello',user_id=self.ids['bob'])
                with self.assertRaises(AIUnavailableError):service.generate_text('hello',user_id=self.ids['research'],files=[AIFile('file.txt',b'private')])
                with self.assertRaises(AIUnavailableError):service.generate_text('x'*20000,user_id=self.ids['research'])
                upstream.assert_not_called();self.assertEqual(service.generate_text('hello',user_id=self.ids['research']),'answer');upstream.assert_called_once()
    def test_all_protected_routes_anonymous(self):
        def deps(d):return [getattr(d.call,'__name__','')]+[n for child in d.dependencies for n in deps(child)]
        inventory=[]
        for route in app.routes:
            if not hasattr(route,'dependant'):continue
            protected='current_user' in deps(route.dependant)
            for method in sorted(route.methods):
                row={'path':route.path,'method':method,'authentication':protected}
                if protected:
                    r=self.c.request(method,re.sub(r'\{[^}]+\}','1',route.path));row['anonymous_status']=r.status_code;self.assertIn(r.status_code,[401,403],row)
                inventory.append(row)
        if os.getenv('PERMISSION_INVENTORY_PATH'):Path(os.environ['PERMISSION_INVENTORY_PATH']).write_text(json.dumps(inventory,ensure_ascii=False,indent=2))
    def test_owner_role_matrix(self):
        h=self.h('bob');r=self.c.post('/api/files/upload',headers=h,files={'file':('owned.txt',b'private sample','text/plain')});self.assertEqual(r.status_code,200,r.text);fid=r.json()['id']
        r=self.c.post('/api/development-planning/goals',headers=h,json={'goal_type':'student_growth','title':'Private Goal'});self.assertEqual(r.status_code,200,r.text);gid=r.json()['id']
        with SessionLocal.begin() as db:
            kb=KnowledgeBase(name='private',scope_type='personal',owner_user_id=self.ids['bob'],allow_team_search=False);db.add(kb);db.flush()
            doc=KnowledgeDocument(knowledge_base_id=kb.id,owner_user_id=self.ids['bob'],title='private doc',source_type='upload',status='ready');db.add(doc);db.flush();did=doc.id
        for role in ['alice','research','review','operator','bob']:
            headers=self.h(role);allowed=role in ['bob','operator']
            r=self.c.get(f"/api/research-profile/profile?user_id={self.ids['bob']}",headers=headers);self.assertEqual(r.status_code,200 if allowed else 403,(role,r.text))
            r=self.c.get(f'/api/files/{fid}/download',headers=headers);self.assertIn(r.status_code,[200] if allowed else [403,404],(role,r.text))
            r=self.c.get(f'/api/development-planning/goals/{gid}/analysis',headers=headers);self.assertEqual(r.status_code,200 if allowed else 403,(role,r.text))
            r=self.c.get(f'/api/knowledge/documents/{did}',headers=headers);self.assertEqual(r.status_code,200 if role=='bob' else 404,(role,r.text))
