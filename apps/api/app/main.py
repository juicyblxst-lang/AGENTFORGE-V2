import asyncio, json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .config import settings, BSC_TESTNET
from .db import init_db, upsert, get
from .discovery import discover, get_agent
from .orchestrator import quote, worker

app=FastAPI(title='AgentForge API',version='2.0.0')
app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
worker_task=None
class Hire(BaseModel):
    agent_id:str
    agent_registry:str
    client:str
    description:str=Field(min_length=1,max_length=4000)
@app.on_event('startup')
async def startup():
    global worker_task
    init_db(); worker_task=asyncio.create_task(worker())
@app.on_event('shutdown')
async def shutdown():
    if worker_task: worker_task.cancel()
@app.get('/health')
async def health(): return {'ok':True,'network':'BSC Testnet','chainId':97,'providerConfigured':bool(settings.provider_private_key and settings.provider_address)}
@app.get('/api/config')
async def config(): return {'chainId':97,'identityRegistry':BSC_TESTNET['identityRegistry'],'commerce':BSC_TESTNET['commerce'],'router':BSC_TESTNET['router'],'policy':BSC_TESTNET['policy'],'network':'bsc-testnet'}
@app.get('/api/agents')
async def agents(limit:int=100):
    try:return {'agents':await discover(limit)}
    except Exception as e:raise HTTPException(502,f'Discovery unavailable: {e}')
@app.get('/api/agents/{agent_id}')
async def agent(agent_id:str):
    try:return await get_agent(int(agent_id))
    except Exception as e:raise HTTPException(404,f'Agent not found: {e}')
@app.post('/api/hire/prepare')
async def prepare(h:Hire):
    try:
        agent=await get_agent(int(h.agent_id))
        if agent['agentRegistry']!=h.agent_registry:raise ValueError('Agent registry mismatch')
        if not agent['endpoints']:raise ValueError('Agent has no executable endpoint')
        upsert('pending:'+h.agent_id,agent_registry=h.agent_registry,agent_id=h.agent_id,client=h.client,status='selected')
        return {'agent':agent,'provider':agent.get('owner'),'evaluator':BSC_TESTNET['router'],'hook':BSC_TESTNET['router'],'policy':BSC_TESTNET['policy'],'expiresInSeconds':1800}
    except Exception as e:raise HTTPException(400,str(e))
@app.post('/api/jobs/{job_id}/budget')
async def budget(job_id:int):
    try:
        tx=await quote(job_id,settings.service_price_units); upsert(job_id,status='budgeted')
        return {'ok':True,'txHash':tx}
    except Exception as e:raise HTTPException(400,str(e))
@app.post('/api/jobs/{job_id}/record')
async def record(job_id:int,h:Hire):
    upsert(job_id,agent_registry=h.agent_registry,agent_id=h.agent_id,client=h.client,status='created'); return {'ok':True}
@app.get('/api/jobs/{job_id}')
async def job(job_id:int):
    r=get(job_id)
    if not r:raise HTTPException(404,'Execution not found')
    if r.get('result_json'):
        try:r['result']=json.loads(r['result_json'])
        except Exception:r['result']=r['result_json']
    return r
