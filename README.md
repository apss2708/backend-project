# Transaction Processing Pipeline

An asynchronous backend processing pipeline for dirty financial transactions. The system ingests CSV uploads, validates structures, normalizes fields, executes anomaly detection rules, enriches categories in batches using LLMs, builds narratives, and exposes polling endpoints for results retrieval.

Built using **FastAPI**, **Celery**, **Redis**, **PostgreSQL**, and **Google Gemini / OpenAI**.

---

## Folder Structure

```text
app/
  api/
    routes/
      jobs.py         # Upload, status, results, and listing endpoints
  core/
    config.py         # Pydantic environment configurations
    database.py       # SQLAlchemy engine & session helper
    logging.py        # Standard log formatting
  models/
    job.py            # Job status and raw count state
    transaction.py    # Cleaned, anomaly-detected, and LLM-categorized transactions
    summary.py        # Narrative, total spend, and risk analysis
  schemas/
    job.py            # API request/response schemas
    transaction.py    # Transaction response formatting
    summary.py        # Narrative and risk response mapping
  services/
    csv_parser.py     # Stage A: Ingestion and validation
    cleaner.py        # Stage B: Deduplication and normalization
    anomaly_detector.py # Stage C: Median calculations and anomaly flagging
    llm_service.py    # Stage D & E: Batch classification and narrative generator
    summary_builder.py# Aggregator of aggregate values
  tasks/
    worker.py         # Celery pipeline orchestrator task
  main.py             # FastAPI entrypoint and lifespan context
docker/
  api.Dockerfile      # Multi-stage build for the FastAPI web server
  worker.Dockerfile   # Multi-stage build for the Celery task processor
tests/
  test_unit.py        # Cleaners and anomaly detectors unit tests
  test_integration.py # Mock SQLite pipeline runner integration tests
docker-compose.yml    # Service composer (API, Worker, Postgres, Redis)
requirements.txt      # Dependency catalog
```

---

## Architectural Choices & Rationale

1. **FastAPI**: Provides high-performance asynchronous HTTP routing, built-in validation via Pydantic, and automatic Swagger docs (`/docs`).
2. **Celery & Redis**: Offloads long-running CSV parsing, data normalization, and external LLM calls to background processes, ensuring the client upload request completes instantly and stays robust.
3. **PostgreSQL**: Used for ACID compliance, index-backed query speeds, and structured schema integrity (Jobs $\rightarrow$ Transactions $\rightarrow$ Summaries).
4. **Unified LLM Service**: Integrates with both Google Gemini (`gemini-1.5-flash`) and OpenAI (`gpt-4o-mini`) through dynamic runtime switches and API key lookups. Fallback algorithms are integrated to keep the pipeline functional even during total LLM failure or unconfigured API keys.
5. **Lifespan Database Schema Initialization**: Auto-creates Postgres tables on container startup, eliminating manual migration steps for reviewers.

---

## Getting Started

### Prerequisites
- Docker & Docker Compose installed on your host.
- (Optional) Google Gemini or OpenAI API Key.

### Running the Stack
Clone the repository and spin up all services using Docker Compose:

```bash
# Start all services (creates database schema and connects ports automatically)
docker compose up --build
```

