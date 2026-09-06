import base64
import json
from urllib.parse import unquote

import httpx
from web3 import Web3
from .config import BSC_NETWORKS, settings

SCAN = 'https://api.8004scan.io/api/v1'
CATEGORIES = {
    'rebalancing': ['rebalance','rebalancing','portfolio rebalance','position reset','range rebalancer','liquidity range','range management','cl range','concentrated liquidity','lp range','liquidity position'],
    'grid-trading': ['grid trading','grid-trading','grid bot','grid orders','grid strategy','grid trader','dca','dollar cost averaging'],
    'yield-optimization': ['yield optimization','yield optimisation','yield optimizer','yield','apr','apy','liquidity routing','yield farming','liquidity mining','lending optimizer','lending optimisation','yield strategy','vault'],
    'health-factor': ['health factor','healthfactor','liquidation','lending health','liquidation monitor','lending guardian','borrow health','collateral health','liquidation risk','venus'],
}
IDENTITY_ABI=[
    {'type':'function','name':'ownerOf','stateMutability':'view','inputs':[{'name':'tokenId','type':'uint256'}],'outputs':[{'type':'address'}]},
    {'type':'function','name':'getAgentWallet','stateMutability':'view','inputs':[{'name':'agentId','type':'uint256'}],'outputs':[{'type':'address'}]},
    {'type':'function','name':'tokenURI','stateMutability':'view','inputs':[{'name':'tokenId','type':'uint256'}],'outputs':[{'type':'string'}]},
    {'type':'event','name':'Registered','anonymous':False,'inputs':[{'indexed':True,'name':'agentId','type':'uint256'},{'indexed':False,'name':'agentURI','type':'string'},{'indexed':True,'name':'owner','type':'address'}]},
]

def network_config(): return BSC_NETWORKS[settings.network]

def category_for(text):
    t=text.lower()
    return [k for k,words in CATEGORIES.items() if any(w in t for w in words)]

def _services(a):
    services=a.get('services') or a.get('endpoints') or []
    if isinstance(services,dict): services=list(services.values())
    out=[]
    for s in services:
        if isinstance(s,str): out.append({'type':'http','url':s})
        elif isinstance(s,dict):
            url=s.get('endpoint') or s.get('url') or s.get('value')
            if url: out.append({'type':str(s.get('type') or s.get('name') or 'http').lower(),'url':url,'skills':s.get('skills') or s.get('capabilities') or [],'domains':s.get('domains') or []})
    return out

def _explicit_registry(a,reg0): return a.get('agent_registry') or a.get('agentRegistry') or reg0.get('agentRegistry')

def _verify_identity(agent):
    try:
        parts=agent['agentRegistry'].split(':',2)
        if len(parts)!=3 or parts[0]!='eip155' or int(parts[1])!=network_config()['chainId']: return {'verified':False,'reason':'registry does not target configured BSC chain'}
        if parts[2].lower()!=network_config()['identityRegistry'].lower(): return {'verified':False,'reason':'registry address does not match canonical ERC-8004 deployment'}
        w3=Web3(Web3.HTTPProvider(settings.rpc_url,request_kwargs={'timeout':10}))
        if not w3.is_connected() or w3.eth.chain_id!=network_config()['chainId']: return {'verified':False,'reason':'identity RPC unavailable or wrong chain'}
        c=w3.eth.contract(address=Web3.to_checksum_address(network_config()['identityRegistry']),abi=IDENTITY_ABI)
        owner=c.functions.ownerOf(int(agent['agentId'])).call(); wallet=c.functions.getAgentWallet(int(agent['agentId'])).call(); uri=c.functions.tokenURI(int(agent['agentId'])).call()
        return {'verified':True,'owner':owner,'agentWallet':wallet,'tokenURI':uri}
    except Exception as e: return {'verified':False,'reason':str(e)}

