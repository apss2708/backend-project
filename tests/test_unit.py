import pytest
from decimal import Decimal
from app.services.cleaner import clean_amount, clean_date, clean_records, CleaningError
from app.services.anomaly_detector import detect_anomalies
from app.services.llm_service import extract_json

def test_clean_amount():
    assert clean_amount("$10882.55") == Decimal("10882.55")
    assert clean_amount("10882.55") == Decimal("10882.55")
    assert clean_amount("Rs. 5,000.00") == Decimal("5000.00")
    assert clean_amount("INR 5,000.00") == Decimal("5000.00")
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
    assert cleaned[0]["raw_amount"] == "423.91"
    assert cleaned[0]["raw_date"] == "23-11-2024"

def test_detect_anomalies_only_current_job():
    records = [
        {"account_id": "ACC001", "amount": Decimal("100.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
        {"account_id": "ACC001", "amount": Decimal("150.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
        {"account_id": "ACC001", "amount": Decimal("120.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
        # Exceeds 3x median (median is 120.00, 3x is 360.00, so 500 should be anomalous)
        {"account_id": "ACC001", "amount": Decimal("500.00"), "currency": "INR", "merchant": "Jio Recharge", "is_anomaly": False, "anomaly_reason": None},
        # Domestic merchant USD check
        {"account_id": "ACC002", "amount": Decimal("50.00"), "currency": "USD", "merchant": "Swiggy", "is_anomaly": False, "anomaly_reason": None},
        {"account_id": "ACC002", "amount": Decimal("50.00"), "currency": "INR", "merchant": "Swiggy", "is_anomaly": False, "anomaly_reason": None}
    ]
    
    results = detect_anomalies(records)
    
    assert results[0]["is_anomaly"] is False
    assert results[3]["is_anomaly"] is True
    assert "exceeds 3x median" in results[3]["anomaly_reason"]
    
    assert results[4]["is_anomaly"] is True
    assert "Swiggy" in results[4]["anomaly_reason"]
    assert results[5]["is_anomaly"] is False

def test_extract_json():
    text = "Here is the response: ```json [1, 2, 3] ``` Hope this helps!"
    assert extract_json(text) == "[1, 2, 3]"
