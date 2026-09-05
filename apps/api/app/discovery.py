import httpx
from .config import BSC_NETWORKS, settings

# 8004scan documents api.8004scan.io as the canonical programmatic API.
SCAN = 'https://api.8004scan.io/api/v1'
CATEGORIES = {
    'rebalancing': ['rebalance', 'rebalancing', 'portfolio rebalance', 'position reset', 'range rebalancer'],
    'grid-trading': ['grid trading', 'grid-trading', 'grid bot', 'grid orders', 'grid strategy'],
    'yield-optimization': ['yield optimization', 'yield optimisation', 'yield optimizer', 'yield', 'apr', 'apy', 'liquidity routing'],
    'health-factor': ['health factor', 'healthfactor', 'liquidation', 'lending health', 'liquidation monitor', 'lending guardian'],
}


def network_config():
    return BSC_NETWORKS[settings.network]


def category_for(text):
    t = text.lower()
    return [k for k, words in CATEGORIES.items() if any(w in t for w in words)]


def _services(a):
    services = a.get('services') or a.get('endpoints') or []
    if isinstance(services, dict):
        services = list(services.values())
    out = []
    for s in services:
        if isinstance(s, str):
            out.append({'type': 'http', 'url': s})
        elif isinstance(s, dict):
            url = s.get('endpoint') or s.get('url') or s.get('value')
            if url:
                out.append({'type': str(s.get('type') or s.get('name') or 'http').lower(), 'url': url})
    return out


def normalize(raw):
    data = raw.get('data', raw) if isinstance(raw, dict) else raw
    if isinstance(data, dict):
        data = data.get('items', data.get('agents', []))
    network = network_config()
    out, seen = [], set()
    for a in data or []:
        if not isinstance(a, dict):
            continue
        regs = a.get('registrations') or []
        reg0 = regs[0] if regs and isinstance(regs[0], dict) else {}
        registry = (
            a.get('agent_registry') or a.get('agentRegistry') or reg0.get('agentRegistry')
            or f"eip155:{network['chainId']}:{network['identityRegistry']}"
        )
        aid = str(a.get('token_id', a.get('agent_id', a.get('agentId', a.get('id', '')))))
        key = f'{registry}:{aid}'
        if not aid or key in seen:
            continue
        seen.add(key)
        endpoints = _services(a)
        skills = a.get('skills') or a.get('tags') or []
        if isinstance(skills, str):
            skills = [skills]
        blob = ' '.join(str(a.get(k, '')) for k in ('name', 'description', 'skills', 'domains', 'tags', 'categories')) + ' ' + str(endpoints)
        out.append({
            'key': key,
            'agentId': aid,
            'agentRegistry': registry,
            'name': a.get('name') or f'Agent #{aid}',
            'description': a.get('description') or f'ERC-8004 registered BNB Chain agent.',
            'owner': a.get('agent_wallet') or a.get('agentWallet') or a.get('owner_address') or a.get('owner') or reg0.get('agentWallet'),
            'categories': category_for(blob),
            'skills': skills,
            'endpoints': endpoints,
            'reputation': a.get('total_score', a.get('reputation', a.get('scores'))),
            'active': a.get('active', a.get('is_active', True)),
            'raw': a,
        })
    return out


async def _get(path, params=None):
    headers = {'Accept': 'application/json'}
    if settings.scan_api_key:
        headers['X-API-Key'] = settings.scan_api_key
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(f'{SCAN}{path}', params=params, headers=headers)
        r.raise_for_status()
        return r.json()


async def discover(limit=100):
    limit = min(max(limit, 1), 100)
    offset = 0
    result = []
    page_size = min(100, limit)
    while len(result) < limit:
        page = await _get('/agents', {
            'chain_id': network_config()['chainId'],
            'limit': min(page_size, limit - len(result)),
            'offset': offset,
        })
        normalized = normalize(page)
        result.extend(normalized)
        raw_items = []
        if isinstance(page, dict):
            data = page.get('data', page)
            if isinstance(data, dict):
                raw_items = data.get('items', data.get('agents', [])) or []
            elif isinstance(data, list):
                raw_items = data
        if not raw_items or len(raw_items) < page_size:
            break
        offset += len(raw_items)
    dedup = {a['key']: a for a in result}
    return list(dedup.values())[:limit]


async def get_agent(agent_id):
    data = await _get(f'/agents/{network_config()["chainId"]}/{int(agent_id)}')
    found = normalize({'data': [data]})
    if not found:
        raise ValueError('Agent response contained no normalized identity')
    return found[0]
