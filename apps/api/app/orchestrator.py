import asyncio
import json
import time
import httpx
from web3 import Web3
from .config import settings, BSC_NETWORKS
from .db import upsert, get, claim_execution
from .discovery import get_agent
from .chain_dynamic import read_job, dispute_window, COMMERCE_ABI

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

    # Get wallet and web3
    wallet, client = provider_client()
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url))
    if not w3.is_connected():
        raise RuntimeError('RPC not connected')

    # Get the current nonce from the node
    account = w3.eth.account.from_key(settings.provider_private_key)
    nonce = w3.eth.get_transaction_count(account.address, 'pending')
    # Force a slight increment if we suspect stale nonce
    # (we'll just use the latest from the node)

    # Build the commerce contract
    commerce_address = Web3.to_checksum_address(network['commerce'])
    commerce = w3.eth.contract(address=commerce_address, abi=COMMERCE_ABI)

    # Calculate amount
    token_decimals = client.token_decimals()  # from the client, or we can read from contract
    amount = amount_units * (10 ** token_decimals)

    # Build the setBudget transaction
    tx = commerce.functions.setBudget(job_id, amount).build_transaction({
        'from': account.address,
        'nonce': nonce,
        'gas': 300000,
        'gasPrice': w3.eth.gas_price,
        'chainId': network['chainId'],
    })

    # Sign and send
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt.status != 1:
        raise RuntimeError(f'Budget transaction failed with status {receipt.status}')

    return tx_hash.hex()

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
