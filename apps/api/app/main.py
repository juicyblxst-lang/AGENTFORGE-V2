import asyncio
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .config import settings, BSC_NETWORKS
from .db import init_db, upsert, get
from .discovery import discover, get_agent
from .chain_dynamic import read_job, verify_receipt
from .orchestrator import quote, worker

network = BSC_NETWORKS[settings.network]
app = FastAPI(title='AgentForge API', version='2.3.0')
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
    return {
        'ok': True,
        'network': settings.network,
        'chainId': network['chainId'],
        'providerConfigured': bool(settings.provider_private_key and settings.provider_address and settings.provider_agent_base_url),
        'contracts': {
            'identityRegistry': network['identityRegistry'],
            'commerce': network['commerce'],
            'router': network['router'],
            'policy': network['policy']
        }
    }

@app.get('/api/config')
async def config():
    return {**network, 'network': settings.network}

# ----- MOCK AGENT EXECUTION ENDPOINTS (for testing) -----
@app.post('/agent/rebalancing')
async def agent_rebalancing(payload: dict):
    return {"result": f"Rebalancing executed for task: {payload.get('task', 'no task')}"}

@app.post('/agent/grid-trading')
async def agent_grid_trading(payload: dict):
    return {"result": f"Grid trading executed for task: {payload.get('task', 'no task')}"}

@app.post('/agent/yield-optimisation')
async def agent_yield_optimisation(payload: dict):
    return {"result": f"Yield optimisation executed for task: {payload.get('task', 'no task')}"}

@app.post('/agent/health-factor-monitoring')
async def agent_health_factor_monitoring(payload: dict):
    return {"result": f"Health factor monitoring executed for task: {payload.get('task', 'no task')}"}

# ----- METADATA ENDPOINTS -----
@app.get('/api/metadata/rebalancing')
async def rebalancing_metadata():
    return {
        'type': 'https://eips.ethereum.org/EIPS/eip-8004#registration-v1',
        'name': 'AgentForge Rebalancing Agent',
        'description': 'ERC-8004 agent metadata for the AgentForge Rebalancing category.',
        'category': 'Rebalancing',
        'active': True,
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/rebalancing'}]
    }

@app.get('/api/metadata/grid-trading')
async def grid_trading_metadata():
    return {
        'type': 'https://eips.ethereum.org/EIPS/eip-8004#registration-v1',
        'name': 'AgentForge Grid Trading Agent',
        'description': 'ERC-8004 agent metadata for the AgentForge Grid Trading category.',
        'category': 'Grid Trading',
        'active': True,
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/grid-trading'}]
    }

@app.get('/api/metadata/yield-optimisation')
async def yield_optimisation_metadata():
    return {
        'type': 'https://eips.ethereum.org/EIPS/eip-8004#registration-v1',
        'name': 'AgentForge Yield Optimisation Agent',
        'description': 'ERC-8004 agent metadata for the AgentForge Yield Optimisation category.',
        'category': 'Yield Optimisation',
        'active': True,
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/yield-optimisation'}]
    }

@app.get('/api/metadata/health-factor-monitoring')
async def health_factor_monitoring_metadata():
    return {
        'type': 'https://eips.ethereum.org/EIPS/eip-8004#registration-v1',
        'name': 'AgentForge Health Factor Monitoring Agent',
        'description': 'ERC-8004 agent metadata for the AgentForge Health Factor Monitoring category.',
        'category': 'Health Factor Monitoring',
        'active': True,
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/health-factor-monitoring'}]
    }

# ----- HARDCODED AGENTS – no RPC, no discovery (frontend will immediately see them) -----
HARDCODED_AGENTS = [
    {
        'key': f'eip155:97:{network["identityRegistry"]}:2183',
        'agentId': '2183',
        'agentRegistry': f'eip155:97:{network["identityRegistry"]}',
        'name': 'AgentForge Rebalancing Agent',
        'description': 'ERC-8004 agent for portfolio rebalancing on BNB Chain.',
        'owner': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'agentWallet': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'identityVerified': True,
        'categories': ['rebalancing'],
        'skills': ['rebalance', 'liquidity', 'range'],
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/rebalancing'}],
        'reputation': None,
        'active': True
    },
    {
        'key': f'eip155:97:{network["identityRegistry"]}:2184',
        'agentId': '2184',
        'agentRegistry': f'eip155:97:{network["identityRegistry"]}',
        'name': 'AgentForge Grid Trading Agent',
        'description': 'ERC-8004 agent for grid trading strategies on BNB Chain.',
        'owner': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'agentWallet': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'identityVerified': True,
        'categories': ['grid-trading'],
        'skills': ['grid', 'dca', 'bot'],
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/grid-trading'}],
        'reputation': None,
        'active': True
    },
    {
        'key': f'eip155:97:{network["identityRegistry"]}:2185',
        'agentId': '2185',
        'agentRegistry': f'eip155:97:{network["identityRegistry"]}',
        'name': 'AgentForge Yield Optimisation Agent',
        'description': 'ERC-8004 agent for yield optimisation on BNB Chain.',
        'owner': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'agentWallet': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'identityVerified': True,
        'categories': ['yield-optimization'],
        'skills': ['yield', 'apr', 'liquidity'],
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/yield-optimisation'}],
        'reputation': None,
        'active': True
    },
    {
        'key': f'eip155:97:{network["identityRegistry"]}:2186',
        'agentId': '2186',
        'agentRegistry': f'eip155:97:{network["identityRegistry"]}',
        'name': 'AgentForge Health Factor Monitoring Agent',
        'description': 'ERC-8004 agent for health factor monitoring on BNB Chain.',
        'owner': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'agentWallet': settings.provider_address or '0x0000000000000000000000000000000000000000',
        'identityVerified': True,
        'categories': ['health-factor'],
        'skills': ['liquidation', 'health', 'risk'],
        'endpoints': [{'type': 'http', 'url': f'https://agentforge-v2-api.onrender.com/agent/health-factor-monitoring'}],
        'reputation': None,
        'active': True
    }
]

@app.get('/api/agents')
async def agents(limit: int = 100):
    return {'agents': HARDCODED_AGENTS[:limit]}

@app.get('/api/agents/{agent_id}')
async def agent(agent_id: str):
    for a in HARDCODED_AGENTS:
        if a['agentId'] == agent_id:
            return a
    try:
        return await get_agent(int(agent_id))
    except Exception as e:
        raise HTTPException(404, f'Agent not found: {e}')

@app.post('/api/hire/prepare')
async def prepare(h: Hire):
    try:
        agent = next((a for a in HARDCODED_AGENTS if a['agentId'] == h.agent_id), None)
        if not agent:
            agent = await get_agent(int(h.agent_id))
        if agent['agentRegistry'] != h.agent_registry:
            raise ValueError('Agent registry mismatch')
        if not agent.get('identityVerified'):
            raise ValueError('Agent identity is not verified on the configured ERC-8004 registry')
        if not agent.get('endpoints'):
            raise ValueError('Agent has no executable endpoint')
        if not settings.provider_address:
            raise ValueError('Provider is not configured: PROVIDER_ADDRESS is required')
        return {
            'agent': agent,
            'provider': settings.provider_address,
            'evaluator': network['router'],
            'hook': network['router'],
            'policy': network['policy'],
            'expiresInSeconds': 7200
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
        agent = next((a for a in HARDCODED_AGENTS if a['agentId'] == h.agent_id), None)
        if not agent:
            agent = await get_agent(int(h.agent_id))
        if agent['agentRegistry'] != h.agent_registry:
            raise HTTPException(400, 'Agent registry mismatch')
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
