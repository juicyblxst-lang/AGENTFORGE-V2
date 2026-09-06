from web3 import Web3
from .config import settings, BSC_NETWORKS

def public_web3():
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={'timeout': 15}))
    if not w3.is_connected():
        raise ConnectionError('BSC RPC is unavailable')
    expected = BSC_NETWORKS[settings.network]['chainId']
    if w3.eth.chain_id != expected:
        raise ConnectionError(f'RPC chain mismatch: expected {expected}, got {w3.eth.chain_id}')
    return w3

def _get_sdk_client():
    from bnbagent import EVMWalletProvider
    from bnbagent.erc8183 import ERC8183Client
    pk = settings.provider_private_key or '0x0000000000000000000000000000000000000000000000000000000000000001'
    wallet = EVMWalletProvider(password='readonly', private_key=pk, persist=False)
    return ERC8183Client(wallet_provider=wallet, network=settings.network)

def read_job(job_id: int) -> dict:
    client = _get_sdk_client()
    job = client.get_job(job_id)
    status_map = {0: 'open', 1: 'funded', 2: 'submitted', 3: 'completed', 4: 'rejected', 5: 'expired'}
    return {
        'id': job.id,
        'client': job.client,
        'provider': job.provider,
        'evaluator': job.evaluator,
        'description': job.description,
        'budget': job.budget,
        'expiredAt': job.expiredAt,
        'status': job.status,
        'statusName': status_map.get(job.status, f'unknown:{job.status}'),
        'hook': job.hook,
        'submittedAt': job.submittedAt,
        'deliverable': job.deliverable.hex() if hasattr(job.deliverable, 'hex') else str(job.deliverable),
    }

def dispute_window() -> int:
    w3 = public_web3()
    policy_address = Web3.to_checksum_address(BSC_NETWORKS[settings.network]['policy'])
    POLICY_ABI = [{'type':'function','name':'disputeWindow','stateMutability':'view','inputs':[],'outputs':[{'type':'uint256'}]}]
    contract = w3.eth.contract(address=policy_address, abi=POLICY_ABI)
    return int(contract.functions.disputeWindow().call())

def verify_receipt(tx_hash: str) -> dict:
    w3 = public_web3()
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return {'txHash': tx_hash, 'status': int(receipt.status), 'blockNumber': int(receipt.blockNumber), 'success': receipt.status == 1}
