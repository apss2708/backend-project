import statistics
from decimal import Decimal
from typing import List, Dict, Any, Set

DOMESTIC_ONLY_MERCHANTS: Set[str] = {"swiggy", "ola", "irctc"}

def detect_anomalies(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Step 1: Group amounts by account_id for the current job only
    account_amounts: Dict[str, List[Decimal]] = {}
    for r in records:
        acc_id = r["account_id"]
        if acc_id not in account_amounts:
            account_amounts[acc_id] = []
        account_amounts[acc_id].append(r["amount"])
        
    # Step 2: Compute median per account using current transactions
    medians: Dict[str, Decimal] = {}
    for acc_id, amounts in account_amounts.items():
        if amounts:
            medians[acc_id] = Decimal(str(statistics.median(amounts)))
        else:
            medians[acc_id] = Decimal("0")
            
    # Step 3: Evaluate each record against anomaly rules
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
