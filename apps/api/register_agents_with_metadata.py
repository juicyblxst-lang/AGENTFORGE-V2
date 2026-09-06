import os
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
from web3 import Web3

load_dotenv(Path(__file__).resolve().with_name('.env'))

CHAIN_ID = 97
IDENTITY_REGISTRY = '0x8004A818BFB912233c491871b3d84c89A494BD9e'
REGISTRY_ABI = [
    {
        'type': 'function',
        'name': 'register',
        'stateMutability': 'nonpayable',
        'inputs': [{'name': 'agentURI', 'type': 'string'}],
        'outputs': [{'name': 'agentId', 'type': 'uint256'}]
    },
    {
        'type': 'event',
        'name': 'Registered',
        'anonymous': False,
        'inputs': [
            {'indexed': True, 'name': 'agentId', 'type': 'uint256'},
            {'indexed': False, 'name': 'agentURI', 'type': 'string'},
            {'indexed': True, 'name': 'owner', 'type': 'address'}
        ]
    }
]

METADATA = {
    'Rebalancing': {
        'name': 'AgentForge Rebalancing Agent',
        'description': 'Portfolio rebalancing, liquidity range management, and position reset.',
        'category': 'Rebalancing',
        'categories': ['rebalancing'],
        'endpoints': [{'type': 'http', 'url': 'https://agentforge-v2-api.onrender.com/agent/rebalancing'}]
    },
    'Grid Trading': {
        'name': 'AgentForge Grid Trading Agent',
        'description': 'Automated grid trading, DCA, and order placement strategies.',
        'category': 'Grid Trading',
        'categories': ['grid-trading'],
        'endpoints': [{'type': 'http', 'url': 'https://agentforge-v2-api.onrender.com/agent/grid-trading'}]
    },
    'Yield Optimisation': {
        'name': 'AgentForge Yield Optimisation Agent',
        'description': 'Yield farming, liquidity routing, and APR optimisation.',
        'category': 'Yield Optimisation',
        'categories': ['yield-optimization'],
        'endpoints': [{'type': 'http', 'url': 'https://agentforge-v2-api.onrender.com/agent/yield-optimisation'}]
    },
    'Health Factor Monitoring': {
        'name': 'AgentForge Health Factor Monitoring Agent',
        'description': 'Liquidation risk monitoring, collateral health, and lending protection.',
        'category': 'Health Factor Monitoring',
        'categories': ['health-factor'],
        'endpoints': [{'type': 'http', 'url': 'https://agentforge-v2-api.onrender.com/agent/health-factor-monitoring'}]
    }
}

def make_data_uri(metadata):
    json_str = json.dumps(metadata, ensure_ascii=False, separators=(',', ':'))
    b64 = base64.b64encode(json_str.encode()).decode()
    return f'data:application/json;base64,{b64}'

def main():
    private_key = os.getenv('PROVIDER_PRIVATE_KEY')
    rpc_url = os.getenv('RPC_URL')
    if not private_key or not rpc_url:
        raise RuntimeError('PROVIDER_PRIVATE_KEY and RPC_URL must be set in .env')

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 20}))
    if not w3.is_connected():
        raise RuntimeError('RPC not connected')
    if w3.eth.chain_id != CHAIN_ID:
        raise RuntimeError(f'Wrong chain: expected {CHAIN_ID}, got {w3.eth.chain_id}')

    account = w3.eth.account.from_key(private_key)
    registry = w3.eth.contract(address=Web3.to_checksum_address(IDENTITY_REGISTRY), abi=REGISTRY_ABI)

    for category, meta in METADATA.items():
        uri = make_data_uri(meta)
        print(f'Registering {category}...')
        nonce = w3.eth.get_transaction_count(account.address, 'pending')
        tx = registry.functions.register(uri).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'gas': 300000,
            'gasPrice': w3.eth.gas_price,
            'chainId': CHAIN_ID,
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        if receipt.status != 1:
            raise RuntimeError(f'{category} registration failed: {tx_hash.hex()}')
        events = registry.events.Registered().process_receipt(receipt)
        if not events:
            raise RuntimeError('No Registered event found')
        agent_id = int(events[0]['args']['agentId'])
        print(f'✅ {category} registered with agentId: {agent_id}\n')

if __name__ == '__main__':
    main()
