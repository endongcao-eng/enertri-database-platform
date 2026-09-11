import hashlib
import json
import time
from sqlalchemy import delete
from .database import SessionLocal
from .models import QuizSession


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def save_quiz(token, term_id, answers, ttl=1800):
    now = int(time.time())
    with SessionLocal.begin() as db:
        db.execute(delete(QuizSession).where(QuizSession.expires_at < now))
        db.add(QuizSession(token_hash=_digest(token), term_id=term_id,
                           answers_json=json.dumps(answers), expires_at=now + ttl))


def consume_quiz(token, term_id):
    with SessionLocal.begin() as db:
        # Atomic DELETE RETURNING prevents replay across API processes.
        row = db.execute(delete(QuizSession).where(
            QuizSession.token_hash == _digest(token),
            QuizSession.term_id == term_id,
            QuizSession.expires_at > int(time.time()),
        ).returning(QuizSession.answers_json)).first()
        return json.loads(row[0]) if row else None
