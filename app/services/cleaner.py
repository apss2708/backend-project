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
    
    # Strip spaces and commas
    cleaned = amount_str.strip().replace(",", "")
    
    # Find the decimal number inside the string
    # Supports negative numbers (optional minus sign), digits, and optional decimal point
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
        
    cleaned = date_str.strip()
    
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
            record.get("txn_id", ""),
            record.get("date", ""),
            record.get("merchant", ""),
            record.get("amount", ""),
            record.get("currency", ""),
            record.get("status", ""),
            record.get("category", ""),
            record.get("account_id", ""),
            record.get("notes", "")
        )
        if key not in seen:
            seen.add(key)
            deduplicated.append(record)
            
    cleaned_records = []
    for r in deduplicated:
        try:
            # Clean and normalize fields
            cleaned_rec = {
                "txn_id": r.get("txn_id", "").strip() or None,  # Keep nullable/empty
                "date": clean_date(r["date"]),
                "merchant": r["merchant"].strip(),
                "amount": clean_amount(r["amount"]),
                "currency": r["currency"].strip().upper(),
                "status": r["status"].strip().upper(),
                "category": r["category"].strip() or "Uncategorised",
                "account_id": r["account_id"].strip(),
                "notes": r.get("notes", "").strip() or None
            }
            cleaned_records.append(cleaned_rec)
        except CleaningError as e:
            raise CleaningError(f"Failed to clean record: {r}. Reason: {str(e)}")
            
    return cleaned_records
