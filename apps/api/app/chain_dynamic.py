from web3 import Web3
from .config import settings, BSC_NETWORKS

# Full Commerce ABI including getJob and setBudget (for completeness)
COMMERCE_ABI = [
    {
        "type": "function",
        "name": "getJob",
        "stateMutability": "view",
        "inputs": [{"name": "jobId", "type": "uint256"}],
        "outputs": [{
            "name": "job",
            "type": "tuple",
            "components": [
                {"name": "id", "type": "uint256"},
                {"name": "client", "type": "address"},
                {"name": "provider", "type": "address"},
                {"name": "evaluator", "type": "address"},
                {"name": "description", "type": "string"},
                {"name": "budget", "type": "uint256"},
                {"name": "expiredAt", "type": "uint256"},
                {"name": "status", "type": "uint8"},
                {"name": "hook", "type": "address"},
                {"name": "submittedAt", "type": "uint256"},
                {"name": "deliverable", "type": "bytes32"}
            ]
        }]
    },
    {
        "type": "function",
        "name": "setBudget",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "jobId", "type": "uint256"},
            {"name": "budget", "type": "uint256"}
        ],
        "outputs": []
    },
    {
        "type": "function",
        "name": "paymentToken",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "address"}]
    },
    {
        "type": "function",
        "name": "jobCounter",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}]
    }
]

POLICY_ABI = [
    {
        "type": "function",
        "name": "disputeWindow",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"type": "uint256"}]
    }
]

STATUS_NAMES = {0: 'open', 1: 'funded', 2: 'submitted', 3: 'completed', 4: 'rejected', 5: 'expired'}

def public_web3():
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={'timeout': 15}))
    if not w3.is_connected():
        raise ConnectionError('BSC RPC is unavailable')
    expected = BSC_NETWORKS[settings.network]['chainId']
    if w3.eth.chain_id != expected:
        raise ConnectionError(f'RPC chain mismatch: expected {expected}, got {w3.eth.chain_id}')
    return w3

def read_job(job_id: int) -> dict:
    w3 = public_web3()
    commerce_address = Web3.to_checksum_address(BSC_NETWORKS[settings.network]['commerce'])
    contract = w3.eth.contract(address=commerce_address, abi=COMMERCE_ABI)
    job = contract.functions.getJob(job_id).call()
    
    # job is a tuple in the order of the components
    fields = ['id', 'client', 'provider', 'evaluator', 'description', 'budget', 'expiredAt', 'status', 'hook', 'submittedAt', 'deliverable']
    data = dict(zip(fields, job))
    
    # Convert to proper types
    for key in ['id', 'budget', 'expiredAt', 'status', 'submittedAt']:
        data[key] = int(data[key])
    data['statusName'] = STATUS_NAMES.get(data['status'], 'unknown')
    data['deliverable'] = data['deliverable'].hex() if isinstance(data['deliverable'], bytes) else str(data['deliverable'])
    
    return data

def dispute_window() -> int:
    w3 = public_web3()
    policy_address = Web3.to_checksum_address(BSC_NETWORKS[settings.network]['policy'])
    contract = w3.eth.contract(address=policy_address, abi=POLICY_ABI)
    return int(contract.functions.disputeWindow().call())

def verify_receipt(tx_hash: str) -> dict:
    w3 = public_web3()
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return {
        'txHash': tx_hash,
        'status': int(receipt.status),
        'blockNumber': int(receipt.blockNumber),
        'success': receipt.status == 1
    }
