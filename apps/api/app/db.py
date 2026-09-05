import json, os, sqlite3
from datetime import datetime, timezone
from .config import settings

DATABASE_URL = os.getenv('DATABASE_URL')

def conn():
    if DATABASE_URL:
        import psycopg
        return psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)
    c = sqlite3.connect(settings.database_path)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    ddl = '''CREATE TABLE IF NOT EXISTS executions (
        id SERIAL PRIMARY KEY,
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
        budget_tx TEXT,
        submit_tx TEXT,
        settle_tx TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS executions (
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
        budget_tx TEXT,
        submit_tx TEXT,
        settle_tx TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )'''
    with conn() as c:
        c.execute(ddl)
        if DATABASE_URL:
            for col in ('budget_tx','register_tx','fund_tx','submit_tx','settle_tx','create_tx'):
                c.execute(f'ALTER TABLE executions ADD COLUMN IF NOT EXISTS {col} TEXT')
        else:
            cols={r[1] for r in c.execute('PRAGMA table_info(executions)').fetchall()}
            if 'budget_tx' not in cols: c.execute('ALTER TABLE executions ADD COLUMN budget_tx TEXT')

def upsert(job_id, **fields):
    now = datetime.now(timezone.utc).isoformat()
    fields['updated_at'] = now
    with conn() as c:
        placeholder = '%s' if DATABASE_URL else '?'
        row = c.execute('SELECT job_id FROM executions WHERE job_id=' + placeholder, (str(job_id),)).fetchone()
        if row:
            sets=', '.join(f'{k}={placeholder}' for k in fields)
            c.execute(f'UPDATE executions SET {sets} WHERE job_id={placeholder}', (*fields.values(), str(job_id)))
        else:
            fields.setdefault('created_at', now); fields.setdefault('status', 'created')
            fields.setdefault('agent_registry', ''); fields.setdefault('agent_id', ''); fields.setdefault('client', '')
            cols=', '.join(fields); qs=', '.join(placeholder for _ in fields)
            c.execute(f'INSERT INTO executions ({cols},job_id) VALUES ({qs},{placeholder})', (*fields.values(), str(job_id)))

def get(job_id):
    with conn() as c:
        placeholder = '%s' if DATABASE_URL else '?'
        r=c.execute('SELECT * FROM executions WHERE job_id=' + placeholder, (str(job_id),)).fetchone()
        if not r: return None
        d=dict(r)
        if d.get('result_json'):
            try: d['result']=json.loads(d['result_json'])
            except Exception: d['result']=d['result_json']
        return d
