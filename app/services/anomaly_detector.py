import statistics
from decimal import Decimal
from typing import List, Dict, Any, Set
from sqlalchemy.orm import Session
from app.models.transaction import Transaction

DOMESTIC_ONLY_MERCHANTS: Set[str] = {"swiggy", "ola", "irctc"}

def detect_anomalies(db: Session, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Step 1: Collect unique account IDs in the current batch
    account_ids = {r["account_id"] for r in records}
    
    # Step 2: Query database for existing transaction amounts per account
    historical_amounts: Dict[str, List[Decimal]] = {}
    for acc_id in account_ids:
        # Query existing completed transaction amounts for this account
        results = db.query(Transaction.amount).filter(Transaction.account_id == acc_id).all()
        historical_amounts[acc_id] = [Decimal(str(r[0])) for r in results]
        
    # Step 3: Combine with current batch to find the comprehensive median per account
    account_all_amounts: Dict[str, List[Decimal]] = {}
    for r in records:
        acc_id = r["account_id"]
        if acc_id not in account_all_amounts:
            # Seed with historical amounts
            account_all_amounts[acc_id] = list(historical_amounts.get(acc_id, []))
        account_all_amounts[acc_id].append(r["amount"])
        
    # Calculate median per account
    medians: Dict[str, Decimal] = {}
    for acc_id, amounts in account_all_amounts.items():
        if amounts:
            medians[acc_id] = Decimal(str(statistics.median(amounts)))
        else:
            medians[acc_id] = Decimal("0")
            
    # Step 4: Evaluate each record against anomaly rules
    for r in records:
        acc_id = r["account_id"]
        amount = r["amount"]
        currency = r["currency"]
        merchant = r["merchant"]
        
        is_anomaly = False
        reasons = []
        
        # Rule 1: Exceeds 3x median
        median = medians.get(acc_id, Decimal("0"))
        if median > 0 and amount > 3 * median:
            is_anomaly = True
            reasons.append(f"Amount {amount} exceeds 3x median amount ({median}) for account {acc_id}")
            
        # Rule 2: USD currency for domestic-only merchants
        if currency == "USD" and merchant.lower() in DOMESTIC_ONLY_MERCHANTS:
            is_anomaly = True
            reasons.append(f"USD currency used at domestic-only merchant: {merchant}")
            
        r["is_anomaly"] = is_anomaly
        r["anomaly_reason"] = "; ".join(reasons) if reasons else None
        
    return records
