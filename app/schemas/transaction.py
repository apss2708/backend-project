from pydantic import BaseModel, ConfigDict
from typing import Optional
from decimal import Decimal
from uuid import UUID

class TransactionBase(BaseModel):
    txn_id: Optional[str] = None
    raw_date: Optional[str] = None
    date: Optional[str] = None
    merchant: Optional[str] = None
    raw_amount: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    notes: Optional[str] = None

class TransactionCreate(TransactionBase):
    pass

class TransactionResponse(TransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    is_anomaly: bool
    anomaly_reason: Optional[str] = None
    llm_category: Optional[str] = None
    llm_raw_response: Optional[str] = None
    llm_failed: bool
