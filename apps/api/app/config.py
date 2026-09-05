import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()
@dataclass(frozen=True)
class Settings:
    network:str=os.getenv('NETWORK','bsc-testnet')
    rpc_url:str=os.getenv('RPC_URL','https://data-seed-prebsc-1-s1.bnbchain.org:8545')
    cors_origins:tuple[str,...]=tuple(x.strip() for x in os.getenv('CORS_ORIGINS','http://localhost:5173').split(',') if x.strip())
    scan_api_key:str|None=os.getenv('EIGHTYFOUR_SCAN_API_KEY') or None
    provider_private_key:str|None=os.getenv('PROVIDER_PRIVATE_KEY') or None
    provider_address:str|None=os.getenv('PROVIDER_ADDRESS') or None
    provider_agent_base_url:str|None=os.getenv('PROVIDER_AGENT_BASE_URL') or None
    database_url:str|None=os.getenv('DATABASE_URL') or None
    database_path:str=os.getenv('DATABASE_PATH','./agentforge.db')
    service_price_units:int=int(os.getenv('SERVICE_PRICE_UNITS','1'))
    poll_interval_seconds:int=int(os.getenv('POLL_INTERVAL_SECONDS','15'))
settings=Settings()
BSC_TESTNET={'chainId':97,'identityRegistry':'0x8004A818BFB912233c491871b3d84c89A494BD9e','commerce':'0xa206c0517b6371c6638cd9e4a42cc9f02a33b0de','router':'0xd7d36d66d2f1b608a0f943f722d27e3744f66f25','policy':'0x4f4678d4439fec812ac7674bb3efb4c8f5fb78a6'}