def _decode_data_uri(uri):
    if not isinstance(uri,str) or not uri.startswith('data:'): return None
    try:
        header,payload=uri.split(',',1)
        return json.loads(base64.b64decode(payload).decode()) if ';base64' in header else json.loads(unquote(payload))
    except Exception: return None

async def _fetch_metadata(uri):
    if not isinstance(uri,str) or not uri: return None
    data=_decode_data_uri(uri)
    if data is not None: return data
    if uri.startswith('ipfs://'): target='https://ipfs.io/ipfs/'+uri.split('ipfs://',1)[1].lstrip('/')
    elif uri.startswith(('https://','http://')): target=uri
    else: return None
    try:
        async with httpx.AsyncClient(timeout=15,follow_redirects=True) as client:
            r=await client.get(target,headers={'Accept':'application/json,text/plain,*/*'}); r.raise_for_status(); return r.json()
    except Exception: return None

def normalize(raw,verify=True):
    data=raw.get('data',raw) if isinstance(raw,dict) else raw
    if isinstance(data,dict): data=data.get('items',data.get('agents',[]))
    out=[]; seen=set()
    for a in data or []:
        if not isinstance(a,dict): continue
        regs=a.get('registrations') or []; reg0=regs[0] if regs and isinstance(regs[0],dict) else {}
        registry=_explicit_registry(a,reg0); aid=str(a.get('token_id',a.get('agent_id',a.get('agentId',a.get('id','')))))
        if not registry or not aid: continue
        key=f'{registry}:{aid}'
        if key in seen: continue
        seen.add(key)
        endpoints=_services(a); skills=a.get('skills') or a.get('tags') or []
        if isinstance(skills,str): skills=[skills]
        domains=a.get('domains') or []
        if isinstance(domains,str): domains=[domains]
        blob=' '.join(str(a.get(k,'')) for k in ('name','description','skills','domains','tags','categories','capabilities','supportedTrust'))+' '+str(endpoints)
        agent={'key':key,'agentId':aid,'agentRegistry':registry,'name':a.get('name') or f'Agent #{aid}','description':a.get('description') or 'ERC-8004 registered BNB Chain agent.','owner':a.get('agent_wallet') or a.get('agentWallet') or a.get('owner_address') or a.get('owner') or reg0.get('agentWallet'),'categories':category_for(blob),'skills':skills,'endpoints':endpoints,'reputation':a.get('total_score',a.get('reputation',a.get('scores'))),'active':a.get('active',a.get('is_active',True)),'raw':a}
        if verify:
            proof=_verify_identity(agent)
            if not proof['verified']: continue
            agent['owner']=proof['owner']; agent['agentWallet']=proof['agentWallet']; agent['identityVerified']=True; agent['identityProof']=proof
        out.append(agent)
    return out

async def _get(path,params=None):
    headers={'Accept':'application/json'}
    if settings.scan_api_key: headers['X-API-Key']=settings.scan_api_key
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        r=await client.get(f'{SCAN}{path}',params=params,headers=headers); r.raise_for_status(); return r.json()

