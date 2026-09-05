from web3 import Web3
from .config import settings, BSC_TESTNET

COMMERCE_ABI = [{
    'type':'function','name':'getJob','stateMutability':'view',
    'inputs':[{'name':'jobId','type':'uint256'}],
    'outputs':[{'name':'job','type':'tuple','components':[
        {'name':'id','type':'uint256'},{'name':'client','type':'address'},
        {'name':'provider','type':'address'},{'name':'evaluator','type':'address'},
        {'name':'description','type':'string'},{'name':'budget','type':'uint256'},
        {'name':'expiredAt','type':'uint256'},{'name':'status','type':'uint8'},
        {'name':'hook','type':'address'},{'name':'submittedAt','type':'uint256'},
        {'name':'deliverable','type':'bytes32'}]}]},
    {'type':'function','name':'paymentToken','stateMutability':'view','inputs':[],
     'outputs':[{'type':'address'}]},
    {'type':'function','name':'jobCounter','stateMutability':'view','inputs':[],
     'outputs':[{'type':'uint256'}]},
]

STATUS_NAMES = {0:'open',1:'funded',2:'submitted',3:'completed',4:'rejected',5:'expired'}

def public_web3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={'timeout':15}))
    if not w3.is_connected():
        raise ConnectionError('BSC RPC is unavailable')
    if w3.eth.chain_id != BSC_TESTNET['chainId']:
        raise ConnectionError(f'RPC chain mismatch: expected 97, got {w3.eth.chain_id}')
    return w3

def read_job(job_id: int) -> dict:
    w3 = public_web3()
    c = w3.eth.contract(address=Web3.to_checksum_address(BSC_TESTNET['commerce']), abi=COMMERCE_ABI)
    j = c.functions.getJob(job_id).call()
    names = ['id','client','provider','evaluator','description','budget','expiredAt','status','hook','submittedAt','deliverable']
    out = dict(zip(names,j))
    out['id'] = int(out['id']); out['budget'] = int(out['budget']); out['expiredAt'] = int(out['expiredAt']);
    out['status'] = int(out['status']); out['statusName'] = STATUS_NAMES.get(out['status'], f'unknown:{out["status"]}')
    out['submittedAt'] = int(out['submittedAt'])
    out['deliverable'] = out['deliverable'].hex() if hasattr(out['deliverable'],'hex') else str(out['deliverable'])
    return out

def verify_receipt(tx_hash: str) -> dict:
    w3 = public_web3()
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    return {'txHash': tx_hash, 'status': int(receipt.status), 'blockNumber': int(receipt.blockNumber), 'success': receipt.status == 1}
