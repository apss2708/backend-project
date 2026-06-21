import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any

DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%Y%m%d",
    "%d%m%Y"
]

class CleaningError(Exception):
    pass

def clean_amount(amount_str: str) -> Decimal:
    if not amount_str:
        raise CleaningError("Amount is missing or empty")
    
    # Convert to string and strip spaces/commas
    cleaned = str(amount_str).strip().replace(",", "")
    
    # Strip symbols: $, Rs., INR (case-insensitive)
    cleaned = re.sub(r'(?i)\$|rs\.?|inr', '', cleaned).strip()
    
    # Find the decimal number inside the string
    match = re.search(r'-?\d+(?:\.\d+)?', cleaned)
    if not match:
        raise CleaningError(f"Could not extract numeric amount from: {amount_str}")
        
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        raise CleaningError(f"Invalid decimal format: {amount_str}")

def clean_date(date_str: str) -> str:
    if not date_str:
        raise CleaningError("Date is missing or empty")
        
    cleaned = str(date_str).strip()
    
    # Try the standard formats
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    raise CleaningError(f"Unable to parse date '{date_str}' with supported formats")

def clean_records(raw_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Step 1: Remove exact duplicates
    seen = set()
    deduplicated = []
    
    for record in raw_records:
        # Create a representation of all field values in order
        key = (
            str(record.get("txn_id", "")).strip(),
            str(record.get("date", "")).strip(),
            str(record.get("merchant", "")).strip(),
            str(record.get("amount", "")).strip(),
            str(record.get("currency", "")).strip(),
            str(record.get("status", "")).strip(),
            str(record.get("category", "")).strip(),
            str(record.get("account_id", "")).strip(),
            str(record.get("notes", "")).strip()
        )
        if key not in seen:
            seen.add(key)
            deduplicated.append(record)
            
    cleaned_records = []
    for r in deduplicated:
        try:
            # Clean and normalize fields, preserving raw inputs for model auditing
            cleaned_rec = {
                "txn_id": str(r.get("txn_id", "")).strip() or None,
                "raw_date": str(r["date"]),
                "date": clean_date(r["date"]),
                "merchant": str(r["merchant"]).strip(),
                "raw_amount": str(r["amount"]),
                "amount": clean_amount(r["amount"]),
                "currency": str(r["currency"]).strip().upper(),
                "status": str(r["status"]).strip().upper(),
                "category": str(r["category"]).strip() or "Uncategorised",
                "account_id": str(r["account_id"]).strip(),
                "notes": str(r.get("notes", "")).strip() or None
            }
            cleaned_records.append(cleaned_rec)
        except CleaningError as e:
            raise CleaningError(f"Failed to clean record: {r}. Reason: {str(e)}")
            
    return cleaned_records