async def _discover_from_chain(limit=100):
    w3=Web3(Web3.HTTPProvider(settings.rpc_url,request_kwargs={'timeout':20}))
    if not w3.is_connected(): raise RuntimeError('BSC RPC unavailable for ERC-8004 discovery')
    if w3.eth.chain_id!=network_config()['chainId']: raise RuntimeError(f'RPC chain mismatch: expected {network_config()["chainId"]}, got {w3.eth.chain_id}')
    address=Web3.to_checksum_address(network_config()['identityRegistry']); contract=w3.eth.contract(address=address,abi=IDENTITY_ABI); latest=w3.eth.block_number
    start=88_179_226 if settings.network=='bsc-testnet' else max(0,latest-1_000_000)
    if start>latest: start=max(0,latest-1_000_000)
    chunk=5_000; events=[]; topic=Web3.keccak(text='Registered(uint256,string,address)').hex()
    for frm in range(start,latest+1,chunk):
        to=min(frm+chunk-1,latest)
        try: events.extend(w3.eth.get_logs({'address':address,'topics':[topic],'fromBlock':frm,'toBlock':to}))
        except Exception:
            for s in range(frm,to+1,1_000):
                try: events.extend(w3.eth.get_logs({'address':address,'topics':[topic],'fromBlock':s,'toBlock':min(s+999,to)}))
                except Exception:
                    continue
    latest_by_id={}
    for ev in events:
        try:
            decoded=contract.events.Registered().process_log(ev); args=decoded['args']; latest_by_id[int(args['agentId'])]=(args['agentURI'],args['owner'])
        except Exception: continue
    result=[]
    for aid,(event_uri,event_owner) in sorted(latest_by_id.items(),reverse=True):
        if len(result)>=limit: break
        try: uri=contract.functions.tokenURI(aid).call(); owner=contract.functions.ownerOf(aid).call(); wallet=contract.functions.getAgentWallet(aid).call()
        except Exception: continue
        metadata=await _fetch_metadata(uri or event_uri)
        if not isinstance(metadata,dict): metadata={}
        metadata=dict(metadata); metadata.update({'agentId':aid,'agentRegistry':f'eip155:{network_config()["chainId"]}:{network_config()["identityRegistry"]}','owner':owner or event_owner,'agentWallet':wallet})
        found=normalize({'data':[metadata]},verify=False)
        if found:
            agent=found[0]; agent['identityVerified']=True; agent['identityProof']={'verified':True,'owner':owner,'agentWallet':wallet,'tokenURI':uri or event_uri}; result.append(agent)
    return result

async def discover(limit=100):
    limit=min(max(limit,1),100)
    params={'chain_id':network_config()['chainId'],'is_testnet':settings.network=='bsc-testnet','limit':limit,'offset':0}
    try:
        page=await _get('/agents',params)
        result=normalize(page,verify=True)
        if result: return list({a['key']:a for a in result}.values())[:limit]
        if settings.network!='bsc-testnet': return []
    except Exception as scan_error:
        if settings.network!='bsc-testnet': raise
    if settings.network=='bsc-testnet':
        return await _discover_from_chain(limit)
    return []

async def get_agent(agent_id):
    try:
        data=await _get(f'/agents/{network_config()["chainId"]}/{int(agent_id)}',{'is_testnet':settings.network=='bsc-testnet'})
        found=normalize({'data':[data]},verify=True)
        if found: return found[0]
    except Exception:
        if settings.network!='bsc-testnet': raise
    if settings.network=='bsc-testnet':
        w3=Web3(Web3.HTTPProvider(settings.rpc_url,request_kwargs={'timeout':20}))
        if not w3.is_connected() or w3.eth.chain_id!=network_config()['chainId']: raise ValueError('BSC testnet RPC unavailable or wrong chain')
        c=w3.eth.contract(address=Web3.to_checksum_address(network_config()['identityRegistry']),abi=IDENTITY_ABI)
        try: uri=c.functions.tokenURI(int(agent_id)).call(); owner=c.functions.ownerOf(int(agent_id)).call(); wallet=c.functions.getAgentWallet(int(agent_id)).call()
        except Exception as e: raise ValueError(f'Agent {agent_id} is not registered on the configured BSC testnet ERC-8004 registry: {e}')
        metadata=await _fetch_metadata(uri)
        if not isinstance(metadata,dict): metadata={}
        metadata.update({'agentId':int(agent_id),'agentRegistry':f'eip155:{network_config()["chainId"]}:{network_config()["identityRegistry"]}','owner':owner,'agentWallet':wallet})
        found=normalize({'data':[metadata]},verify=False)
        if not found: raise ValueError('Agent is not a verified ERC-8004 identity on the configured BSC network')
        found[0]['identityVerified']=True; found[0]['identityProof']={'verified':True,'owner':owner,'agentWallet':wallet,'tokenURI':uri}
        return found[0]
    raise ValueError('Agent is not a verified ERC-8004 identity on the configured BSC network')
