import asyncio
import json
import time
import httpx
from web3 import Web3
from .config import settings, BSC_NETWORKS
from .db import upsert, get, claim_execution, list_all
from .discovery import get_agent
from .chain_dynamic import read_job, dispute_window

network = BSC_NETWORKS[settings.network]

COMMERCE_ABI = [
    {'type':'function','name':'setBudget','stateMutability':'nonpayable','inputs':[{'name':'jobId','type':'uint256'},{'name':'budget','type':'uint256'},{'name':'optParams','type':'bytes'}],'outputs':[]},
    {'type':'function','name':'getJob','stateMutability':'view','inputs':[{'name':'jobId','type':'uint256'}],'outputs':[{'type':'tuple','components':[{'name':'id','type':'uint256'},{'name':'client','type':'address'},{'name':'provider','type':'address'},{'name':'evaluator','type':'address'},{'name':'description','type':'string'},{'name':'budget','type':'uint256'},{'name':'expiredAt','type':'uint256'},{'name':'status','type':'uint8'},{'name':'hook','type':'address'},{'name':'submittedAt','type':'uint256'},{'name':'deliverable','type':'bytes32'}]}]},
    {'type':'function','name':'paymentToken','stateMutability':'view','inputs':[],'outputs':[{'type':'address'}]},
]
ROUTER_ABI = [
    {'type':'function','name':'settle','stateMutability':'nonpayable','inputs':[{'name':'jobId','type':'uint256'},{'name':'evidence','type':'bytes'}],'outputs':[]},
]

def provider_ready():
    return bool(settings.provider_private_key and settings.provider_address and settings.provider_agent_base_url)

def get_w3():
    return Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={'timeout': 20}))

def send_tx(w3, contract_fn, from_address, private_key):
    """Build, sign and send a transaction with a fresh pending nonce."""
    nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(from_address), 'pending')
    gas_price = w3.eth.gas_price
    tx = contract_fn.build_transaction({'from': Web3.to_checksum_address(from_address), 'nonce': nonce, 'gasPrice': int(gas_price * 1.2)})
    try:
        tx['gas'] = w3.eth.estimate_gas(tx)
    except Exception:
        tx['gas'] = 300000
    signed = w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        raise RuntimeError(f'Transaction reverted: {tx_hash.hex()}')
    return tx_hash.hex()

async def quote(job_id: int, amount_units: int):
    if not provider_ready():
        raise RuntimeError('Provider not ready')
    w3 = get_w3()
    if not w3.is_connected():
        raise RuntimeError('RPC unavailable')
    commerce = w3.eth.contract(address=Web3.to_checksum_address(network['commerce']), abi=COMMERCE_ABI)
    token_address = commerce.functions.paymentToken().call()
    erc20 = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=[{'type':'function','name':'decimals','stateMutability':'view','inputs':[],'outputs':[{'type':'uint8'}]}])
    decimals = erc20.functions.decimals().call()
    amount = amount_units * (10 ** decimals)
    return send_tx(w3, commerce.functions.setBudget(job_id, amount, b''), settings.provider_address, settings.provider_private_key)

async def execute_external(agent, task):
    endpoints = agent.get('endpoints', [])
    if not endpoints:
        raise RuntimeError('No executable endpoint')
    last = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0), follow_redirects=True) as http:
        for ep in endpoints:
            try:
                kind = str(ep.get('type', 'http')).lower()
                url = ep['url']
                if kind in ('a2a', 'agentcard', 'agent-card'):
                    card = (await http.get(url)).json()
                    if isinstance(card, dict) and card.get('url'):
                        url = card['url']
                    elif not url.rstrip('/').endswith('/message/send'):
                        url = url.rstrip('/') + '/message/send'
                    payload = {'jsonrpc':'2.0','id':str(time.time_ns()),'method':'message/send','params':{'message':{'role':'user','parts':[{'kind':'text','text':task}]}}}
                else:
                    payload = {'task': task}
                r = await http.post(url, json=payload, headers={'content-type':'application/json','accept':'application/json'})
                r.raise_for_status()
                try:
                    result = r.json()
                except ValueError:
                    result = {'text': r.text}
                if result is None or result == '' or result == {}:
                    raise RuntimeError('Agent returned empty response')
                return result
            except Exception as e:
                last = e
    raise RuntimeError(f'Agent endpoint failed: {last}')

