import asyncio
import json
import logging
import re
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .config import settings, BSC_NETWORKS
from .db import init_db, upsert, get, list_all
from .discovery import discover, get_agent
from .chain_dynamic import read_job, verify_receipt
from .orchestrator import quote, worker, provider_ready

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
network = BSC_NETWORKS[settings.network]
app = FastAPI(title='AgentForge API', version='2.4.0')
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
worker_task = None

class Hire(BaseModel):
    agent_id: str
    agent_registry: str
    client: str
    description: str = Field(min_length=1, max_length=4000)

class TxRecord(BaseModel):
    agent_id: str | None = None
    agent_registry: str | None = None
    client: str | None = None
    description: str | None = None
    create_tx: str | None = None
    register_tx: str | None = None
    budget_tx: str | None = None
    approval_tx: str | None = None
    fund_tx: str | None = None
    submit_tx: str | None = None
    settle_tx: str | None = None

@app.on_event('startup')
async def startup():
    global worker_task
    init_db()
    worker_task = asyncio.create_task(worker())

@app.on_event('shutdown')
async def shutdown():
    if worker_task:
        worker_task.cancel()

@app.get('/health')
async def health():
    return {'ok': True, 'network': settings.network, 'chainId': network['chainId'], 'providerConfigured': provider_ready(), 'contracts': {'identityRegistry': network['identityRegistry'], 'commerce': network['commerce'], 'router': network['router'], 'policy': network['policy']}}

@app.get('/api/config')
async def config():
    return {**network, 'network': settings.network}

@app.get('/api/agents')
async def agents(limit: int = 100):
    try:
        return {'agents': await discover(limit)}
    except Exception as e:
        logger.exception('Discovery failed')
        raise HTTPException(503, f'ERC-8004 discovery unavailable: {e}')

@app.get('/api/agents/{agent_id}')
async def agent(agent_id: str):
    try:
        return await get_agent(int(agent_id))
    except Exception as e:
        raise HTTPException(404, f'Agent not found: {e}')

@app.post('/api/hire/prepare')
async def prepare(h: Hire):
    try:
        agent=await get_agent(int(h.agent_id))
        if agent['agentRegistry']!=h.agent_registry: raise ValueError('Agent registry mismatch')
        if not agent.get('identityVerified'): raise ValueError('Agent identity is not verified on the configured ERC-8004 registry')
        if not agent.get('endpoints'): raise ValueError('Agent has no executable endpoint')
        if not settings.provider_address: raise ValueError('Provider is not configured: PROVIDER_ADDRESS is required')
        return {'agent':agent,'provider':settings.provider_address,'evaluator':network['router'],'hook':network['router'],'policy':network['policy'],'expiresInSeconds':2592000}
    except Exception as e:
        raise HTTPException(400,str(e))

@app.post('/api/jobs/{job_id}/budget')
async def budget(job_id: int):
    if not provider_ready(): raise HTTPException(400,'Provider is not configured: please set PROVIDER_PRIVATE_KEY and PROVIDER_ADDRESS in environment variables.')
    try:
        tx=await quote(job_id,settings.service_price_units)
        state=read_job(job_id)
        if state['statusName']!='open' or int(state['budget'])<=0: raise RuntimeError(f'Budget verification failed: {state}')
        upsert(job_id,status='budgeted',budget_tx=tx)
        return {'ok':True,'txHash':tx,'onChain':state}
    except Exception as e:
        logger.exception(f'Budget failed for job {job_id}')
        raise HTTPException(400,str(e))

@app.post('/api/jobs/{job_id}/record')
async def record(job_id: int,h: TxRecord):
    fields=h.model_dump(exclude_none=True); fields.pop('description',None)
    if h.agent_id and h.agent_registry:
        agent=await get_agent(int(h.agent_id))
        if agent['agentRegistry']!=h.agent_registry: raise HTTPException(400,'Agent registry mismatch')
    upsert(job_id,**fields)
    return {'ok':True}

@app.post('/api/tx/verify')
async def tx_verify(tx_hash: str):
    try: return verify_receipt(tx_hash)
    except Exception as e: raise HTTPException(400,str(e))

@app.get('/api/jobs/{job_id}/chain')
async def chain_job(job_id: int):
    try: return read_job(job_id)
    except Exception as e: raise HTTPException(502,f'On-chain read failed: {e}')

def _recover_from_chain(job_id: int, chain: dict):
    description=str(chain.get('description') or '')
    match=re.match(r'^AgentForge:(.+):(\d+)$',description)
    fields={
        'status': str(chain.get('statusName') or 'onchain'),
        'client': str(chain.get('client') or ''),
    }
    if match:
        fields['agent_registry']=match.group(1)
        fields['agent_id']=match.group(2)
    upsert(job_id,**fields)
    recovered=get(job_id) or {'job_id':str(job_id),**fields}
    recovered['chain']=chain
    recovered['recoveredFromChain']=True
    return recovered

@app.get('/api/jobs/{job_id}')
async def job(job_id: int):
    r=get(job_id)
    if r:
        try: r['chain']=read_job(job_id)
        except Exception as e: r['chainError']=str(e)
        return r
    try:
        chain=read_job(job_id)
    except Exception as e:
        raise HTTPException(404,'Execution not found and no readable on-chain job exists')
    try:
        return _recover_from_chain(job_id,chain)
    except Exception as e:
        logger.exception(f'Job recovery failed for {job_id}')
        raise HTTPException(500,f'On-chain job exists but persistence recovery failed: {e}')

@app.get('/api/jobs')
async def list_jobs(limit: int = 50):
    return {'jobs':list_all(limit)}

@app.get('/erc8183/job/{job_id}/response')
async def deliverable(job_id: int):
    r=get(job_id)
    if not r or not r.get('result_json'): raise HTTPException(404,'Deliverable not found')
    try: return JSONResponse(content=json.loads(r['result_json']))
    except Exception: return JSONResponse(content={'result':r['result_json']})
