<h1 align="center">stockclaw</h1>

<p align="center">
  <a href="./README.md">
    <img src="https://img.shields.io/badge/%E8%AF%AD%E8%A8%80-%E4%B8%AD%E6%96%87-blue" alt="Language: Chinese" />
  </a>
</p>

<p align="center">
  <img src="./screen_shot.png" alt="Screenshot" />
</p>

`stockclaw` is a financial QA system based on `FastAPI + React + market data + RAG`.
It supports two major query types:

- **Asset market QA**: stock price, trend, and event-driven analysis for A-shares, HK, and US stocks.
- **Financial knowledge QA**: grounded answers with citations from local knowledge base and web retrieval.

## Quick Start

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### 2. Configure environment

```bash
cp .env.example .env.local
```

Required/important options:

- `OPENROUTER_API_KEY`: optional; template fallback is used when empty.
- `OPENROUTER_APP_NAME`: default is `stockclaw`.
- `WEB_SEARCH_ENABLED`: enable/disable web retrieval augmentation.
- `KB_*`: local knowledge base path and indexing parameters.

### 3. Build frontend and start backend

```bash
cd frontend
npm run build
cd ..

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- `http://localhost:8000`
- `http://localhost:8000/api/health`

## Open Source Components

- License: [MIT](./LICENSE)
- Chinese doc: [README.md](./README.md)
- English doc: [README_EN.md](./README_EN.md)
- Contribution guide: [CONTRIBUTING.md](./CONTRIBUTING.md)
