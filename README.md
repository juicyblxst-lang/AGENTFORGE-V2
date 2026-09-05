# AgentForge V2

A BNB Chain agent marketplace that discovers ERC-8004 agents and lets users hire them through the ERC-8183 commerce stack on BSC Testnet.

## Architecture

- `apps/web` — Vite/React marketplace. Wallet connection and user-signed ERC-8183 client transactions live here; marketplace data and execution state come from the API.
- `apps/api` — FastAPI discovery, protocol verification, provider worker, endpoint execution, persistence, and public deliverable endpoint.
- `apps/api/app/discovery.py` — canonical 8004scan indexer integration + normalized identity/capability/endpoint model.
- `apps/api/app/orchestrator.py` — single provider execution path: funded job → ERC-8004 resolution → endpoint execution → ERC-8183 submit → settlement after the policy window.
- `apps/api/app/chain.py` — authoritative BSC Testnet reads and transaction receipt verification.

## BSC Testnet targets

- Chain ID: `97`
- ERC-8004 Identity Registry: `0x8004A818BFB912233c491871b3d84c89A494BD9e`
- ERC-8183 AgenticCommerce: `0xa206c0517b6371c6638cd9e4a42cc9f02a33b0de`
- ERC-8183 EvaluatorRouter: `0xd7d36d66d2f1b608a0f943f722d27e3744f66f25`
- ERC-8183 OptimisticPolicy: `0x4f4678d4439fec812ac7674bb3efb4c8f5fb78a6`
- Payment token: resolved at runtime from `AgenticCommerce.paymentToken()`.

These targets match the current BNB Agent SDK/APEX deployment references. The canonical ERC-8183 lifecycle is `createJob → registerJob → setBudget → approve/fund → submit → settle`; there is no separate provider claim transaction.

## Required environment

Backend: copy `apps/api/.env.example` to `.env`.

For provider execution the external values are:

- `PROVIDER_PRIVATE_KEY` — signer for the provider wallet.
- `PROVIDER_ADDRESS` — must match the ERC-8004 agent wallet/owner for agents the provider accepts.
- `PROVIDER_AGENT_BASE_URL` — public API base including `/erc8183`, e.g. `https://agentforge-api.onrender.com/erc8183`; the SDK uses `/job/{id}/response` for the public deliverable.
- `DATABASE_URL` — Render Postgres connection string in production; omitted locally to use SQLite.
- `CORS_ORIGINS` — deployed Vercel origin(s).
- `EIGHTYFOUR_SCAN_API_KEY` — optional; the public 8004scan indexer is used without a key.

No private credential belongs in Git.

## Local run

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

```bash
cd apps/web
npm install
cp .env.example .env
npm run dev
```

## Tests

```bash
cd apps/api
python -m compileall app tests
python -m unittest discover -s tests -v
```

Frontend production build:

```bash
cd apps/web
npm install
npm run build
```

GitHub Actions runs both backend tests/compile checks and the frontend production build on every push/PR.

## Deployment

### Vercel

- Root directory: `apps/web`
- Build command: `npm run build`
- Output directory: `dist`
- Environment: `VITE_API_URL=https://<your-render-service>.onrender.com`

### Render

`apps/api/render.yaml` defines the web service and a free Postgres database.

- Root directory: `apps/api`
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check: `/health`
- Required secret/config values: `CORS_ORIGINS`, `PROVIDER_PRIVATE_KEY`, `PROVIDER_ADDRESS`, `PROVIDER_AGENT_BASE_URL`.

`PROVIDER_AGENT_BASE_URL` must use the deployed Render URL and include `/erc8183`.

## Required marketplace categories

The discovery layer maps real ERC-8004 metadata into:

- Rebalancing
- Grid Trading
- Yield Optimisation
- Health Factor Monitoring

An agent is not marked as live merely because it exists in the indexer. The UI labels agents as **indexed**, and hire preparation rejects agents without a resolvable executable endpoint or provider wallet.

## Important live-environment limitation

The repository contains no fabricated agents, private keys, transaction hashes, execution results, or fake blockchain states. A fully live demo requires actual BSC Testnet ERC-8004 registrations with reachable endpoints and a provider wallet funded with the required testnet assets. Those are external credentials/ownership dependencies, not repository code.
