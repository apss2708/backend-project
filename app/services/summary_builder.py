from collections import Counter
from decimal import Decimal
from typing import List, Dict, Any

def compile_job_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_count = len(records)
    
    # Currency totals
    currency_totals: Dict[str, Decimal] = {}
    for r in records:
        curr = r["currency"]
        currency_totals[curr] = currency_totals.get(curr, Decimal("0")) + r["amount"]
        
    # Category breakdown
    category_breakdown: Dict[str, Decimal] = {}
    for r in records:
        cat = r["category"]
        category_breakdown[cat] = category_breakdown.get(cat, Decimal("0")) + r["amount"]
        
    # Top 3 merchants by transaction count
    merchant_counts = Counter(r["merchant"] for r in records)
    top_merchants = [m for m, _ in merchant_counts.most_common(3)]
    
    # Anomaly count & details
    anomalies = [r for r in records if r["is_anomaly"]]
    anomaly_count = len(anomalies)
    
    anomaly_details = []
    for a in anomalies[:5]:  # Limit to top 5 anomalies in context to prevent token overflows
        anomaly_details.append(
            f"Merchant: {a['merchant']}, Amount: {a['amount']} {a['currency']}, Reason: {a['anomaly_reason']}"
        )
        
    return {
        "total_count": total_count,
        "clean_count": total_count,
        "total_spend_inr": currency_totals.get("INR", Decimal("0")),
        "total_spend_usd": currency_totals.get("USD", Decimal("0")),
        "currency_totals": currency_totals,
        "category_spend": {cat: float(val) for cat, val in category_breakdown.items()},
        "category_breakdown": category_breakdown,
        "top_merchants": top_merchants,
        "anomaly_count": anomaly_count,
        "anomaly_details": "; ".join(anomaly_details) if anomaly_details else "None"
    }
