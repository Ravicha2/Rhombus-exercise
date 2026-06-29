# Distributed NL-to-Regex Data Processing Platform

Upload large CSV or Excel datasets, describe patterns in natural language, and replace them asynchronously at scale. Built with Django, React, Celery, Redis, and PySpark.

---

## Architecture

![Architecture Diagram](./docs/diagrams/architecture.png)

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 18+

### 1. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 2. Start Backend

```bash
docker-compose up --build -d
```

The API is available at `http://localhost:8000`.

### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

The UI is available at `http://localhost:3000`.

---

## API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/upload/` | `POST` | Upload CSV/Excel, returns `dataset_id` |
| `/api/jobs/start/` | `POST` | Start a job (dataset_id, prompt, columns, replacement) |
| `/api/jobs/<id>/status/` | `GET` | Job status and progress |
| `/api/jobs/<id>/results/` | `GET` | Paginated results |
| `/api/jobs/<id>/cancel/` | `POST` | Cancel a running job |
