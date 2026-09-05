import asyncio, json, time
import httpx
from .config import settings
from .db import upsert, get
from .discovery import get_agent

STATUS_NAMES=['Open','Funded','Submitted','Completed','Rejected','Expired']

def provider_ready():
    return bool(settings.provider_private_key and settings.provider_address)

async def quote(job_id:int, amount_units:int):
    if not provider_ready():
        raise RuntimeError('Provider wallet is not configured')
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    wallet=EVMWalletProvider(password='agentforge-runtime', private_key=settings.provider_private_key, persist=False)
    client=await ERC8183Client.create(wallet_provider=wallet, network='bsc-testnet')
    result=await client.set_budget(job_id, amount_units * (10 ** await client.token_decimals()))
    if not result.success: raise RuntimeError(result.error or 'setBudget failed')
    return result.tx_hash

async def execute_external(agent, task):
    endpoints=agent.get('endpoints',[])
    if not endpoints: raise RuntimeError('Selected ERC-8004 agent has no executable endpoint')
    last=None
    async with httpx.AsyncClient(timeout=45) as client:
        for ep in endpoints:
            url=ep['url']
            try:
                if str(ep.get('type','')).lower() in ('a2a','agentcard'):
                    if not url.endswith('/message/send'): url=url.rstrip('/')+'/message/send'
                    payload={'jsonrpc':'2.0','id':str(time.time_ns()),'method':'message/send','params':{'message':{'role':'user','parts':[{'kind':'text','text':task}]}}}
                else:
                    payload={'task':task}
                r=await client.post(url,json=payload,headers={'content-type':'application/json'})
                r.raise_for_status()
                return r.json() if 'json' in r.headers.get('content-type','') else {'text':r.text}
            except Exception as e: last=e
    raise RuntimeError(f'Agent endpoint failed: {last}')

async def process_job(job_id:int):
    if not provider_ready(): return
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client, ERC8183JobOps
    from bnbagent.storage import LocalStorageProvider
    wallet=EVMWalletProvider(password='agentforge-runtime', private_key=settings.provider_private_key, persist=False)
    client=await ERC8183Client.create(wallet_provider=wallet, network='bsc-testnet')
    job=await client.get_job(job_id)
    if str(job.provider).lower()!=str(settings.provider_address).lower() or int(job.status)!=1: return
    record=get(job_id)
    if not record: return
    agent=await get_agent(int(record['agent_id']))
    task=job.description
    upsert(job_id,status='executing')
    result=await execute_external(agent, task)
    storage=LocalStorageProvider('.agent-data')
    ops=await ERC8183JobOps.create(wallet_provider=wallet,network='bsc-testnet',storage_provider=storage,service_price=0,agent_url=settings.provider_agent_base_url)
    submitted=await ops.submit_result(job_id,json.dumps(result,ensure_ascii=False),{'agentforge_agent':record['agent_id']})
    if not submitted.success: raise RuntimeError(submitted.error or 'submitResult failed')
    upsert(job_id,status='submitted',submit_tx=submitted.tx_hash,result_json=json.dumps(result,ensure_ascii=False))

async def reconcile_once():
    if not provider_ready(): return
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    wallet=EVMWalletProvider(password='agentforge-runtime', private_key=settings.provider_private_key, persist=False)
    client=await ERC8183Client.create(wallet_provider=wallet, network='bsc-testnet')
    counter=int(await client.commerce.job_counter())
    start=max(1,counter-50)
    for jid in range(start,counter+1):
        try:
            job=await client.get_job(jid)
            if str(job.provider).lower()!=str(settings.provider_address).lower(): continue
            if int(job.status)==1:
                await process_job(jid)
            elif int(job.status)==2:
                result=await client.settle(jid)
                if result.success:
                    upsert(jid,status='completed',settle_tx=result.tx_hash)
        except Exception as e:
            if get(jid): upsert(jid,status='error',error=str(e))

async def worker():
    while True:
        try: await reconcile_once()
        except Exception: pass
        await asyncio.sleep(settings.poll_interval_seconds)
