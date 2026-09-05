import httpx
from .config import settings, BSC_TESTNET

SCAN='https://www.8004scan.io/api/v1'
CATEGORIES={
 'rebalancing': ['rebalance','rebalancing','liquidity range','lp range','position reset'],
 'grid-trading': ['grid trading','grid-trading','grid bot','grid orders'],
 'yield-optimization': ['yield','apr','apy','yield optimization','yield optimisation','liquidity routing'],
 'health-factor': ['health factor','liquidation','lending health','liquidation monitor'],
}

def category_for(text):
    t=text.lower()
    return [k for k, words in CATEGORIES.items() if any(w in t for w in words)]

def normalize(raw):
    data=raw.get('data', raw)
    if isinstance(data, dict):
        data=data.get('agents', data.get('items', []))
    out=[]
    seen=set()
    for a in data or []:
        registry=a.get('agent_registry') or a.get('agentRegistry') or f"eip155:{BSC_TESTNET['chainId']}:{BSC_TESTNET['identityRegistry']}"
        aid=str(a.get('agent_id', a.get('agentId', a.get('id',''))))
        key=f'{registry}:{aid}'
        if not aid or key in seen: continue
        seen.add(key)
        services=a.get('services') or a.get('endpoints') or []
        endpoints=[]
        for s in services:
            if isinstance(s,str): endpoints.append({'type':'http','url':s})
            elif isinstance(s,dict):
                url=s.get('endpoint') or s.get('url') or s.get('value')
                if url: endpoints.append({'type':s.get('type','http'),'url':url})
        blob=' '.join(str(a.get(k,'')) for k in ('name','description','skills','domains','tags','categories'))+' '+str(services)
        cats=category_for(blob)
        out.append({
            'key':key,'agentId':aid,'agentRegistry':registry,
            'name':a.get('name') or f'Agent #{aid}',
            'description':a.get('description') or 'ERC-8004 registered BNB Chain agent.',
            'owner':a.get('owner') or a.get('owner_address'),
            'categories':cats,
            'skills':a.get('skills') or a.get('tags') or [],
            'endpoints':endpoints,
            'reputation':a.get('reputation') or a.get('scores') or None,
            'raw':a,
        })
    return out

async def discover(limit=100):
    params={'chain_id':97,'is_testnet':'true','limit':min(max(limit,1),100)}
    headers={'Accept':'application/json'}
    if settings.scan_api_key: headers['X-API-Key']=settings.scan_api_key
    async with httpx.AsyncClient(timeout=15) as client:
        r=await client.get(f'{SCAN}/agents',params=params,headers=headers)
        r.raise_for_status()
        return normalize(r.json())

async def get_agent(agent_id):
    headers={'Accept':'application/json'}
    if settings.scan_api_key: headers['X-API-Key']=settings.scan_api_key
    async with httpx.AsyncClient(timeout=15) as client:
        r=await client.get(f'{SCAN}/agents/97/{agent_id}',headers=headers)
        r.raise_for_status()
        return normalize({'data':[r.json()]})[0]
