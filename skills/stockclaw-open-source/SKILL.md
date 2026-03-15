---
name: stockclaw-open-source
description: Start stockclaw services and call stockclaw APIs from OpenClaw workflows. Use when tasks ask how to boot backend/frontend, verify service health, or invoke public endpoints such as /api/chat and /api/kb/*.
---

# Stockclaw OpenClaw API Runner

## Overview

Start the local stockclaw server stack and call its HTTP APIs in a deterministic way.
Focus only on runtime startup and API invocation, not documentation styling.

## Quick Start

### 1) Start backend API

From repo root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl -sS http://127.0.0.1:8000/api/health
```

Expected response:

```json
{"status":"ok"}
```

### 2) Start frontend (optional for UI mode)

```bash
cd frontend
npm install
npm run build
cd ..
```

Then open `http://127.0.0.1:8000`.

## API Calls

### `POST /api/chat`

JSON mode:

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -d '{"question":"苹果近7天走势怎么样？"}' \
  http://127.0.0.1:8000/api/chat
```

Markdown mode:

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: text/markdown" \
  -d '{"query":"通货膨胀是什么？"}' \
  http://127.0.0.1:8000/api/chat
```

### `GET /api/kb/stats`

```bash
curl -sS http://127.0.0.1:8000/api/kb/stats
```

## Internal Data Source Boundary

- Treat Eastmoney realtime fetch as internal data-layer capability.
- Do not call or expose a public `/api/market/eastmoney/realtime` endpoint.
- Access Eastmoney-derived realtime context through `POST /api/chat` responses only.

## OpenClaw Usage Pattern

When OpenClaw receives requests like "start stockclaw and query the API", execute in this order:

1. Start backend and verify `/api/health`.
2. Call target endpoint with minimal valid payload.
3. Return raw API output or key fields to the user.

## Reference

Read `references/startup-and-api.md` for copy-paste command snippets.