async def process_job(job_id: int):
    if not provider_ready():
        return
    from bnbagent.erc8183 import ERC8183JobOps
    from bnbagent.storage import LocalStorageProvider
    from bnbagent import EVMWalletProvider
    wallet = EVMWalletProvider(password='agentforge-runtime', private_key=settings.provider_private_key, persist=False)
    client_sdk = __import__('bnbagent.erc8183', fromlist=['ERC8183Client']).ERC8183Client(wallet_provider=wallet, network=settings.network)
    job = client_sdk.get_job(job_id)
    if str(job.provider).lower() != str(settings.provider_address).lower() or job.status != 1:
        return
    record = get(job_id)
    if not record or not claim_execution(job_id):
        return
    try:
        from .main import HARDCODED_AGENTS
        agent = next((a for a in HARDCODED_AGENTS if a['agentId'] == record['agent_id']), None)
        if not agent:
            agent = await get_agent(int(record['agent_id']))
        if not agent.get('identityVerified'):
            raise RuntimeError('Agent not verified at execution time')
        if not agent.get('endpoints'):
            raise RuntimeError('No executable endpoint at execution time')
        result = await execute_external(agent, job.description or f'Execute job {job_id}')
        deliverable = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        if not deliverable or deliverable == '{}':
            raise RuntimeError('Execution produced no valid deliverable')
        ops = ERC8183JobOps(wallet, network=settings.network, storage_provider=LocalStorageProvider('.agent-data'), service_price=0, agent_url=settings.provider_agent_base_url)
        submitted = await ops.submit_result(job_id, deliverable, {'agentforge_agent': record['agent_id']})
        if not submitted.get('success', False):
            raise RuntimeError(submitted.get('error') or 'submit_result failed')
        submit_tx = submitted.get('txHash') or submitted.get('tx_hash')
        if not submit_tx:
            raise RuntimeError('submit_result returned no tx hash')
        state = read_job(job_id)
        if state['statusName'] != 'submitted':
            raise RuntimeError(f'Submit verification failed: {state}')
        upsert(job_id, status='submitted', submit_tx=submit_tx, result_json=deliverable)
    except Exception as e:
        upsert(job_id, status='error', error=str(e))

async def reconcile_once():
    if not provider_ready():
        return
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    wallet = EVMWalletProvider(password='agentforge-runtime', private_key=settings.provider_private_key, persist=False)
    client_sdk = ERC8183Client(wallet_provider=wallet, network=settings.network)
    for row in list_all(limit=200):
        jid = int(row['job_id'])
        db_status = row.get('status')
        # Completed is terminal. Errors are deliberately retryable because a failed
        # provider call/RPC must never strand an on-chain FUNDED job in escrow.
        # Apply a short backoff so a permanently broken endpoint does not get
        # hammered every poll cycle.
        if db_status == 'completed':
            continue
        if db_status == 'error':
            updated_at = row.get('updated_at')
            if updated_at:
                try:
                    age = time.time() - __import__('datetime').datetime.fromisoformat(updated_at.replace('Z', '+00:00')).timestamp()
                    if age < 60:
                        continue
                except Exception:
                    pass
        try:
            state = read_job(jid)
            if str(state['provider']).lower() != str(settings.provider_address).lower():
                continue
            if state['statusName'] == 'funded':
                await process_job(jid)
            elif state['statusName'] == 'submitted' and int(state['submitted_at']) + dispute_window() <= int(time.time()):
                w3 = get_w3()
                router = w3.eth.contract(address=Web3.to_checksum_address(network['router']), abi=ROUTER_ABI)
                settle_hash = send_tx(w3, router.functions.settle(jid, b''), settings.provider_address, settings.provider_private_key)
                if read_job(jid)['statusName'] == 'completed':
                    upsert(jid, status='completed', settle_tx=settle_hash)
                else:
                    raise RuntimeError('Settlement transaction succeeded but job is not Completed')
        except Exception as e:
            existing = get(jid)
            if existing and existing.get('status') not in ('submitted', 'completed'):
                upsert(jid, status='error', error=str(e))
    try:
        counter = int(client_sdk.commerce.job_counter())
        for jid in range(max(1, counter - 5), counter + 1):
            if get(jid):
                continue
            state = read_job(jid)
            if str(state['provider']).lower() == str(settings.provider_address).lower() and state['statusName'] == 'funded':
                upsert(jid, status='created')
                await process_job(jid)
    except Exception:
        pass

async def worker():
    await asyncio.sleep(15)
    while True:
        try:
            await reconcile_once()
        except Exception:
            pass
        await asyncio.sleep(settings.poll_interval_seconds)
