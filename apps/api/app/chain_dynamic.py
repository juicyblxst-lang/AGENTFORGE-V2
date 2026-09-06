from bnbagent import EVMWalletProvider
from bnbagent.erc8183 import ERC8183Client
from .config import settings, BSC_NETWORKS

def _get_sdk_client():
    pk = settings.provider_private_key or '0x0000000000000000000000000000000000000000000000000000000000000001'
    wallet = EVMWalletProvider(password='readonly', private_key=pk, persist=False)
    return ERC8183Client(wallet_provider=wallet, network=settings.network)

def read_job(job_id: int) -> dict:
    client = _get_sdk_client()
    job = client.get_job(job_id)  # returns a dict with snake_case keys
    status_map = {0: 'open', 1: 'funded', 2: 'submitted', 3: 'completed', 4: 'rejected', 5: 'expired'}
    return {
        'id': job['jobId'],
        'client': job['client'],
        'provider': job['provider'],
        'evaluator': job['evaluator'],
        'description': job.get('description', ''),
        'budget': job['budget'],
        'expired_at': job['expired_at'],   # ✅ correct snake_case
        'status': job['status'],
        'statusName': status_map.get(job['status'], 'unknown'),
        'hook': job.get('hook', '0x0000000000000000000000000000000000000000'),
        'submitted_at': job.get('submitted_at', 0),
        'deliverable': job.get('deliverable', '0x0000000000000000000000000000000000000000000000000000000000000000')
    }

# Keep dispute_window and verify_receipt as before using web3
def dispute_window() -> int:
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={'timeout': 15}))
    policy_address = Web3.to_checksum_address(BSC_NETWORKS[settings.network]['policy'])
    POLICY_ABI = [{'type':'function','name':'disputeWindow','stateMutability':'view','inputs':[],'outputs':[{'type':'uint256'}]}]
    contract = w3.eth.contract(address=policy_address, abi=POLICY_ABI)
    return int(contract.functions.disputeWindow().call())

def verify_receipt(tx_hash: str) -> dict:
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={'timeout': 15}))
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return {'txHash': tx_hash, 'status': int(receipt.status), 'blockNumber': int(receipt.blockNumber), 'success': receipt.status == 1}
