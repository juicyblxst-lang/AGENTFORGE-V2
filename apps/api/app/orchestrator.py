import asyncio, json, time
import httpx
from .config import settings
from .db import upsert, get
from .discovery import get_agent
from .chain import read_job, dispute_window

def provider_ready():
    return bool(settings.provider_private_key and settings.provider_address and settings.provider_agent_base_url)

def provider_client():
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    wallet=EVMWalletProvider(password='agentforge-runtime',private_key=settings.provider_private_key,persist=False)
    return wallet, ERC8183Client(wallet_provider=wallet,network=settings.network)

async def quote(job_id:int,amount_units:int):
    if not provider_ready(): raise RuntimeError('Provider requires PROVIDER_PRIVATE_KEY, PROVIDER_ADDRESS and PROVIDER_AGENT_BASE_URL')
    _,client=provider_client(); amount=amount_units*(10**client.token_decimals())
    result=client.set_budget(job_id,amount)
    if not result.get('success',False): raise RuntimeError(result.get('error') or 'setBudget failed')
    tx=result.get('txHash') or result.get('tx_hash')
    if not tx: raise RuntimeError('setBudget returned no transaction hash')
    return tx

async def execute_external(agent,task):
    endpoints=agent.get('endpoints',[])
    if not endpoints: raise RuntimeError('Selected ERC-8004 agent has no executable endpoint')
    last=None
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0,connect=10.0),follow_redirects=True) as http:
        for ep in endpoints:
            try:
                kind=str(ep.get('type','http')).lower(); url=ep['url']; payload={'task':task}
                if kind in ('a2a','agentcard','agent-card'):
                    card=(await http.get(url)).json()
                    if isinstance(card,dict) and card.get('url'): url=card['url']
                    elif not url.rstrip('/').endswith('/message/send'): url=url.rstrip('/')+'/message/send'
                    payload={'jsonrpc':'2.0','id':str(time.time_ns()),'method':'message/send','params':{'message':{'role':'user','parts':[{'kind':'text','text':task}]}}}
                r=await http.post(url,json=payload,headers={'content-type':'application/json','accept':'application/json'})
                r.raise_for_status()
                try:return r.json()
                except ValueError:return {'text':r.text}
            except Exception as e:last=e
    raise RuntimeError(f'Agent endpoint failed: {last}')

async def process_job(job_id:int):
    if not provider_ready(): return
    from bnbagent.erc8183 import ERC8183JobOps
    from bnbagent.storage import LocalStorageProvider
    wallet,client=provider_client(); job=client.get_job(job_id)
    if str(job.provider).lower()!=str(settings.provider_address).lower() or int(job.status)!=1:return
    record=get(job_id)
    if not record:return
    agent=await get_agent(int(record['agent_id']))
    if str(agent.get('owner','')).lower()!=str(settings.provider_address).lower():
        upsert(job_id,status='error',error='Configured provider wallet does not own the selected ERC-8004 agent')
        return
    upsert(job_id,status='executing')
    result=await execute_external(agent,job.description)
    ops=ERC8183JobOps(wallet,network=settings.network,storage_provider=LocalStorageProvider('.agent-data'),service_price=0,agent_url=settings.provider_agent_base_url)
    submitted=ops.submit_result(job_id,json.dumps(result,ensure_ascii=False),{'agentforge_agent':record['agent_id']})
    if not submitted.get('success',False):raise RuntimeError(submitted.get('error') or 'submit_result failed')
    submit_tx=submitted.get('txHash') or submitted.get('tx_hash')
    state=read_job(job_id)
    if state['statusName']!='submitted':raise RuntimeError(f'On-chain submit verification failed: {state}')
    upsert(job_id,status='submitted',submit_tx=submit_tx,result_json=json.dumps(result,ensure_ascii=False))

async def reconcile_once():
    if not provider_ready():return
    _,client=provider_client(); counter=int(client.commerce.job_counter())
    for jid in range(max(1,counter-50),counter+1):
        try:
            state=read_job(jid)
            if str(state['provider']).lower()!=str(settings.provider_address).lower():continue
            if state['statusName']=='funded': await process_job(jid)
            elif state['statusName']=='submitted':
                if int(state['submittedAt']) + dispute_window() > int(time.time()): continue
                result=client.settle(jid)
                if result.get('success',False):
                    settled=read_job(jid)
                    if settled['statusName']=='completed':upsert(jid,status='completed',settle_tx=result.get('txHash') or result.get('tx_hash'))
        except Exception as e:
            existing=get(jid)
            if existing and existing.get('status') not in ('submitted','completed'):upsert(jid,status='error',error=str(e))

async def worker():
    while True:
        try:await reconcile_once()
        except Exception:pass
        await asyncio.sleep(settings.poll_interval_seconds)
