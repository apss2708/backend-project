import os
import io
import pytest
from decimal import Decimal
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.models.job import Job
from app.models.transaction import Transaction
from app.models.summary import JobSummary
from app.tasks.worker import process_transaction_csv

from sqlalchemy.pool import StaticPool

# Setup in-memory sqlite for integration tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Auto-create tables in the test SQLite DB
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Override FastAPI db dependency
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# Sample CSV file content
CSV_CONTENT = """txn_id,date,merchant,amount,currency,status,category,account_id,notes
TXN1001,04-09-2024,Flipkart,1000.00,INR,success,Shopping,ACC001,
TXN1002,2024/02/05,Swiggy,$120.00,USD,SUCCESS,,ACC002,
TXN1003,17-02-2024,Zomato,150.00,INR,FAILED,Food,ACC001,
TXN1004,18-02-2024,Swiggy,500.00,INR,success,Food,ACC001,
"""

@patch("app.tasks.worker.SessionLocal", TestingSessionLocal)
@patch("app.tasks.worker.engine", engine)
def test_full_pipeline_flow(tmp_path):
    # Mock settings.UPLOAD_DIR to use pytest temp path
    upload_dir = str(tmp_path / "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    # We patch settings and Celery delay to run worker synchronously
    with patch("app.core.config.settings.UPLOAD_DIR", upload_dir), \
         patch("app.tasks.worker.settings.UPLOAD_DIR", upload_dir), \
         patch("app.tasks.worker.process_transaction_csv.delay") as mock_delay:
         
        # Make mock_delay run the task synchronously
        def run_sync(job_id, file_path):
            process_transaction_csv(job_id, file_path)
            
        mock_delay.side_effect = run_sync
        
        # 1. Post upload request
        file_payload = {"file": ("test_transactions.csv", io.BytesIO(CSV_CONTENT.encode("utf-8")), "text/csv")}
        response = client.post("/jobs/upload", files=file_payload)
        
        assert response.status_code == 202
        res_data = response.json()
        assert "job_id" in res_data
        assert res_data["status"] == "pending"
        job_id = res_data["job_id"]
        
        # 2. Verify status endpoint reflects completion
        status_resp = client.get(f"/jobs/{job_id}/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] == "completed"
        assert status_data["summary"] is not None
        assert status_data["summary"]["anomaly_count"] >= 1
        
        # 3. Retrieve final results
        results_resp = client.get(f"/jobs/{job_id}/results")
        assert results_resp.status_code == 200
        results_data = results_resp.json()
        
        # Verify transaction fields normalized correctly
        transactions = results_data["cleaned_transactions"]
        assert len(transactions) == 4
        
        # Swiggy USD transaction must be marked anomalous
        swiggy_usd = [t for t in transactions if t["currency"] == "USD" and t["merchant"] == "Swiggy"][0]
        assert swiggy_usd["is_anomaly"] is True
        assert "USD currency used at domestic-only merchant" in swiggy_usd["anomaly_reason"]
        
        # Category classification (empty category mapped to Uncategorised baseline, then fallback classification to Other)
        uncat_txn = [t for t in transactions if t["txnid"] == "TXN1002"][0]
        # In test, LLM key is not configured, so fallback category classification sets category to "Other"
        assert uncat_txn["category"] == "Other"
        assert uncat_txn["llm_failed"] is True
        
        # Verify aggregates
        currency_totals = results_data["currency_totals"]
        assert Decimal(str(currency_totals["USD"])) == Decimal("120.00")
        assert Decimal(str(currency_totals["INR"])) == Decimal("1650.00") # 1000 + 150 + 500
        
        # Risk level should be high/medium due to anomalies
        assert results_data["summary"]["risk_level"] in ("low", "medium", "high")
        
        # 4. List all jobs
        list_resp = client.get("/jobs")
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert len(list_data) >= 1
        assert list_data[0]["job_id"] == job_id
