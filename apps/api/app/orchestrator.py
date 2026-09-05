import asyncio, json, time
import httpx
from .config import settings
from .db import upsert, get
from .discovery import get_agent

def provider_ready():
    return bool(settings.provider_private_key and settings.provider_address)

def provider_client():
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    wallet=EVMWalletProvider(password='agentforge-runtime', private_key=settings.provider_private_key, persist=False)
    return wallet, ERC8183Client(wallet_provider=wallet, network='bsc-testnet')

async def quote(job_id:int, amount_units:int):
    if not provider_ready(): raise RuntimeError('Provider wallet is not configured')
    _,client=provider_client()
    amount=amount_units * (10 ** client.token_decimals())
    result=client.set_budget(job_id, amount)
    if not result.get('success',False): raise RuntimeError(result.get('error') or 'setBudget failed')
    return result.get('txHash') or result.get('tx_hash')

async def execute_external(agent, task):
    endpoints=agent.get('endpoints',[])
    if not endpoints: raise RuntimeError('Selected ERC-8004 agent has no executable endpoint')
    last=None
    async with httpx.AsyncClient(timeout=45) as http:
        for ep in endpoints:
            url=ep['url']
            try:
                if str(ep.get('type','')).lower() in ('a2a','agentcard'):
                    if not url.endswith('/message/send'): url=url.rstrip('/')+'/message/send'
                    payload={'jsonrpc':'2.0','id':str(time.time_ns()),'method':'message/send','params':{'message':{'role':'user','parts':[{'kind':'text','text':task}]}}}
                else: payload={'task':task}
                r=await http.post(url,json=payload,headers={'content-type':'application/json'})
                r.raise_for_status()
                return r.json() if 'json' in r.headers.get('content-type','') else {'text':r.text}
            except Exception as e: last=e
    raise RuntimeError(f'Agent endpoint failed: {last}')

async def process_job(job_id:int):
    if not provider_ready(): return
    from bnbagent.erc8183 import ERC8183JobOps
    from bnbagent.storage import LocalStorageProvider
    wallet,client=provider_client()
    job=client.get_job(job_id)
    if str(job.provider).lower()!=str(settings.provider_address).lower() or int(job.status)!=1: return
    record=get(job_id)
    if not record: return
    agent=await get_agent(int(record['agent_id']))
    upsert(job_id,status='executing')
    result=await execute_external(agent, job.description)
    ops=ERC8183JobOps(wallet,network='bsc-testnet',storage_provider=LocalStorageProvider('.agent-data'),service_price=0,agent_url=settings.provider_agent_base_url)
    submitted=ops.submit_result(job_id,json.dumps(result,ensure_ascii=False),{'agentforge_agent':record['agent_id']})
    if not submitted.get('success',False): raise RuntimeError(submitted.get('error') or 'submitResult failed')
    upsert(job_id,status='submitted',submit_tx=submitted.get('txHash') or submitted.get('tx_hash'),result_json=json.dumps(result,ensure_ascii=False))

async def reconcile_once():
    if not provider_ready(): return
    _,client=provider_client()
    counter=int(client.commerce.job_counter())
    for jid in range(max(1,counter-50),counter+1):
        try:
            job=client.get_job(jid)
            if str(job.provider).lower()!=str(settings.provider_address).lower(): continue
            if int(job.status)==1: await process_job(jid)
            elif int(job.status)==2:
                result=client.settle(jid)
                if result.get('success',False): upsert(jid,status='completed',settle_tx=result.get('txHash') or result.get('tx_hash'))
        except Exception as e:
            if get(jid): upsert(jid,status='error',error=str(e))

async def worker():
    while True:
        try: await reconcile_once()
        except Exception: pass
        await asyncio.sleep(settings.poll_interval_seconds)
