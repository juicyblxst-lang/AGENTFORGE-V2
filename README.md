# AgentForge V2

BNB Chain agent marketplace for discovering live ERC-8004 agents and hiring them through ERC-8183 on BSC Testnet.

## Architecture

- `apps/web` — Vite/React marketplace. Wallet signing only; consumes normalized API data and protocol transaction plans.
- `apps/api` — FastAPI discovery, orchestration, execution and SQLite persistence. Provider worker uses the official `@bnbagent` Python SDK.

## Verified protocol targets

BSC Testnet (chain 97):
- ERC-8004 Identity Registry: `0x8004A818BFB912233c491871b3d84c89A494BD9e`
- ERC-8183 AgenticCommerce: `0xa206c0517b6371c6638cd9e4a42cc9f02a33b0de`
- ERC-8183 EvaluatorRouter: `0xd7d36d66d2f1b608a0f943f722d27e3744f66f25`
- ERC-8183 OptimisticPolicy: `0x4f4678d4439fec812ac7674bb3efb4c8f5fb78a6`

The payment token is read from `AgenticCommerce.paymentToken()` at runtime.

## Run

```bash
cd apps/api
python -m venv .venv && source .venv/bin/activate
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

Provider execution requires `PROVIDER_PRIVATE_KEY`, `PROVIDER_ADDRESS`, and a public `PUBLIC_AGENT_BASE_URL`/`EXECUTION_BASE_URL` appropriate to the deployed provider agent. User wallets remain in the browser.

## Production

Web: Vercel, root `apps/web`, build `npm run build`, output `dist`.
API: Render, root `apps/api`, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

## Protocol lifecycle

`createJob → registerJob → provider setBudget → user approve/fund → provider executes selected ERC-8004 endpoint → provider submit → router settle → persistence → result`.

No agent catalog is hardcoded. Discovery is sourced from 8004scan and normalized by the API.
