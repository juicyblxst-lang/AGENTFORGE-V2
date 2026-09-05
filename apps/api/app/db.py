import json, os, sqlite3
from datetime import datetime, timezone, timedelta
from .config import settings

DATABASE_URL = os.getenv('DATABASE_URL')

def conn():
    if DATABASE_URL:
        import psycopg
        return psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row)
    c=sqlite3.connect(settings.database_path, timeout=15); c.row_factory=sqlite3.Row; return c

def init_db():
    ddl='''CREATE TABLE IF NOT EXISTS executions (id SERIAL PRIMARY KEY, job_id TEXT UNIQUE NOT NULL, agent_registry TEXT NOT NULL, agent_id TEXT NOT NULL, client TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT, error TEXT, create_tx TEXT, register_tx TEXT, budget_tx TEXT, approval_tx TEXT, fund_tx TEXT, submit_tx TEXT, settle_tx TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''' if DATABASE_URL else '''CREATE TABLE IF NOT EXISTS executions (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT UNIQUE NOT NULL, agent_registry TEXT NOT NULL, agent_id TEXT NOT NULL, client TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT, error TEXT, create_tx TEXT, register_tx TEXT, fund_tx TEXT, budget_tx TEXT, approval_tx TEXT, submit_tx TEXT, settle_tx TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)'''
    with conn() as c:
        c.execute(ddl)
        cols_needed=('budget_tx','register_tx','approval_tx','fund_tx','submit_tx','settle_tx','create_tx')
        if DATABASE_URL:
            for col in cols_needed: c.execute(f'ALTER TABLE executions ADD COLUMN IF NOT EXISTS {col} TEXT')
        else:
            cols={r[1] for r in c.execute('PRAGMA table_info(executions)').fetchall()}
            for col in cols_needed:
                if col not in cols: c.execute(f'ALTER TABLE executions ADD COLUMN {col} TEXT')

def upsert(job_id,**fields):
    now=datetime.now(timezone.utc).isoformat(); fields['updated_at']=now
    with conn() as c:
        p='%s' if DATABASE_URL else '?'; row=c.execute('SELECT job_id FROM executions WHERE job_id='+p,(str(job_id),)).fetchone()
        if row:
            sets=', '.join(f'{k}={p}' for k in fields); c.execute(f'UPDATE executions SET {sets} WHERE job_id={p}',(*fields.values(),str(job_id)))
        else:
            fields.setdefault('created_at',now); fields.setdefault('status','created'); fields.setdefault('agent_registry',''); fields.setdefault('agent_id',''); fields.setdefault('client','')
            cols=', '.join(fields); qs=', '.join(p for _ in fields); c.execute(f'INSERT INTO executions ({cols},job_id) VALUES ({qs},{p})',(*fields.values(),str(job_id)))

def get(job_id):
    with conn() as c:
        p='%s' if DATABASE_URL else '?'; r=c.execute('SELECT * FROM executions WHERE job_id='+p,(str(job_id),)).fetchone()
        if not r:return None
        d=dict(r)
        if d.get('result_json'):
            try:d['result']=json.loads(d['result_json'])
            except Exception:d['result']=d['result_json']
        return d

def claim_execution(job_id, stale_after_seconds=600):
    now=datetime.now(timezone.utc); cutoff=(now-timedelta(seconds=stale_after_seconds)).isoformat()
    with conn() as c:
        p='%s' if DATABASE_URL else '?'
        if DATABASE_URL:
            cur=c.execute(f"UPDATE executions SET status='executing',updated_at={p},error=NULL WHERE job_id={p} AND (status NOT IN ('executing','submitted','completed') OR (status='executing' AND updated_at < {p}))",(now.isoformat(),str(job_id),cutoff))
        else:
            cur=c.execute(f"UPDATE executions SET status='executing',updated_at=?,error=NULL WHERE job_id=? AND (status NOT IN ('executing','submitted','completed') OR (status='executing' AND updated_at < ?))",(now.isoformat(),str(job_id),cutoff))
        return cur.rowcount==1
