"""Small persistent queue; a new SQLite connection per operation/thread."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self.database = data_dir / 'invoices.sqlite3'
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL, document TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, document: dict[str, Any]):
        with self.connect() as db:
            db.execute('INSERT INTO invoices VALUES (?, ?, ?, ?)', (document['id'], document['created_at'], document['status'], json.dumps(document, ensure_ascii=False)))

    def get(self, invoice_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute('SELECT document FROM invoices WHERE id=?', (invoice_id,)).fetchone()
        return json.loads(row['document']) if row else None

    def list(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute('SELECT document FROM invoices ORDER BY created_at DESC').fetchall()
        return [json.loads(row['document']) for row in rows]

    def update(self, invoice_id: str, changes: dict, expected_statuses: tuple[str, ...] | None = None) -> dict | None:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT document FROM invoices WHERE id=?', (invoice_id,)).fetchone()
            if not row:
                return None
            document = json.loads(row['document'])
            if expected_statuses and document['status'] not in expected_statuses:
                return None
            document.update(changes)
            document['updated_at'] = now()
            db.execute('UPDATE invoices SET status=?, document=? WHERE id=?', (document['status'], json.dumps(document, ensure_ascii=False), invoice_id))
        return document

    def claim_next(self) -> dict | None:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT document FROM invoices WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            document = json.loads(row['document'])
            document.update(status='processing', updated_at=now(), error=None)
            db.execute('UPDATE invoices SET status=?, document=? WHERE id=?', ('processing', json.dumps(document, ensure_ascii=False), document['id']))
        return document

    def recover(self):
        for doc in self.list():
            if doc['status'] == 'processing':
                self.update(doc['id'], {'status': 'failed', 'error': {'code': 'interrupted', 'message': 'توقفت المعالجة عند إعادة تشغيل التطبيق. يمكنك إعادة المحاولة.', 'stage': doc['stage']}})
