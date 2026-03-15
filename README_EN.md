<h1 align="center">stockclaw</h1>

<p align="center">
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" />
  </a>
  <a href="./skills/stockclaw-open-source/SKILL.md">
    <img src="https://img.shields.io/badge/OpenClaw-Integrated-2F80ED" alt="OpenClaw Integrated" />
  </a>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-Chinese-blue" alt="Language: Chinese" />
  </a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-18-20232A?logo=react&logoColor=61DAFB" alt="React 18" />
  <img src="https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white" alt="Vite 7" />
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