The server will bind and be reachable on:
- API endpoint: [http://localhost:8000](http://localhost:8000)
- Interactive documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Configuration

Control the pipeline behavior using standard environment variables (placed in a `.env` file in the root directory):

| Environment Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `gemini` or `openai` | `gemini` |
| `LLM_API_KEY` | Key for selected LLM model | |
| `LLM_MODEL` | Specific model identifier | `gemini-1.5-flash` or `gpt-4o-mini` |
| `LOG_LEVEL` | Log outputs constraints (`INFO`, `DEBUG`, `ERROR`) | `INFO` |

---

## API Endpoints & Usage

### 1. Upload CSV File
Accepts a raw transaction CSV and triggers asynchronous parsing.

**Request:**
```bash
curl -X POST "http://localhost:8000/jobs/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@transactions.csv"
```

**Response:**
```json
{
  "job_id": "0b3aa954-1d94-420d-94f6-ef523292330b",
  "status": "pending",
  "message": "Job created and queued for processing"
}
```

---

### 2. Poll Job Status
Check the status of a specific processing pipeline.

**Request:**
```bash
curl -X GET "http://localhost:8000/jobs/0b3aa954-1d94-420d-94f6-ef523292330b/status"
```

**Response (Processing):**
```json
{
  "job_id": "0b3aa954-1d94-420d-94f6-ef523292330b",
  "status": "processing",
  "filename": "transactions.csv",
  "created_at": "2026-06-21T21:28:18.542Z",
  "completed_at": null,
  "summary": null,
  "error_message": null
}
```

**Response (Completed):**
```json
{
  "job_id": "0b3aa954-1d94-420d-94f6-ef523292330b",
  "status": "completed",
  "filename": "transactions.csv",
  "created_at": "2026-06-21T21:28:18.542Z",
  "completed_at": "2026-06-21T21:28:24.120Z",
  "summary": {
    "total_spend_inr": 12345.67,
    "total_spend_usd": 88.45,
    "anomaly_count": 4,
    "risk_level": "medium"
  },
  "error_message": null
}
```

---

### 3. Retrieve Job Results
Retrieves normalized transactions, anomaly markers, currency aggregates, and the narrative summary.

**Request:**
```bash
curl -X GET "http://localhost:8000/jobs/0b3aa954-1d94-420d-94f6-ef523292330b/results"
```

**Response:**
```json
{
  "job_id": "0b3aa954-1d94-420d-94f6-ef523292330b",
  "status": "completed",
  "cleaned_transactions": [
    {
      "id": "a1f9e20a-8d19-4503-b092-2b3b8ef10928",
      "job_id": "0b3aa954-1d94-420d-94f6-ef523292330b",
      "txnid": "TXN1065",
      "date": "2024-09-04",
      "merchant": "Flipkart",
      "amount": 10882.55,
      "currency": "INR",
      "status": "SUCCESS",
      "category": "Shopping",
      "account_id": "ACC003",
      "notes": "Refund expected",
      "is_anomaly": false,
      "anomaly_reason": null,
      "llm_category": null,
      "llm_raw_response": null,
      "llm_failed": false
    }
  ],
  "anomalies": [],
  "category_breakdown": {
    "Shopping": 10882.55
  },
  "currency_totals": {
    "INR": 10882.55,
    "USD": 0.00
  },
  "summary": {
    "total_spend_inr": 10882.55,
    "total_spend_usd": 0.00,
    "top_merchants": ["Flipkart"],
    "anomaly_count": 0,
    "narrative": "Spending patterns reveal highly contained shopping expenses with zero anomalies detected. Account stands in a solid and low risk condition.",
    "risk_level": "low"
  },
  "llm_failed_rows_count": 0
}
```

---

### 4. List All Jobs
Returns a paginated log of all processed and pending uploads.

**Request:**
```bash
curl -X GET "http://localhost:8000/jobs?status=completed"
```

**Response:**
```json
[
  {
    "job_id": "0b3aa954-1d94-420d-94f6-ef523292330b",
    "filename": "transactions.csv",
    "status": "completed",
    "row_count_raw": 92,
    "row_count_clean": 88,
    "created_at": "2026-06-21T21:28:18.542Z"
  }
]
```

---

## Local Development & Testing

You can spin up local test runs using virtual environment configs:

```bash
# 1. Setup virtual env
python3 -m venv .venv
source .venv/bin/activate

# 2. Install requirements
pip install -r requirements.txt

# 3. Execute unit and integration tests (uses in-memory SQLite + mocked task workers)
PYTHONPATH=. pytest tests/
```

---

## Scalability & Production Planning

If traffic scaled by 100x, the following optimizations are recommended:

1. **Object Storage for Uploads**: Instead of saving uploaded files to local block storage, write directly to AWS S3 or Google Cloud Storage, passing URLs to the Celery worker.
2. **Chunked Ingestion**: For very large CSVs, split rows into chunks (e.g., 5000 rows each) and orchestrate them as a Celery chord or pipeline group to process chunks in parallel across multiple workers.
3. **PostgreSQL Connection Pooler**: Implement PgBouncer to prevent worker scaling from saturating PostgreSQL connection limits.
4. **Rate-limiting & Token Management**: Implement token bucket rate limiters around Gemini/OpenAI client calls to prevent API rate-limit errors when scaling parallel classification calls.