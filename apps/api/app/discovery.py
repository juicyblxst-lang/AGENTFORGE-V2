import httpx
from web3 import Web3
from .config import BSC_NETWORKS, settings

SCAN = 'https://api.8004scan.io/api/v1'
CATEGORIES = {
    'rebalancing': ['rebalance', 'rebalancing', 'portfolio rebalance', 'position reset', 'range rebalancer'],
    'grid-trading': ['grid trading', 'grid-trading', 'grid bot', 'grid orders', 'grid strategy'],
    'yield-optimization': ['yield optimization', 'yield optimisation', 'yield optimizer', 'yield', 'apr', 'apy', 'liquidity routing'],
    'health-factor': ['health factor', 'healthfactor', 'liquidation', 'lending health', 'liquidation monitor', 'lending guardian'],
}
IDENTITY_ABI=[
    {'type':'function','name':'ownerOf','stateMutability':'view','inputs':[{'name':'tokenId','type':'uint256'}],'outputs':[{'type':'address'}]},
    {'type':'function','name':'getAgentWallet','stateMutability':'view','inputs':[{'name':'agentId','type':'uint256'}],'outputs':[{'type':'address'}]},
    {'type':'function','name':'tokenURI','stateMutability':'view','inputs':[{'name':'tokenId','type':'uint256'}],'outputs':[{'type':'string'}]},
]

def network_config():
    return BSC_NETWORKS[settings.network]

def category_for(text):
    t = text.lower()
    return [k for k, words in CATEGORIES.items() if any(w in t for w in words)]

def _services(a):
    services = a.get('services') or a.get('endpoints') or []
    if isinstance(services, dict): services = list(services.values())
    out = []
    for s in services:
        if isinstance(s, str): out.append({'type':'http','url':s})
        elif isinstance(s, dict):
            url=s.get('endpoint') or s.get('url') or s.get('value')
            if url: out.append({'type':str(s.get('type') or s.get('name') or 'http').lower(),'url':url})
    return out

def _explicit_registry(a, reg0):
    return a.get('agent_registry') or a.get('agentRegistry') or reg0.get('agentRegistry')

def _verify_identity(agent):
    try:
        parts=agent['agentRegistry'].split(':',2)
        if len(parts)!=3 or parts[0]!='eip155' or int(parts[1])!=network_config()['chainId']:
            return {'verified':False,'reason':'registry does not target configured BSC chain'}
        if parts[2].lower()!=network_config()['identityRegistry'].lower():
            return {'verified':False,'reason':'registry address does not match canonical ERC-8004 deployment'}
        w3=Web3(Web3.HTTPProvider(settings.rpc_url,request_kwargs={'timeout':10}))
        if not w3.is_connected() or w3.eth.chain_id!=network_config()['chainId']:
            return {'verified':False,'reason':'identity RPC unavailable or wrong chain'}
        c=w3.eth.contract(address=Web3.to_checksum_address(network_config()['identityRegistry']),abi=IDENTITY_ABI)
        owner=c.functions.ownerOf(int(agent['agentId'])).call()
        wallet=c.functions.getAgentWallet(int(agent['agentId'])).call()
        uri=c.functions.tokenURI(int(agent['agentId'])).call()
        return {'verified':True,'owner':owner,'agentWallet':wallet,'tokenURI':uri}
    except Exception as e:
        return {'verified':False,'reason':str(e)}

def normalize(raw, verify=True):
    data=raw.get('data',raw) if isinstance(raw,dict) else raw
    if isinstance(data,dict): data=data.get('items',data.get('agents',[]))
    out=[]; seen=set()
    for a in data or []:
        if not isinstance(a,dict): continue
        regs=a.get('registrations') or []
        reg0=regs[0] if regs and isinstance(regs[0],dict) else {}
        registry=_explicit_registry(a,reg0)
        aid=str(a.get('token_id',a.get('agent_id',a.get('agentId',a.get('id','')))))
        if not registry or not aid: continue
        key=f'{registry}:{aid}'
        if key in seen: continue
        seen.add(key)
        endpoints=_services(a)
        skills=a.get('skills') or a.get('tags') or []
        if isinstance(skills,str): skills=[skills]
        blob=' '.join(str(a.get(k,'')) for k in ('name','description','skills','domains','tags','categories'))+' '+str(endpoints)
        agent={
            'key':key,'agentId':aid,'agentRegistry':registry,
            'name':a.get('name') or f'Agent #{aid}',
            'description':a.get('description') or 'ERC-8004 registered BNB Chain agent.',
            'owner':a.get('agent_wallet') or a.get('agentWallet') or a.get('owner_address') or a.get('owner') or reg0.get('agentWallet'),
            'categories':category_for(blob),'skills':skills,'endpoints':endpoints,
            'reputation':a.get('total_score',a.get('reputation',a.get('scores'))),
            'active':a.get('active',a.get('is_active',True)),'raw':a,
        }
        if verify:
            proof=_verify_identity(agent)
            if not proof['verified']: continue
            agent['owner']=proof['owner']
            agent['agentWallet']=proof['agentWallet']
            agent['identityVerified']=True
            agent['identityProof']=proof
        out.append(agent)
    return out

async def _get(path,params=None):
    headers={'Accept':'application/json'}
    if settings.scan_api_key: headers['X-API-Key']=settings.scan_api_key
    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        r=await client.get(f'{SCAN}{path}',params=params,headers=headers); r.raise_for_status(); return r.json()

async def discover(limit=100):
    limit=min(max(limit,1),100); offset=0; result=[]; page_size=min(100,limit)
    while len(result)<limit:
        page=await _get('/agents',{'chain_id':network_config()['chainId'],'limit':min(page_size,limit-len(result)),'offset':offset})
        normalized=normalize(page,verify=True); result.extend(normalized)
        raw_items=[]
        if isinstance(page,dict):
            data=page.get('data',page)
            if isinstance(data,dict): raw_items=data.get('items',data.get('agents',[])) or []
            elif isinstance(data,list): raw_items=data
        if not raw_items or len(raw_items)<page_size: break
        offset+=len(raw_items)
    return list({a['key']:a for a in result}.values())[:limit]

async def get_agent(agent_id):
    data=await _get(f'/agents/{network_config()["chainId"]}/{int(agent_id)}')
    found=normalize({'data':[data]},verify=True)
    if not found: raise ValueError('Agent is not a verified ERC-8004 identity on the configured BSC network')
    return found[0]
