import asyncio, json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .config import settings, BSC_NETWORKS
from .db import init_db, upsert, get
from .discovery import discover, get_agent
from .chain import read_job, verify_receipt
from .orchestrator import quote, worker

network = BSC_NETWORKS[settings.network]
app = FastAPI(title='AgentForge API', version='2.2.0')
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
    fund_tx: str | None = None

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
    return {
        'ok': True,
        'network': settings.network,
        'chainId': network['chainId'],
        'providerConfigured': bool(settings.provider_private_key and settings.provider_address and settings.provider_agent_base_url),
    }

@app.get('/api/config')
async def config():
    return {**network, 'network': settings.network}

@app.get('/api/agents')
async def agents(limit: int = 100):
    try:
        return {'agents': await discover(limit)}
    except Exception as e:
        raise HTTPException(502, f'Discovery unavailable: {e}')

@app.get('/api/agents/{agent_id}')
async def agent(agent_id: str):
    try:
        return await get_agent(int(agent_id))
    except Exception as e:
        raise HTTPException(404, f'Agent not found: {e}')

@app.post('/api/hire/prepare')
async def prepare(h: Hire):
    try:
        agent = await get_agent(int(h.agent_id))
        if agent['agentRegistry'] != h.agent_registry:
            raise ValueError('Agent registry mismatch')
        if not agent.get('endpoints'):
            raise ValueError('Agent has no executable endpoint')
        provider = agent.get('owner')
        if not provider:
            raise ValueError('Agent has no resolvable provider/agent wallet')
        # Do not create a DB row with a string pseudo-job-id. The durable record
        # begins only after the real ERC-8183 JobCreated event gives us a uint job id.
        return {
            'agent': agent,
            'provider': provider,
            'evaluator': network['router'],
            'hook': network['router'],
            'policy': network['policy'],
            'expiresInSeconds': 7200,
        }
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post('/api/jobs/{job_id}/budget')
async def budget(job_id: int):
    try:
        tx = await quote(job_id, settings.service_price_units)
        state = read_job(job_id)
        if state['statusName'] != 'open' or state['budget'] <= 0:
            raise RuntimeError(f'On-chain verification failed after setBudget: {state}')
        upsert(job_id, status='budgeted', budget_tx=tx)
        return {'ok': True, 'txHash': tx, 'onChain': state}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post('/api/jobs/{job_id}/record')
async def record(job_id: int, h: TxRecord):
    fields = h.model_dump(exclude_none=True)
    fields.pop('description', None)
    if h.agent_id and h.agent_registry:
        agent = await get_agent(int(h.agent_id))
        if agent['agentRegistry'] != h.agent_registry:
            raise HTTPException(400, 'Agent registry mismatch')
    # Recording a transaction must never regress a later lifecycle state back to
    # `created`. The orchestrator is the authority for execution state.
    upsert(job_id, **fields)
    return {'ok': True}

@app.post('/api/tx/verify')
async def tx_verify(tx_hash: str):
    try:
        return verify_receipt(tx_hash)
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get('/api/jobs/{job_id}/chain')
async def chain_job(job_id: int):
    try:
        return read_job(job_id)
    except Exception as e:
        raise HTTPException(502, f'On-chain read failed: {e}')

@app.get('/api/jobs/{job_id}')
async def job(job_id: int):
    r = get(job_id)
    if not r:
        raise HTTPException(404, 'Execution not found')
    try:
        r['chain'] = read_job(job_id)
    except Exception as e:
        r['chainError'] = str(e)
    return r

@app.get('/erc8183/job/{job_id}/response')
async def deliverable(job_id: int):
    r = get(job_id)
    if not r or not r.get('result_json'):
        raise HTTPException(404, 'Deliverable not found')
    try:
        return JSONResponse(content=json.loads(r['result_json']))
    except Exception:
        return JSONResponse(content={'result': r['result_json']})
