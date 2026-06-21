import pytest
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.services.cleaner import clean_amount, clean_date, clean_records, CleaningError
from app.services.anomaly_detector import detect_anomalies
from app.services.llm_service import extract_json

def test_clean_amount():
    assert clean_amount("$10882.55") == Decimal("10882.55")
    assert clean_amount("10882.55") == Decimal("10882.55")
    assert clean_amount("Rs. 5,000.00") == Decimal("5000.00")
    assert clean_amount("-123.45") == Decimal("-123.45")
    with pytest.raises(CleaningError):
        clean_amount("no digits")

def test_clean_date():
    assert clean_date("04-09-2024") == "2024-09-04"
    assert clean_date("2024/02/05") == "2024-02-05"
    assert clean_date("2024-07-15") == "2024-07-15"
    assert clean_date("20240205") == "2024-02-05"
    with pytest.raises(CleaningError):
        clean_date("invalid-date")

def test_clean_records_deduplication():
    raw = [
        {
            "txn_id": "TXN1000",
            "date": "23-11-2024",
            "merchant": "Amazon",
            "amount": "423.91",
            "currency": "INR",
            "status": "failed",
            "category": "",
            "account_id": "ACC004",
            "notes": ""
        },
        # Exact duplicate
        {
            "txn_id": "TXN1000",
            "date": "23-11-2024",
            "merchant": "Amazon",
            "amount": "423.91",
            "currency": "INR",
            "status": "failed",
            "category": "",
            "account_id": "ACC004",
            "notes": ""
        }
    ]
    cleaned = clean_records(raw)
    assert len(cleaned) == 1
    assert cleaned[0]["category"] == "Uncategorised"
    assert cleaned[0]["status"] == "FAILED"

def test_detect_anomalies():
    # Setup in-memory sqlite db for tests
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()
    
    try:
        records = [
            {"account_id": "ACC001", "amount": Decimal("100.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
            {"account_id": "ACC001", "amount": Decimal("150.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
            {"account_id": "ACC001", "amount": Decimal("120.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
            # 3x median check: median is ~120, so 3x is 360. 500 should be anomaly
            {"account_id": "ACC001", "amount": Decimal("500.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
            # Domestic merchant USD check
            {"account_id": "ACC002", "amount": Decimal("50.00"), "currency": "USD", "merchant": "Swiggy", "is_anomaly": False, "anomaly_reason": None},
            {"account_id": "ACC002", "amount": Decimal("50.00"), "currency": "INR", "merchant": "Swiggy", "is_anomaly": False, "anomaly_reason": None}
        ]
        
        results = detect_anomalies(db, records)
        
        # Check median rule
        # ACC001 amounts: [100, 150, 120, 500], median is 135.00
        # 3 * 135 = 405. 500 > 405, so it is an anomaly
        assert results[0]["is_anomaly"] is False
        assert results[3]["is_anomaly"] is True
        assert "exceeds 3x median" in results[3]["anomaly_reason"]
        
        # Check USD rule
        assert results[4]["is_anomaly"] is True
        assert "Swiggy" in results[4]["anomaly_reason"]
        assert results[5]["is_anomaly"] is False
    finally:
        db.close()

def test_extract_json():
    text = "Here is the response: ```json [1, 2, 3] ``` Hope this helps!"
    assert extract_json(text) == "[1, 2, 3]"
