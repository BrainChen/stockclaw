# stockclaw Startup and API Cheatsheet

## Backend Startup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Health Check

```bash
curl -sS http://127.0.0.1:8000/api/health
```

## Chat API

Request body accepts `question` or `query`.

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -d '{"question":"特斯拉最近30天走势"}' \
  http://127.0.0.1:8000/api/chat
```

Markdown output:

```bash
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: text/markdown" \
  -d '{"query":"什么是ROE"}' \
  http://127.0.0.1:8000/api/chat
```

## Eastmoney Data Source (Internal)

Eastmoney realtime fetch is internal-only in stockclaw data layer.
Do not expose or call a public `/api/market/eastmoney/realtime` endpoint.
Use `POST /api/chat` to consume Eastmoney-derived market context.

## Knowledge Base APIs

```bash
curl -sS http://127.0.0.1:8000/api/kb/stats
curl -sS -X POST http://127.0.0.1:8000/api/kb/reindex
curl -sS -X POST \
  -H "Content-Type: application/json" \
  -d '{"query":"what is wacc","top_k":5}' \
  http://127.0.0.1:8000/api/kb/search
```
