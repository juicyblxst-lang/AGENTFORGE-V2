import os
from pathlib import Path
from urllib.parse import urljoin

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
        'inputs': [
            {
                'name': 'agentURI',
                'type': 'string',
            },
        ],
        'outputs': [
            {
                'name': 'agentId',
                'type': 'uint256',
            },
        ],
    },
    {
        'type': 'event',
        'name': 'Registered',
        'anonymous': False,
        'inputs': [
            {
                'indexed': True,
                'name': 'agentId',
                'type': 'uint256',
            },
            {
                'indexed': False,
                'name': 'agentURI',
                'type': 'string',
            },
            {
                'indexed': True,
                'name': 'owner',
                'type': 'address',
            },
        ],
    },
]


CATEGORIES = [
    ('Rebalancing', 'api/metadata/rebalancing'),
    ('Grid Trading', 'api/metadata/grid-trading'),
    ('Yield Optimisation', 'api/metadata/yield-optimisation'),
    ('Health Factor Monitoring', 'api/metadata/health-factor-monitoring'),
]


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f'{name} is required')
    return value


def public_api_base_url() -> str:
    base_url = require_env('PROVIDER_AGENT_BASE_URL').rstrip('/')
    if not base_url.endswith('/erc8183'):
        raise RuntimeError(
            'PROVIDER_AGENT_BASE_URL must point to the existing /erc8183 API base'
        )
    return base_url[:-len('/erc8183')]


def metadata_urls() -> list[tuple[str, str]]:
    base_url = public_api_base_url()
    return [(category, urljoin(f'{base_url}/', path)) for category, path in CATEGORIES]


def main():
    private_key = require_env('PROVIDER_PRIVATE_KEY')
    rpc_url = require_env('RPC_URL')

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 20}))
    if not w3.is_connected():
        raise RuntimeError('BSC Testnet RPC is unavailable')

    actual_chain_id = w3.eth.chain_id
    if actual_chain_id != CHAIN_ID:
        raise RuntimeError(
            f'RPC chain mismatch: expected {CHAIN_ID}, got {actual_chain_id}'
        )

    account = w3.eth.account.from_key(private_key)
    registry_address = Web3.to_checksum_address(IDENTITY_REGISTRY)
    registry = w3.eth.contract(address=registry_address, abi=REGISTRY_ABI)

    for category, agent_uri in metadata_urls():
        print(f'Registering {category}: {agent_uri}')

        nonce = w3.eth.get_transaction_count(account.address, 'pending')
        transaction = registry.functions.register(agent_uri).build_transaction({
            'from': account.address,
            'nonce': nonce,
            'chainId': CHAIN_ID,
            'gas': 300000,
            'gasPrice': w3.eth.gas_price,
        })

        signed = account.sign_transaction(transaction)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)

        if receipt.status != 1:
            raise RuntimeError(
                f'{category} registration failed: {tx_hash.hex()}'
            )

        events = registry.events.Registered().process_receipt(receipt)
        if not events:
            raise RuntimeError(
                f'{category} registration succeeded but no Registered event '
                f'was found in receipt {tx_hash.hex()}'
            )

        event_args = events[0]['args']
        agent_id = int(event_args['agentId'])
        registered_uri = event_args['agentURI']
        owner = event_args['owner']

        if registered_uri != agent_uri:
            raise RuntimeError(
                f'{category} registration URI mismatch in receipt: '
                f'expected {agent_uri}, got {registered_uri}'
            )

        if owner.lower() != account.address.lower():
            raise RuntimeError(
                f'{category} registration owner mismatch in receipt: '
                f'expected {account.address}, got {owner}'
            )

        print(f'  agentId: {agent_id}')
        print(f'  txHash: {tx_hash.hex()}')
        print(f'  owner: {owner}')


if __name__ == '__main__':
    main()
