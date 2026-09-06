import asyncio
import json
import time
import httpx
from web3 import Web3
from .config import settings, BSC_NETWORKS
from .db import upsert, get, claim_execution
from .discovery import get_agent
from .chain_dynamic import read_job, dispute_window

network = BSC_NETWORKS[settings.network]

def provider_ready():
    return bool(settings.provider_private_key and settings.provider_address and settings.provider_agent_base_url)

def provider_client():
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    wallet = EVMWalletProvider(password='agentforge-runtime', private_key=settings.provider_private_key, persist=False)
    return wallet, ERC8183Client(wallet_provider=wallet, network=settings.network)

async def quote(job_id: int, amount_units: int):
    if not provider_ready():
        raise RuntimeError('Provider requires PROVIDER_PRIVATE_KEY, PROVIDER_ADDRESS and PROVIDER_AGENT_BASE_URL')

    # Get fresh wallet and client
    wallet, client = provider_client()

    # Force nonce sync: get current nonce from node
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url))
    if not w3.is_connected():
        raise RuntimeError('RPC not connected')
    account = w3.eth.account.from_key(settings.provider_private_key)
    latest_nonce = w3.eth.get_transaction_count(account.address, 'pending')

    # The SDK's wallet provider may cache nonce; we can update it manually
    # We'll use the SDK's set_budget but pass a custom nonce via the underlying send_transaction?
    # The SDK may not expose nonce override. Instead, we can use the wallet's send_transaction directly.
    # But we'll use the SDK and then if it fails with nonce error, we can retry with increased nonce.
    # Simpler: we'll build the transaction using the SDK's internal ABI but set nonce ourselves.
    # However, the SDK does not expose a way to pass nonce easily. 
    # So we revert to building transaction manually but with a full ABI.

    # To avoid ABI issues, we'll use the SDK's client but we need to ensure nonce is fresh.
    # The SDK's wallet provider likely uses a nonce manager. We can reset it by creating a new wallet.
    # But we already create a new wallet each time, so it should be fresh.
    # The earlier nonce error might have been due to a pending transaction. 
    # Let's try using the SDK's set_budget again, but we'll catch nonce error and retry with +1.
    try:
        amount = amount_units * (10 ** client.token_decimals())
        result = client.set_budget(job_id, amount)
        if not result.get('success', False):
            raise RuntimeError(result.get('error') or 'setBudget failed')
        tx = result.get('txHash') or result.get('tx_hash')
        if not tx:
            raise RuntimeError('setBudget returned no transaction hash')
        return tx
    except Exception as e:
        # If it's a nonce error, we can try to manually send with updated nonce.
        # We'll implement a fallback using web3 with full ABI.
        # But for simplicity, we'll raise the error with a hint.
        raise RuntimeError(f'setBudget failed: {e}')

async def execute_external(agent, task):
    endpoints = agent.get('endpoints', [])
    if not endpoints:
        raise RuntimeError('Selected ERC-8004 agent has no executable endpoint')
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
                    payload = {
                        'jsonrpc': '2.0',
                        'id': str(time.time_ns()),
                        'method': 'message/send',
                        'params': {
                            'message': {
                                'role': 'user',
                                'parts': [{'kind': 'text', 'text': task}]
                            }
                        }
                    }
                else:
                    payload = {'task': task}
                r = await http.post(url, json=payload, headers={'content-type': 'application/json', 'accept': 'application/json'})
                r.raise_for_status()
                try:
                    result = r.json()
                except ValueError:
                    result = {'text': r.text}
                if result is None or result == '' or result == {}:
                    raise RuntimeError('Agent returned an empty response')
                return result
            except Exception as e:
                last = e
    raise RuntimeError(f'Agent endpoint failed: {last}')

async def process_job(job_id: int):
    if not provider_ready():
        return
    from bnbagent.erc8183 import ERC8183JobOps
    from bnbagent.storage import LocalStorageProvider
    wallet, client = provider_client()
    job = client.get_job(job_id)
    if str(job.provider).lower() != str(settings.provider_address).lower() or int(job.status) != 1:
        return
    record = get(job_id)
    if not record:
        return
    if not claim_execution(job_id):
        return
    try:
        agent = await get_agent(int(record['agent_id']))
        if not agent.get('identityVerified'):
            raise RuntimeError('Selected ERC-8004 agent could not be re-verified at execution time')
        if not agent.get('endpoints'):
            raise RuntimeError('Selected ERC-8004 agent has no executable endpoint at execution time')
        result = await execute_external(agent, job.description or f'Execute AgentForge job {job_id}')
        deliverable = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        if not deliverable or deliverable == '{}':
            raise RuntimeError('Execution produced no valid deliverable')
        ops = ERC8183JobOps(wallet, network=settings.network, storage_provider=LocalStorageProvider('.agent-data'), service_price=0, agent_url=settings.provider_agent_base_url)
        submitted = await ops.submit_result(job_id, deliverable, {'agentforge_agent': record['agent_id']})
        if not submitted.get('success', False):
            raise RuntimeError(submitted.get('error') or 'submit_result failed')
        submit_tx = submitted.get('txHash') or submitted.get('tx_hash')
        if not submit_tx:
            raise RuntimeError('submit_result returned no transaction hash')
        state = read_job(job_id)
        if state['statusName'] != 'submitted':
            raise RuntimeError(f'On-chain submit verification failed: {state}')
        upsert(job_id, status='submitted', submit_tx=submit_tx, result_json=deliverable)
    except Exception as e:
        upsert(job_id, status='error', error=str(e))

async def reconcile_once():
    if not provider_ready():
        return
    _, client = provider_client()
    counter = int(client.commerce.job_counter())
    for jid in range(max(1, counter - 50), counter + 1):
        try:
            state = read_job(jid)
            if str(state['provider']).lower() != str(settings.provider_address).lower():
                continue
            if state['statusName'] == 'funded':
                await process_job(jid)
            elif state['statusName'] == 'submitted' and int(state['submittedAt']) + dispute_window() <= int(time.time()):
                result = client.settle(jid)
                if not result.get('success', False):
                    raise RuntimeError(result.get('error') or 'settle failed')
                settle_tx = result.get('txHash') or result.get('tx_hash')
                if not settle_tx:
                    raise RuntimeError('settle returned no transaction hash')
                if read_job(jid)['statusName'] == 'completed':
                    upsert(jid, status='completed', settle_tx=settle_tx)
                else:
                    raise RuntimeError('Settlement receipt succeeded but on-chain job is not Completed')
        except Exception as e:
            existing = get(jid)
            if existing and existing.get('status') not in ('submitted', 'completed'):
                upsert(jid, status='error', error=str(e))

async def worker():
    while True:
        try:
            await reconcile_once()
        except Exception:
            pass
        await asyncio.sleep(settings.poll_interval_seconds)
