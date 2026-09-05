import json, sqlite3
from datetime import datetime, timezone
from .config import settings

def conn():
    c = sqlite3.connect(settings.database_path)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE NOT NULL,
            agent_registry TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            client TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            create_tx TEXT,
            register_tx TEXT,
            fund_tx TEXT,
            submit_tx TEXT,
            settle_tx TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )''')

def upsert(job_id, **fields):
    now = datetime.now(timezone.utc).isoformat()
    fields['updated_at'] = now
    with conn() as c:
        row = c.execute('SELECT job_id FROM executions WHERE job_id=?', (str(job_id),)).fetchone()
        if row:
            sets=', '.join(f'{k}=?' for k in fields)
            c.execute(f'UPDATE executions SET {sets} WHERE job_id=?', (*fields.values(), str(job_id)))
        else:
            fields.setdefault('created_at', now)
            fields.setdefault('status', 'created')
            fields.setdefault('agent_registry', '')
            fields.setdefault('agent_id', '')
            fields.setdefault('client', '')
            cols=', '.join(fields)
            qs=', '.join('?' for _ in fields)
            c.execute(f'INSERT INTO executions ({cols},job_id) VALUES ({qs},?)', (*fields.values(), str(job_id)))

def get(job_id):
    with conn() as c:
        r=c.execute('SELECT * FROM executions WHERE job_id=?',(str(job_id),)).fetchone()
        return dict(r) if r else None
